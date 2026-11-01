"""HTTP-level checks for the two real model harnesses; no live API spending."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from aisle.agent_worker import WorkerError, step
from aisle.contracts import AgentSpec


@pytest.fixture
def model_server():
    responses, requests = [], []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, self.headers.get("Authorization"), body))
            response = responses.pop(0)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield responses, requests, f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()
    thread.join()
    server.server_close()


def payload(base, harness="json"):
    agent = AgentSpec(agent_id="mock", model="test-model", harness=harness).model_dump()
    return {
        "state": {
            "task": {"action_schema": {"type": "object"}},
            "mode": "sim",
            "history": [],
            "checkpoint": {},
        },
        "agent": agent,
        "credentials": {"base_url": base, "api_key": "test-private-key"},
    }


def response(message, usage=None):
    return {
        "choices": [{"message": message}],
        "model": "resolved-model",
        "usage": usage if usage is not None else {"prompt_tokens": 11, "completion_tokens": 7},
    }


def test_json_retries_and_preserves_usage(model_server):
    replies, requests, base = model_server
    replies.extend(
        [
            response({"content": '```json\n{"action": {}}\n```'}),
            response({"content": '{"action":{"recipe":{"water":200}}}'}),
        ]
    )
    data = payload(base)
    first = step(data)
    assert first["kind"] == "retry"
    assert first["usage"]["input_tokens"] == 11
    data["state"]["checkpoint"] = first["checkpoint"]
    second = step(data)
    assert second["kind"] == "action"
    assert second["checkpoint"]["model_turns"] == 2
    assert requests[0][0] == "/v1/chat/completions"
    assert requests[0][1] == "Bearer test-private-key"
    assert requests[0][2]["temperature"] == 0
    assert requests[1][2]["messages"][-1]["role"] == "user"
    assert "test-private-key" not in json.dumps(second)


def test_native_tool_result_is_returned_after_real_resume(model_server):
    replies, requests, base = model_server
    replies.extend(
        [
            response(
                {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_a",
                            "type": "function",
                            "function": {
                                "name": "submit_experiment",
                                "arguments": '{"recipe":{"water":200}}',
                            },
                        }
                    ],
                }
            ),
            response({"content": '{"finish":true}'}),
        ]
    )
    data = payload(base, "tools")
    first = step(data)
    assert first["kind"] == "action"
    assert requests[0][2]["tools"][0]["function"]["name"] == "submit_experiment"
    data["state"]["checkpoint"] = first["checkpoint"]
    data["state"]["history"] = [{"order_id": "exp_1", "observation": {"measured_lab": [3, 4, 5]}}]
    final = step(data)
    assert final["kind"] == "finish"
    tool_reply = requests[-1][2]["messages"][-1]
    assert tool_reply["role"] == "tool" and tool_reply["tool_call_id"] == "call_a"
    assert json.loads(tool_reply["content"])["experiment_result"]["order_id"] == "exp_1"


def test_turn_limit_does_not_call_model_and_skills_fail_explicitly():
    data = payload("unused")
    data["state"]["checkpoint"] = {"model_turns": 30}
    assert step(data)["reason"] == "model_turn_limit"
    data["agent"]["skills"] = ["unknown-skill"]
    with pytest.raises(WorkerError, match="skills"):
        step(data)


def test_bad_tool_arguments_are_closed_before_retry(model_server):
    replies, _requests, base = model_server
    replies.append(
        response(
            {
                "tool_calls": [
                    {
                        "id": "bad",
                        "type": "function",
                        "function": {
                            "name": "submit_experiment",
                            "arguments": '{"x": NaN}',
                        },
                    }
                ]
            }
        )
    )
    result = step(payload(base, "tools"))
    assert result["kind"] == "retry"
    assert result["checkpoint"]["messages"][-1]["role"] == "tool"
    assert result["checkpoint"]["messages"][-1]["tool_call_id"] == "bad"
    assert "awaiting_tool" not in result["checkpoint"]


def test_completion_token_parameter_is_configurable(model_server):
    replies, requests, base = model_server
    replies.append(response({"content": '{"finish":true}'}))
    data = payload(base)
    data["agent"]["token_parameter"] = "max_completion_tokens"
    assert step(data)["kind"] == "finish"
    assert requests[0][2]["max_completion_tokens"] == 2048
    assert "max_tokens" not in requests[0][2]


def test_controller_transport_builds_and_parses_without_credentials():
    data = payload("unused", "tools")
    data.pop("credentials")
    data["model_transport"] = "controller"
    data["agent"]["extra_body"] = {"enable_thinking": False}
    prepared = step(data)
    assert prepared["kind"] == "model_request"
    assert prepared["request"]["enable_thinking"] is False
    assert prepared["checkpoint"].get("model_turns", 0) == 0
    data["state"]["checkpoint"] = prepared["checkpoint"]
    data["model_response"] = response({"content": '{"finish":true}'})
    parsed = step(data)
    assert parsed["kind"] == "finish"
    assert parsed["checkpoint"]["model_turns"] == 1


def test_extra_body_cannot_replace_harness_messages():
    data = payload("unused")
    data["model_transport"] = "controller"
    data["agent"]["extra_body"] = {"messages": []}
    with pytest.raises(WorkerError, match="override"):
        step(data)
