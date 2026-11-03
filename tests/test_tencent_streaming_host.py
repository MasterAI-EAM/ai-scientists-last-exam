"""Full trusted host / file RPC / sandbox HTTP streaming without cloud access."""

from __future__ import annotations

import asyncio
import http.client
import json
import shlex
import socket
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from harbor.models.task.config import NetworkMode, NetworkPolicy

from integrations import tencent
from integrations.tencent import BRIDGE_DIR, RELAY_SOURCE, TencentEnvironment


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = predicate()
        if found:
            return found
        time.sleep(0.01)
    raise AssertionError("Expected relay progress did not occur")


class LocalSandbox:
    """Only the SDK filesystem/rename transport is replaced; both HTTP sides are real."""

    def __init__(self, root):
        self.root = root
        self.files = self
        self.commands = self
        self.deleted = False

    def local(self, path):
        assert path.startswith(BRIDGE_DIR + "/")
        return self.root / path.removeprefix(BRIDGE_DIR + "/")

    def list(self, path, **kwargs):
        return [
            SimpleNamespace(name=item.name, path=path + "/" + item.name)
            for item in self.local(path + "/").iterdir()
        ]

    def read(self, path, **kwargs):
        return self.local(path).read_text()

    def write(self, path, data, **kwargs):
        self.local(path).write_text(data)

    def run(self, command, **kwargs):
        fields = shlex.split(command)
        assert fields[:2] == ["mv", "--"]
        self.local(fields[2]).replace(self.local(fields[3]))
        return SimpleNamespace(stdout="", stderr="", exit_code=0)

    def kill(self):
        self.deleted = True


@contextmanager
def full_relay(tmp_path, upstream_handler):
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), upstream_handler)
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()
    root = tmp_path / "rpc"
    (root / "requests").mkdir(parents=True)
    (root / "responses").mkdir()
    namespace = {"__name__": "test_relay"}
    exec(compile(RELAY_SOURCE, "<actual-sandbox-relay>", "exec"), namespace)  # noqa: S102
    namespace["root"] = root
    sandbox_http = ThreadingHTTPServer(("127.0.0.1", 0), namespace["Handler"])
    sandbox_thread = threading.Thread(target=sandbox_http.serve_forever, daemon=True)
    sandbox_thread.start()
    env = object.__new__(TencentEnvironment)
    env.connections = SimpleNamespace(
        model_base=f"http://127.0.0.1:{upstream.server_port}", model_key="private-test-key"
    )
    env.expected_model = "test-model"
    env.sandbox = LocalSandbox(root)
    env._closed = threading.Event()
    env._agent_stopped = False
    env._experiment_lock = threading.Lock()
    env._request_lock = threading.Lock()
    env._active_requests = {}
    env._request_ids = set()
    env._cancelled_requests = set()
    env._metrics_lock = threading.Lock()
    env.relay_metrics = {
        "model_requests": 0,
        "experiment_requests": 0,
        "relay_errors": 0,
        "requests": [],
    }
    env._network_policy = NetworkPolicy(network_mode=NetworkMode.PUBLIC)
    env.private_dir = tmp_path
    env.cleanup_confirmed = False
    env._relay_thread = threading.Thread(target=env._relay_loop, daemon=True)
    env._relay_thread.start()
    client = http.client.HTTPConnection("127.0.0.1", sandbox_http.server_port, timeout=5)
    try:
        yield env, client
    finally:
        client.close()
        if not env._closed.is_set():
            asyncio.run(env.stop())
        sandbox_http.shutdown()
        sandbox_http.server_close()
        upstream.shutdown()
        upstream.server_close()
        sandbox_thread.join(timeout=2)
        upstream_thread.join(timeout=2)


def post(client):
    client.request(
        "POST",
        "/v1/chat/completions",
        body=json.dumps({"model": "test-model", "stream": True, "messages": []}),
        headers={"Content-Type": "application/json"},
    )


