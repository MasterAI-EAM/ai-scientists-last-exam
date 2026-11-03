"""A scheduled target gets one isolated trial; failures remain visible."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_suite as suite
from scripts.usage import summarize_usage


def test_native_usage_includes_memory_calls_and_deduplicates_copied_sessions(tmp_path):
    def response(identifier, inputs, outputs, subtype=None):
        event = {
            "event.name": "qwen-code.api_response",
            "response_id": identifier,
            "input_token_count": inputs,
            "output_token_count": outputs,
            "cached_content_token_count": 3,
            "thoughts_token_count": 4,
            "response_text": "private assistant message",
        }
        if subtype:
            event["subagent_type"] = subtype
        return {"systemPayload": {"uiEvent": event}}

    events = [response("one", 100, 20), response("two", 30, 10, "managed-auto-memory-extractor")]
    chats = tmp_path / "trial/agent/qwen-sessions/workspace/chats"
    chats.mkdir(parents=True)
    (chats / "one.jsonl").write_text("\n".join(json.dumps(event) for event in events))
    (chats / "copy.jsonl").write_text(json.dumps(events[0]) + "\n")
    result = summarize_usage(
        tmp_path,
        {"agent_result": {"n_input_tokens": 100, "n_output_tokens": 20, "n_cache_tokens": 3}},
        {"steps": [{"source": "agent", "metrics": {"prompt_tokens": 100}}]},
        {"model_requests": 2},
    )
    assert result["main_trajectory"]["total_tokens"] == 120
    assert result["native_api_responses"]["total_tokens"] == 160
    assert result["native_api_responses"]["model_requests"] == 2
    assert result["native_categories"]["managed_auto_memory"]["total_tokens"] == 40
    assert result["native_request_count_matches_relay"] is True
    assert result["native_api_responses"]["cost_usd"] is None
    assert "private assistant message" not in json.dumps(result)


def test_missing_usage_is_unknown_and_partial_telemetry_does_not_become_zero(tmp_path):
    assert summarize_usage(None, {}, {}, {})["native_api_responses"] is None
    chats = tmp_path / "trial/agent/qwen-sessions/workspace/chats"
    chats.mkdir(parents=True)
    event = {"systemPayload": {"uiEvent": {"event.name": "qwen-code.api_response"}}}
    (chats / "one.jsonl").write_text(json.dumps(event) + "\n{broken\n")
    result = summarize_usage(tmp_path, {}, {}, {"model_requests": 3})
    assert result["native_api_responses"]["input_tokens"] is None
    assert result["native_api_responses"]["total_tokens"] is None
    assert result["native_request_count_matches_relay"] is False
    assert result["malformed_jsonl_lines"] == 1


def make_selection(tmp_path, count=2):
    items = []
    for index in range(count):
        task = tmp_path / "tasks" / f"color_00{index + 1}"
        task.mkdir(parents=True)
        (task / "task.json").write_text(json.dumps({"index": index}))
        config = {
            "task_id": task.name,
            "target": {"id": f"test_{index}", "lab": [70, index, 20], "success_threshold": 1},
        }
        items.append((task, config))
    return items


def arguments(tmp_path):
    return SimpleNamespace(
        tasks=["color_001", "color_002"],
        model="qwen3.5-plus",
        timeout=900,
        asset=Path("external-model"),
        connections=Path("private-connections"),
        output_dir=tmp_path / "summary",
    )


def test_suite_runs_sequentially_once_and_retains_failure_without_leaking_error(
    tmp_path, monkeypatch
):
    selected = make_selection(tmp_path)
    monkeypatch.setattr(suite, "select_tasks", lambda _: selected)
    calls = []

    async def run(args):
        # The schedule is on disk before a single model invocation.
        manifest = json.loads((args.output.parent / "manifest.json").read_text())
        assert len(manifest["tasks"]) == 2
        calls.append(args.task.name)
        if args.task.name == "color_001":
            raise RuntimeError("API key secret-must-never-leak")
        assert calls == ["color_001", "color_002"]
        args.output.write_text(
            json.dumps(
                {
                    "task_id": args.task.name,
                    "engineering_complete": True,
                    "reward": {"success": 1, "reward": 0.8},
                }
            )
        )
        return 0

    monkeypatch.setattr(suite.run_tencent, "run", run)
    args = arguments(tmp_path)
    assert asyncio.run(suite.run_suite(args)) == 1
    report_text = (args.output_dir / "summary.json").read_text()
    report = json.loads(report_text)
    assert calls == ["color_001", "color_002"]
    assert report["n_scheduled"] == report["n_finished"] == 2
    assert report["n_infrastructure_failures"] == 1
    assert report["n_successful_tasks"] == 1
    assert report["mean_reward_valid_trials"] == 0.8
    assert report["success_rate_valid_trials"] == 1
    assert report["results"][0]["reward"] is None
    assert "secret-must-never-leak" not in report_text
    assert report["concurrency"] == 1


def test_parallel_suite_bounds_overlap_and_preserves_order_and_failed_trials(tmp_path, monkeypatch):
    selected = make_selection(tmp_path, count=4)
    monkeypatch.setattr(suite, "select_tasks", lambda _: selected)
    args = arguments(tmp_path)
    args.concurrency = 2
    active, calls, snapshots = set(), [], []
    peak = 0
    original_write = suite.write_json

    async def exercise():
        started = asyncio.Queue()
        release = {task.name: asyncio.Event() for task, _ in selected}
        three_finished = asyncio.Event()

        def write_json(path, data):
            original_write(path, data)
            if path.name == "summary.json":
                snapshots.append(json.loads(path.read_text()))
                if data["n_finished"] == 3:
                    three_finished.set()

        async def run(run_args):
            nonlocal peak
            manifest = json.loads((run_args.output.parent / "manifest.json").read_text())
            assert len(manifest["tasks"]) == 4
            assert manifest["concurrency"] == 2
            assert all(item["task_package_sha256"] for item in manifest["tasks"])
            name = run_args.task.name
            active.add(name)
            calls.append(name)
            peak = max(peak, len(active))
            await started.put(name)
            try:
                await release[name].wait()
                if name == "color_002":
                    raise RuntimeError("private failure detail")
                run_args.output.write_text(
                    json.dumps(
                        {
                            "task_id": name,
                            "engineering_complete": True,
                            "reward": {"success": 1, "reward": 1},
                        }
                    )
                )
            finally:
                active.remove(name)

        monkeypatch.setattr(suite, "write_json", write_json)
        monkeypatch.setattr(suite.run_tencent, "run", run)
        execution = asyncio.create_task(suite.run_suite(args))
        assert {await started.get(), await started.get()} == {"color_001", "color_002"}
        assert len(calls) == 2  # The other two tasks cannot enter before a slot is free.
        release["color_002"].set()
        assert await started.get() == "color_003"
        assert snapshots[-1]["n_finished"] == 1
        assert snapshots[-1]["results"][0]["task_id"] == "color_002"
        release["color_003"].set()
        assert await started.get() == "color_004"
        release["color_004"].set()
        await three_finished.wait()
        assert [item["task_id"] for item in snapshots[-1]["results"]] == [
            "color_002",
            "color_003",
            "color_004",
        ]
        release["color_001"].set()
        return await execution

    async def bounded_exercise():
        return await asyncio.wait_for(exercise(), timeout=10)

    assert asyncio.run(bounded_exercise()) == 1
    assert peak == 2
    assert calls == [task.name for task, _ in selected]
    report = json.loads((args.output_dir / "summary.json").read_text())
    assert report["n_finished"] == 4
    assert report["n_valid_trials"] == 3
    assert report["n_infrastructure_failures"] == 1
    assert [item["task_id"] for item in report["results"]] == calls
    assert report["results"][1]["reward"] is None
    assert "private failure detail" not in json.dumps(report)


@pytest.mark.parametrize("concurrency", [0, -1, True, 1.5, "2", None])
def test_invalid_concurrency_is_rejected_before_any_output_or_runner_call(
    tmp_path, monkeypatch, concurrency
):
    monkeypatch.setattr(suite, "select_tasks", lambda _: make_selection(tmp_path))
    args = arguments(tmp_path)
    args.concurrency = concurrency
    with pytest.raises(ValueError, match="positive integer"):
        asyncio.run(suite.run_suite(args))
    assert not args.output_dir.exists()


def test_requested_concurrency_is_capped_by_predeclared_task_count(tmp_path, monkeypatch):
    selected = make_selection(tmp_path)
    monkeypatch.setattr(suite, "select_tasks", lambda _: selected)
    args = arguments(tmp_path)
    args.concurrency = 8

    async def run(run_args):
        manifest = json.loads((run_args.output.parent / "manifest.json").read_text())
        assert manifest["requested_concurrency"] == 8
        assert manifest["concurrency"] == 2
        run_args.output.write_text(
            json.dumps({"engineering_complete": True, "reward": {"success": 0, "reward": 0}})
        )

    monkeypatch.setattr(suite.run_tencent, "run", run)
    assert asyncio.run(suite.run_suite(args)) == 0


@pytest.mark.parametrize("cli_value, expected", [(None, 4), ("2", 2)])
def test_cli_concurrency_overrides_config_when_provided(tmp_path, monkeypatch, cli_value, expected):
    config = tmp_path / "suite.json"
    config.write_text(json.dumps({"tasks": ["color_001"], "concurrency": 4}))
    argv = ["run_suite.py", "--config", str(config), "--asset", "external-model"]
    if cli_value is not None:
        argv.extend(["--concurrency", cli_value])
    monkeypatch.setattr(suite.sys, "argv", argv)

    async def run(args):
        assert args.concurrency == expected
        return 0

    monkeypatch.setattr(suite, "run_suite", run)
    assert suite.main() == 0


def test_suite_refuses_changed_tasks_and_existing_output(tmp_path, monkeypatch):
    selected = make_selection(tmp_path)
    monkeypatch.setattr(suite, "select_tasks", lambda _: selected)
    calls = []

    async def run(args):
        calls.append(args.task.name)
        (selected[1][0] / "task.json").write_text("changed after schedule")
        args.output.write_text(
            json.dumps(
                {
                    "engineering_complete": True,
                    "reward": {"success": 0, "reward": 0},
                }
            )
        )
        return 0

    monkeypatch.setattr(suite.run_tencent, "run", run)
    args = arguments(tmp_path)
    assert asyncio.run(suite.run_suite(args)) == 1
    assert calls == ["color_001"]
    with pytest.raises(ValueError, match="overwrite"):
        asyncio.run(suite.run_suite(args))


def test_duplicate_tasks_rejected_before_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(suite.run_tencent, "ROOT", tmp_path)
    monkeypatch.setattr(suite.run_tencent, "resolve_task", lambda path: (path, {}))
    with pytest.raises(ValueError, match="duplicate"):
        suite.select_tasks(["color_001", "color_001"])


def test_suite_reports_all_recorded_native_tokens_and_scientific_failures():
    report = suite.aggregate(
        {"tasks": [{}, {}]},
        [
            {
                "engineering_complete": True,
                "reward": {"success": 0, "reward": 0},
                "usage": {
                    "native_api_responses": {
                        "model_requests": 3,
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "total_tokens": 120,
                    }
                },
            },
            {
                "engineering_complete": True,
                "reward": {"success": 1, "reward": 0.75},
                "usage": {
                    "native_api_responses": {
                        "model_requests": 5,
                        "input_tokens": 200,
                        "output_tokens": 30,
                        "total_tokens": 230,
                    }
                },
            },
        ],
    )
    assert report["n_infrastructure_failures"] == 0
    assert report["success_rate_valid_trials"] == 0.5
    assert report["mean_reward_valid_trials"] == 0.375
    assert report["recorded_native_usage_finished_trials"]["total_tokens"] == 350
