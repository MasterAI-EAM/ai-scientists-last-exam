"""Exercise controller persistence, model usage and Tencent lifecycle with doubles."""

import json
from pathlib import Path

import pytest

from aisle import execution, sandbox
from aisle.contracts import AgentSpec
from aisle.engine import Engine
from aisle.execution import run_agent_loop
from aisle.store import Store

ROOT = Path(__file__).resolve().parents[1]
ACTION = {"recipe": {"Red": 20, "Green": 20, "Blue": 20, "water": 140}}


def setup_run(tmp_path, mode="rehearsal", harness="scripted", max_turns=30):
    engine = Engine(Store(tmp_path / "data"))
    agent = AgentSpec(
        agent_id="test",
        model="test-model",
        harness=harness,
        scripted_actions=[ACTION],
        max_turns=max_turns,
    )
    run, _ = engine.create_run(ROOT / "examples/tasks/color_matching/task.yaml", agent, mode=mode)
    return engine, run


def observation():
    return {
        "recipe": ACTION["recipe"],
        "measured_lab": [50, 0, 0],
        "qc": {"status": "passed"},
        "provenance": {"kind": "real"},
    }


def test_waiting_loop_does_not_dispatch_again_and_resumes(tmp_path):
    engine, run = setup_run(tmp_path)
    state = run_agent_loop(engine, run["id"])
    assert state["status"] == "waiting_for_lab"
    assert len(engine.store.list("orders")) == 1
    assert run_agent_loop(engine, run["id"])["pending_order"] == state["pending_order"]
    engine.transition(state["pending_order"], "executing", "test-operator")
    engine.complete(state["pending_order"], observation(), "test-operator")
    assert run_agent_loop(engine, run["id"])["status"] == "completed"
    assert len(engine.store.list("orders")) == 1


def test_crash_after_dispatch_reuses_durable_proposal(tmp_path, monkeypatch):
    engine, run = setup_run(tmp_path)
    checkpoint = engine.checkpoint
    monkeypatch.setattr(
        engine, "checkpoint", lambda *_: (_ for _ in ()).throw(RuntimeError("crash"))
    )
    with pytest.raises(RuntimeError, match="crash"):
        run_agent_loop(engine, run["id"])
    order = engine.store.list("orders")[0]
    assert engine.state(run["id"])["checkpoint"]["pending_proposal"]["key"] == order["key"]
    monkeypatch.setattr(engine, "checkpoint", checkpoint)
    engine.transition(order["id"], "executing", "test-operator")
    engine.complete(order["id"], observation(), "test-operator")
    state = run_agent_loop(engine, run["id"])
    assert state["status"] == "completed"
    assert len(engine.store.list("orders")) == 1
    assert state["cost"]["proposed_samples"] == 1


def test_model_usage_and_validation_feedback_are_controller_recorded(tmp_path, monkeypatch):
    engine, run = setup_run(tmp_path, harness="json")
    monkeypatch.setenv("AISLE_MODEL_BASE_URL", "http://unused")
    monkeypatch.setenv("AISLE_MODEL_API_KEY", "never-log-me")
    calls = []

    class FakeExecutor(sandbox.LocalExecutor):
        def step(self, payload):
            calls.append(payload)
            # An illegal total is returned first. It must not cost a physical attempt.
            if len(calls) == 1:
                action = {"recipe": {"Red": 1, "Green": 0, "Blue": 0, "water": 0}}
            else:
                assert "exactly 200" in payload["state"]["checkpoint"]["validation_error"]
                action = ACTION
            return {
                "kind": "action",
                "action": action,
                "checkpoint": {},
                "usage": {
                    "model_calls": 1,
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "usage_missing": False,
                    "source": "model_api_response",
                },
            }

    monkeypatch.setattr(execution, "LocalExecutor", FakeExecutor)
    state = run_agent_loop(engine, run["id"])
    assert state["status"] == "waiting_for_lab"
    assert state["cost"]["proposed_samples"] == 1
    assert state["cost"]["model_calls"] == 2
    assert state["cost"]["input_tokens"] == 20
    assert len(engine.store.list("orders")) == 1
    assert "never-log-me" not in json.dumps(engine.store.read("runs", run["id"]))
    assert "sim" not in calls[0]["state"]["task"]
    assert "real" not in calls[0]["state"]["task"]


def test_tencent_executor_is_killed_when_waiting(tmp_path, monkeypatch):
    engine, run = setup_run(tmp_path)
    stopped = []

    class FakeTencent(sandbox.LocalExecutor):
        def __exit__(self, *args):
            stopped.append(True)

    monkeypatch.setattr(execution, "TencentExecutor", FakeTencent)
    assert run_agent_loop(engine, run["id"], "tencent")["status"] == "waiting_for_lab"
    assert stopped == [True]


def test_controller_lock_rejects_second_run(tmp_path):
    engine, run = setup_run(tmp_path)
    with (
        execution._run_lock(engine, run["id"]),
        pytest.raises(ValueError, match="active controller"),
    ):
        run_agent_loop(engine, run["id"])