def test_full_transport_delivers_real_tokens_while_upstream_is_still_generating(tmp_path):
    release = threading.Event()
    first = 'data: {"delta":"颜色"}\n\n'.encode()
    remainder = b'data: {"usage":{"total_tokens":42}}\n\ndata: [DONE]\n\n'

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            assert self.headers["Authorization"] == "Bearer private-test-key"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(first)
            self.wfile.flush()
            assert release.wait(5)
            for byte in remainder:  # Provider network writes need not align with SSE frames.
                self.wfile.write(bytes([byte]))
            self.wfile.flush()

    with full_relay(tmp_path, Upstream) as (env, client):
        try:
            post(client)
            response = client.getresponse()
            assert response.status == 200
            assert response.read1(4096) == first
            assert not release.is_set()  # This deadlocks/fails under the former response.read().
            release.set()
            assert response.read() == remainder
            timing = wait_for(lambda: env.relay_metrics["requests"])[0]
            assert timing["outcome"] == "completed"
            assert timing["bytes_forwarded"] == len(first + remainder)
            assert timing["data_frames"] < len(remainder)
            assert timing["first_data_forwarded_ms"] <= timing["duration_ms"]
            assert env.relay_metrics["model_requests"] == 1
            assert "private-test-key" not in json.dumps(env.relay_metrics)
        finally:
            release.set()


def test_disconnect_cancels_an_upstream_with_no_further_tokens(tmp_path):
    upstream_disconnected = threading.Event()

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"data: first\n\n")
            self.wfile.flush()
            self.connection.settimeout(5)
            if self.connection.recv(1) == b"":
                upstream_disconnected.set()

    with full_relay(tmp_path, Upstream) as (env, client):
        post(client)
        wire = client.sock
        response = client.getresponse()
        assert response.read1(4096) == b"data: first\n\n"
        wire.shutdown(socket.SHUT_RDWR)
        response.close()
        client.close()
        assert upstream_disconnected.wait(3)
        timing = wait_for(lambda: env.relay_metrics["requests"])[0]
        assert timing["outcome"] == "cancelled"
        assert timing["cancel_reason"] == "client_disconnected"
        assert env.relay_metrics["relay_errors"] == 0
        assert not env._active_requests


def test_stop_cancels_active_upstream_before_sandbox_deletion(tmp_path):
    upstream_disconnected = threading.Event()

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"data: first\n\n")
            self.wfile.flush()
            self.connection.settimeout(5)
            if self.connection.recv(1) == b"":
                upstream_disconnected.set()

    with full_relay(tmp_path, Upstream) as (env, client):
        post(client)
        response = client.getresponse()
        assert response.read1(4096) == b"data: first\n\n"
        sandbox = env.sandbox
        asyncio.run(env.stop())
        assert upstream_disconnected.wait(1)
        assert sandbox.deleted and env.cleanup_confirmed
        assert not env._active_requests
        metrics = json.loads((tmp_path / "relay-metrics.json").read_text())
        assert metrics["requests"][0]["outcome"] == "cancelled"
        assert metrics["requests"][0]["cancel_reason"] == "environment_stopped"
        response.close()


def test_short_content_length_is_a_failed_request_and_truncated_client_response(tmp_path):
    partial = b'{"answer":"unfinished'

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(partial) + 100))
            self.end_headers()
            self.wfile.write(partial)
            self.wfile.flush()
            self.close_connection = True

    with full_relay(tmp_path, Upstream) as (env, client):
        post(client)
        response = client.getresponse()
        assert response.status == 200
        with pytest.raises(http.client.IncompleteRead) as failure:
            response.read()
        assert failure.value.partial == partial
        timing = wait_for(lambda: env.relay_metrics["requests"])[0]
        assert timing["outcome"] == "failed"
        assert timing["error_type"] == "IncompleteRead"
        assert env.relay_metrics["relay_errors"] == 1
        response.close()


def test_sse_eof_without_done_is_not_reported_as_a_successful_generation(tmp_path):
    partial = b'data: {"choices":[{"delta":{"content":"unfinished"}}]}\n\n'

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(partial)
            self.wfile.flush()
            self.close_connection = True

    with full_relay(tmp_path, Upstream) as (env, client):
        post(client)
        response = client.getresponse()
        with pytest.raises(http.client.IncompleteRead) as failure:
            response.read()
        assert failure.value.partial == partial
        timing = wait_for(lambda: env.relay_metrics["requests"])[0]
        assert timing["outcome"] == "failed"
        assert env.relay_metrics["relay_errors"] == 1
        response.close()


