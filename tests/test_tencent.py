"""Offline checks of the trusted RPC boundary, without cloud credentials."""

import asyncio
from types import SimpleNamespace

import pytest
from harbor.agents.installed.qwen_code import QwenCode
from harbor.models.task.config import NetworkMode, NetworkPolicy

from integrations.tencent import (
    Connections,
    PreinstalledQwenCode,
    TencentEnvironment,
    route_request,
)


def policy(*hosts):
    return NetworkPolicy(network_mode=NetworkMode.ALLOWLIST, allowed_hosts=list(hosts))


def test_no_custom_agent_loop():
    assert PreinstalledQwenCode.run is QwenCode.run
    assert PreinstalledQwenCode.populate_context_post_run is QwenCode.populate_context_post_run


@pytest.mark.parametrize(
    "path,method",
    [
        ("https://evil.test", "GET"),
        ("/reset", "POST"),
        ("/predict", "POST"),
        ("/v1/models", "GET"),
        ("/history?url=https://evil.test", "GET"),
        ("/propose", "GET"),
    ],
)
def test_relay_cannot_be_used_as_general_proxy(path, method):
    with pytest.raises(PermissionError):
        route_request(path, method, NetworkPolicy(network_mode=NetworkMode.PUBLIC))


def test_phase_gate_prevents_verifier_model_access():
    assert route_request("/history", "GET", policy("simulator")) == "simulator"
    with pytest.raises(PermissionError):
        route_request("/v1/chat/completions", "POST", policy("simulator"))
    with pytest.raises(PermissionError):
        route_request("/propose", "POST", NetworkPolicy(network_mode=NetworkMode.NO_NETWORK))


def test_explicit_credentials_private_permissions_and_repr(tmp_path):
    path = tmp_path / "connection.txt"
    path.write_text(
        'api_key="example-tencent"\nDASHSCOPE_API_KEY=example-model\n'
        "DASHSCOPE_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1\n"
    )
    path.chmod(0o644)
    with pytest.raises(ValueError, match="0600"):
        Connections.read(path)
    path.chmod(0o600)
    settings = Connections.read(path)
    assert settings.tencent_key == "example-tencent"
    assert "example-tencent" not in repr(settings)
    assert "example-model" not in repr(settings)


def test_agent_commands_use_unprivileged_namespace_and_quote_command():
    calls = []
    environment = object.__new__(TencentEnvironment)
    environment.namespace_pid = 42
    environment.sandbox = SimpleNamespace(
        commands=SimpleNamespace(
            run=lambda *a, **k: (
                calls.append((a, k)) or SimpleNamespace(stdout="ok", stderr="", exit_code=0)
            )
        )
    )
    result = environment._exec_sync("printf '%s' '$secret'", user="agent")
    assert result.return_code == 0
    command = calls[0][0][0]
    assert "nsenter -t 42 -n" in command
    assert "--reuid=agent --regid=agent" in command
    assert "--no-new-privs" in command
    assert "HOME=/home/agent" in command
    with pytest.raises(ValueError):
        environment._exec_sync("anything", user="unexpected")


def test_policy_switch_is_immediate():
    environment = object.__new__(TencentEnvironment)
    selected = policy("simulator")
    asyncio.run(environment._apply_network_policy(selected))
    assert environment.network_policy == selected


def test_model_cannot_be_changed_by_agent():
    import base64
    import json

    environment = object.__new__(TencentEnvironment)
    environment.expected_model = "frozen-model"
    payload = {
        "body": base64.b64encode(json.dumps({"model": "other-model"}).encode()).decode(),
        "method": "POST",
        "path": "/v1/chat/completions",
    }
    with pytest.raises(PermissionError, match="frozen"):
        environment._forward_request("dashscope.aliyuncs.com", payload)


def test_redirects_cannot_forward_credentials():
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.request import ProxyHandler, Request, build_opener

    from integrations.tencent import NoRedirect

    received = []

    class Redirect(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            received.append(self.path)
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/forbidden")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/original",
            headers={"Authorization": "Bearer dummy-private"},
        )
        with pytest.raises(PermissionError, match="redirect"):
            build_opener(ProxyHandler({}), NoRedirect()).open(request)
        assert received == ["/original"]
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def test_sdk_timeout_defers_to_harbor_deadline():
    calls = []
    environment = object.__new__(TencentEnvironment)
    environment.namespace_pid = 42
    environment.sandbox = SimpleNamespace(
        commands=SimpleNamespace(
            run=lambda *a, **k: (
                calls.append(k) or SimpleNamespace(stdout="", stderr="", exit_code=0)
            )
        )
    )
    environment._exec_sync("qwen", user="agent")
    environment._exec_sync("probe", user="root", timeout_sec=30)
    assert [call["timeout"] for call in calls] == [0, 30]


def test_cancel_waits_for_created_sandbox_then_cleans_it():
    import threading

    entered = threading.Event()
    release = threading.Event()
    environment = object.__new__(TencentEnvironment)
    environment.sandbox = None
    stopped = []

    def start_sync():
        entered.set()
        release.wait(timeout=3)
        environment.sandbox = "created-after-cancel"

    async def stop(delete):
        stopped.append(environment.sandbox)
        environment.sandbox = None

    environment._start_sync = start_sync
    environment.stop = stop

    async def scenario():
        pending = asyncio.create_task(environment.start())
        await asyncio.to_thread(entered.wait, 1)
        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending

    asyncio.run(scenario())
    assert stopped == ["created-after-cancel"]
    assert environment.sandbox is None


def test_environment_credentials_are_explicit(monkeypatch):
    monkeypatch.setenv("TENCENT_SANDBOX_API_KEY", "env-tencent")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "env-model")
    settings = Connections.read(None)
    assert settings.tencent_key == "env-tencent"
    assert settings.model_key == "env-model"


def test_trusted_seal_route_is_forwarded_without_model_access():
    assert route_request("/seal", "POST", policy("simulator")) == "simulator"
    assert route_request("/propose", "POST", policy("simulator")) == "simulator"
    with pytest.raises(PermissionError):
        route_request("/seal", "GET", policy("simulator"))