def test_tencent_config_rejects_group_readable_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox.Path, "home", lambda: tmp_path)
    config = tmp_path / ".config/aisle/sandbox.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"TENCENT_SANDBOX_API_KEY":"example"}')
    config.chmod(0o644)
    with pytest.raises(ValueError, match="0600"):
        sandbox.sandbox_settings()
    config.chmod(0o600)
    monkeypatch.setenv("TENCENT_SANDBOX_API_KEY", "environment-override")
    assert sandbox.sandbox_settings()["TENCENT_SANDBOX_API_KEY"] == "environment-override"


def _model_response(content):
    return {
        "id": "response-123",
        "model": "resolved-model",
        "choices": [
            {
                "message": {"content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 15, "completion_tokens": 8},
    }


def _model_env(monkeypatch):
    monkeypatch.setenv("AISLE_MODEL_BASE_URL", "https://model.example/v1")
    monkeypatch.setenv("AISLE_MODEL_API_KEY", "controller-only-key")


def test_proxy_preserves_request_and_keeps_credentials_out_of_worker(tmp_path, monkeypatch):
    engine, run = setup_run(tmp_path, harness="tools")
    _model_env(monkeypatch)
    worker_payloads, forwarded = [], []

    class ObservedWorker(sandbox.LocalExecutor):
        def step(self, payload):
            worker_payloads.append(payload)
            assert "credentials" not in payload
            assert "controller-only-key" not in json.dumps(payload)
            return super().step(payload)

    def chat(request, credentials):
        forwarded.append(request)
        assert credentials["api_key"] == "controller-only-key"
        return _model_response('{"finish":true}')

    monkeypatch.setattr(execution, "LocalExecutor", ObservedWorker)
    monkeypatch.setattr(execution, "_chat", chat)
    result = run_agent_loop(engine, run["id"])
    assert result["status"] == "completed"
    assert len(worker_payloads) == 2
    assert forwarded[0]["tools"][0]["function"]["name"] == "submit_experiment"
    assert forwarded[0]["messages"] == worker_payloads[1]["state"]["checkpoint"]["messages"]
    assert result["cost"]["model_request_attempts"] == 1
    assert result["cost"]["model_calls"] == 1
    assert result["cost"]["input_tokens"] == 15
    assert result["cost"]["output_tokens"] == 8
    assert "controller-only-key" not in json.dumps(engine.store.read("runs", run["id"]))


def test_phase_two_failure_resumes_saved_response_without_second_api_call(tmp_path, monkeypatch):
    engine, run = setup_run(tmp_path, harness="json")
    _model_env(monkeypatch)
    api_calls, failures = [], []

    class InterruptedParser(sandbox.LocalExecutor):
        def step(self, payload):
            if "model_response" in payload and not failures:
                failures.append(True)
                raise RuntimeError("phase-two RPC interrupted")
            return super().step(payload)

    def chat(request, credentials):
        api_calls.append(True)
        return _model_response(json.dumps({"action": ACTION}))

    monkeypatch.setattr(execution, "LocalExecutor", InterruptedParser)
    monkeypatch.setattr(execution, "_chat", chat)
    with pytest.raises(RuntimeError, match="phase-two"):
        run_agent_loop(engine, run["id"])
    persisted = engine.store.read("runs", run["id"])
    assert persisted["pending_model_request"]["status"] == "response_received"
    assert persisted["cost"]["model_calls"] == 1
    assert persisted["cost"].get("usage_unknown_calls", 0) == 0
    resumed = run_agent_loop(engine, run["id"])
    assert resumed["status"] == "waiting_for_lab"
    assert resumed["cost"]["model_calls"] == 1
    assert len(api_calls) == 1 and len(engine.store.list("orders")) == 1


def test_interrupted_api_attempt_is_unknown_and_spends_model_attempt_budget(tmp_path, monkeypatch):
    engine, run = setup_run(tmp_path, harness="json", max_turns=1)
    _model_env(monkeypatch)
    calls = []

    def chat(request, credentials):
        calls.append(True)
        raise execution.WorkerError("model connection failed")

    monkeypatch.setattr(execution, "_chat", chat)
    with pytest.raises(execution.WorkerError):
        run_agent_loop(engine, run["id"])
    state = engine.state(run["id"])
    assert state["cost"]["model_request_attempts"] == 1
    assert state["cost"]["usage_unknown_calls"] == 1
    assert state["cost"]["model_calls"] == 0  # completed responses only; usage is unknown
    assert run_agent_loop(engine, run["id"])["status"] == "completed"
    assert len(calls) == 1


def test_changing_endpoint_during_resume_is_rejected(tmp_path, monkeypatch):
    engine, run = setup_run(tmp_path, harness="json")
    _model_env(monkeypatch)
    monkeypatch.setattr(
        execution, "_chat", lambda *_: _model_response(json.dumps({"action": ACTION}))
    )
    state = run_agent_loop(engine, run["id"])
    engine.transition(state["pending_order"], "executing", "test-operator")
    engine.complete(state["pending_order"], observation(), "test-operator")
    monkeypatch.setenv("AISLE_MODEL_BASE_URL", "https://different.example/v1")
    with pytest.raises(ValueError, match="endpoint changed"):
        run_agent_loop(engine, run["id"])