@contextmanager
def stalled_frame_relay(tmp_path, monkeypatch):
    """Hold one genuine SDK frame upload while stop interrupts its HTTP upstream."""
    write_entered = threading.Event()
    release_write = threading.Event()
    write_returned = threading.Event()
    upstream_disconnected = threading.Event()
    deletion_seen_by_writer = []

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"data: first\n\n")
            self.wfile.flush()
            self.connection.settimeout(5)
            if self.connection.recv(1) == b"":
                upstream_disconnected.set()

    with full_relay(tmp_path, Upstream) as (env, client):
        sandbox = env.sandbox
        original_write = sandbox.write

        def slow_write(path, data, **kwargs):
            write_entered.set()
            assert release_write.wait(5), "Test did not release the blocked SDK upload"
            deletion_seen_by_writer.append(sandbox.deleted)
            original_write(path, data, **kwargs)
            write_returned.set()

        monkeypatch.setattr(sandbox, "write", slow_write)
        try:
            post(client)
            assert write_entered.wait(3)
            yield SimpleNamespace(
                env=env,
                sandbox=sandbox,
                release_write=release_write,
                write_returned=write_returned,
                upstream_disconnected=upstream_disconnected,
                deletion_seen_by_writer=deletion_seen_by_writer,
            )
        finally:
            release_write.set()
            if env._closed.is_set():
                env._relay_thread.join(timeout=3)


def test_stop_drains_a_slow_frame_upload_before_metrics_and_sandbox_cleanup(tmp_path, monkeypatch):
    with stalled_frame_relay(tmp_path, monkeypatch) as relay:
        timer = threading.Timer(0.2, relay.release_write.set)
        timer.start()
        try:
            asyncio.run(relay.env.stop())
        finally:
            timer.cancel()
            relay.release_write.set()
            timer.join(timeout=1)
        assert relay.write_returned.is_set()
        assert relay.deletion_seen_by_writer == [False]
        assert relay.upstream_disconnected.wait(1)
        assert not relay.env._relay_thread.is_alive()
        assert not relay.env._active_requests
        assert relay.sandbox.deleted and relay.env.cleanup_confirmed
        metrics = json.loads((tmp_path / "relay-metrics.json").read_text())
        cleanup = json.loads((tmp_path / "cleanup.json").read_text())
        for report in (metrics, cleanup):
            assert report["relay_drained"] is True
            assert report["unfinished_request_ids"] == []
        assert metrics["requests"][0]["outcome"] == "cancelled"
        assert metrics["requests"][0]["cancel_reason"] == "environment_stopped"


def test_stop_reports_pending_requests_when_bounded_drain_expires(tmp_path, monkeypatch):
    monkeypatch.setattr(tencent, "RELAY_DRAIN_SECONDS", 0.05)
    with stalled_frame_relay(tmp_path, monkeypatch) as relay:
        active_ids = set(relay.env._active_requests)
        assert len(active_ids) == 1
        asyncio.run(relay.env.stop())
        assert not relay.write_returned.is_set()
        assert relay.env._relay_thread.is_alive()
        metrics = json.loads((tmp_path / "relay-metrics.json").read_text())
        cleanup = json.loads((tmp_path / "cleanup.json").read_text())
        for report in (metrics, cleanup):
            assert report["relay_drained"] is False
            assert set(report["unfinished_request_ids"]) == active_ids
        pending = {entry["request_id"]: entry for entry in metrics["requests"]}
        assert set(pending) == active_ids
        for entry in pending.values():
            assert entry["outcome"] == "pending"
            assert entry["cancel_requested"] is True
            assert entry["cancel_reason"] == "environment_stopped"
        assert relay.upstream_disconnected.wait(1)
        relay.release_write.set()
        relay.env._relay_thread.join(timeout=3)
        assert not relay.env._relay_thread.is_alive()


def test_verifier_boundary_drains_model_requests_before_returning(tmp_path, monkeypatch):
    upstream_disconnected = threading.Event()

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"data: first\n\n")
            self.wfile.flush()
            self.connection.settimeout(5)
            if self.connection.recv(1) == b"":
                upstream_disconnected.set()

    with full_relay(tmp_path, Upstream) as (env, client):
        post(client)
        response = client.getresponse()
        assert response.read1(4096) == b"data: first\n\n"
        commands = []

        def run_root(command, **kwargs):
            commands.append(command)
            return SimpleNamespace(stdout="", stderr="", exit_code=0)

        monkeypatch.setattr(env, "_run_root", run_root)
        try:
            env._stop_agent_for_verifier()
            assert commands[:2] == [
                "pkill -KILL -u agent || test $? -eq 1",
                "! pgrep -u agent >/dev/null",
            ]
            assert env._agent_stopped
            assert not env._active_requests
            assert upstream_disconnected.wait(1)
            timing = env.relay_metrics["requests"][0]
            assert timing["outcome"] == "cancelled"
            assert timing["cancel_reason"] == "agent_phase_finished"
            assert not env._closed.is_set()
            assert not env.sandbox.deleted
        finally:
            response.close()
