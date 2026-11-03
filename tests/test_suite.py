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


def make_selection(tmp_path):
    items = []
    for index in range(2):
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
