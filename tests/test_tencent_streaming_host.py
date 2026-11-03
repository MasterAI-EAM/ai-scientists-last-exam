"""Full trusted host / file RPC / sandbox HTTP streaming without cloud access."""

from __future__ import annotations

import asyncio
import http.client
import json
import shlex
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from connectrpc.code import Code
from connectrpc.errors import ConnectError
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
        # Execute the actual publication/abort shell expression against the
        # local private directory, including the idempotent rename fallback.
        subprocess.run(
            ["bash", "-c", command.replace(BRIDGE_DIR, shlex.quote(str(self.root)))],
            check=True,
            capture_output=True,
            text=True,
        )
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


@contextmanager
def unfinished_generation(tmp_path):
    """The real HTTP upstream remains open when publishing its first token fails."""
    send_token = threading.Event()
    disconnected = threading.Event()
    token = b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            assert send_token.wait(5)
            self.wfile.write(token)
            self.wfile.flush()
            self.connection.settimeout(5)
            if self.connection.recv(1) == b"":
                disconnected.set()

    with full_relay(tmp_path, Upstream) as (env, client):
        try:
            yield env, client, send_token, disconnected, token
        finally:
            send_token.set()


def test_data_upload_timeout_is_failed_and_promptly_ends_the_client(tmp_path, monkeypatch):
    with unfinished_generation(tmp_path) as (env, client, send_token, disconnected, _token):
        original_write = env.sandbox.write
        failed_once = threading.Event()

        def fail_data_write(path, data, **kwargs):
            if not failed_once.is_set() and json.loads(data).get("kind") == "data":
                failed_once.set()
                raise TimeoutError("private upstream details must not enter metrics")
            original_write(path, data, **kwargs)

        monkeypatch.setattr(env.sandbox, "write", fail_data_write)
        post(client)
        response = client.getresponse()
        assert response.status == 200
        started = time.monotonic()
        send_token.set()
        try:
            with pytest.raises(http.client.IncompleteRead):
                response.read()
            assert time.monotonic() - started < 3
            timing = wait_for(lambda: env.relay_metrics["requests"])[0]
            assert failed_once.is_set()
            assert disconnected.wait(1)
            assert timing["outcome"] == "failed"
            assert timing["error_type"] == "TimeoutError"
            assert timing["error_stage"]
            assert "cancel_reason" not in timing
            assert "private upstream details" not in json.dumps(env.relay_metrics)
            assert env.relay_metrics["relay_errors"] == 1
        finally:
            response.close()


def test_lost_rename_ack_after_frame_consumption_aborts_without_sequence_deadlock(
    tmp_path, monkeypatch
):
    with unfinished_generation(tmp_path) as (env, client, send_token, disconnected, token):
        sandbox = env.sandbox
        original_run = sandbox.run
        ack_lost = threading.Event()

        def lose_ack_after_data_rename(command, **kwargs):
            fields = shlex.split(command)
            data_frame = (
                fields[:2] == ["mv", "--"]
                and json.loads(sandbox.local(fields[2]).read_text()).get("kind") == "data"
            )
            result = original_run(command, **kwargs)
            if data_frame and not ack_lost.is_set():
                wait_for(lambda: not sandbox.local(fields[3]).exists())
                ack_lost.set()
                raise TimeoutError("rename completed but its acknowledgement was lost")
            return result

        monkeypatch.setattr(sandbox, "run", lose_ack_after_data_rename)
        post(client)
        response = client.getresponse()
        assert response.status == 200
        started = time.monotonic()
        send_token.set()
        try:
            with pytest.raises(http.client.IncompleteRead) as failure:
                response.read()
            assert time.monotonic() - started < 3
            assert failure.value.partial == token
            assert ack_lost.is_set()
            assert disconnected.wait(1)
            timing = wait_for(lambda: env.relay_metrics["requests"])[0]
            assert timing["outcome"] == "failed"
            assert timing["error_type"] == "TimeoutError"
            assert timing["error_stage"]
            assert env.relay_metrics["relay_errors"] == 1
        finally:
            response.close()


def test_persistent_file_upload_failure_uses_command_abort_fallback(tmp_path, monkeypatch):
    with unfinished_generation(tmp_path) as (env, client, send_token, disconnected, _token):
        sandbox = env.sandbox
        original_write = sandbox.write
        original_run = sandbox.run
        uploads_failed = threading.Event()
        abort_commands = []

        def fail_all_uploads_after_first_data(path, data, **kwargs):
            if uploads_failed.is_set() or json.loads(data).get("kind") == "data":
                uploads_failed.set()
                raise TimeoutError("SDK file uploads are unavailable")
            original_write(path, data, **kwargs)

        def record_abort_command(command, **kwargs):
            fields = shlex.split(command)
            if fields[:2] == ["touch", "--"]:
                abort_commands.append(fields[2])
            return original_run(command, **kwargs)

        monkeypatch.setattr(sandbox, "write", fail_all_uploads_after_first_data)
        monkeypatch.setattr(sandbox, "run", record_abort_command)
        post(client)
        response = client.getresponse()
        assert response.status == 200
        started = time.monotonic()
        send_token.set()
        try:
            with pytest.raises(http.client.IncompleteRead):
                response.read()
            assert time.monotonic() - started < 3
            timing = wait_for(lambda: env.relay_metrics["requests"])[0]
            assert timing["outcome"] == "failed"
            assert timing["error_type"] == "TimeoutError"
            assert timing["error_stage"]
            assert uploads_failed.is_set()
            assert disconnected.wait(1)
            assert abort_commands == [f"{BRIDGE_DIR}/responses/{timing['request_id']}.abort"]
            assert env.relay_metrics["relay_errors"] == 1
        finally:
            response.close()


def transport_failure():
    error = ConnectError(Code.UNAVAILABLE, "synthetic SDK stream disconnect")
    error.__cause__ = ConnectionError("synthetic transport failure")
    return error


@pytest.mark.parametrize("kind", ["data", "end"])
@pytest.mark.parametrize("after_consumption", [False, True])
def test_one_rename_retry_recovers_without_reupload_or_replaying_upstream(
    tmp_path, monkeypatch, kind, after_consumption
):
    body = b'data: {"delta":"one"}\n\ndata: [DONE]\n\n'

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(body)

    with full_relay(tmp_path, Upstream) as (env, client):
        sandbox = env.sandbox
        original_run, original_write = sandbox.run, sandbox.write
        failed = False
        writes = []

        def record_write(path, data, **kwargs):
            writes.append(path)
            original_write(path, data, **kwargs)

        def fail_once(command, **kwargs):
            nonlocal failed
            fields = shlex.split(command)
            if (
                not failed
                and fields[:2] == ["mv", "--"]
                and json.loads(sandbox.local(fields[2]).read_text())["kind"] == kind
            ):
                failed = True
                if after_consumption:
                    original_run(command, **kwargs)
                    wait_for(lambda: not sandbox.local(fields[3]).exists())
                raise transport_failure()
            return original_run(command, **kwargs)

        monkeypatch.setattr(sandbox, "write", record_write)
        monkeypatch.setattr(sandbox, "run", fail_once)
        post(client)
        response = client.getresponse()
        assert response.read() == body
        timing = wait_for(lambda: env.relay_metrics["requests"])[0]
        assert failed
        assert timing["outcome"] == "completed"
        assert timing["frame_rename_retries"] == 1
        assert timing["bytes_forwarded"] == len(body)
        assert len(writes) == len(set(writes))
        assert env.relay_metrics["model_requests"] == 1
        assert env.relay_metrics["experiment_requests"] == 0
        assert env.relay_metrics["relay_errors"] == 0
        assert not list((sandbox.root / "responses").iterdir())


def test_persistent_rename_transport_failure_aborts_after_one_retry(tmp_path, monkeypatch):
    with unfinished_generation(tmp_path) as (env, client, send_token, disconnected, _token):
        sandbox = env.sandbox
        original_run = sandbox.run
        attempts = 0

        def fail_data(command, **kwargs):
            nonlocal attempts
            fields = shlex.split(command)
            if (
                fields[:2] == ["mv", "--"]
                and json.loads(sandbox.local(fields[2]).read_text())["kind"] == "data"
            ):
                attempts += 1
                raise transport_failure()
            return original_run(command, **kwargs)

        monkeypatch.setattr(sandbox, "run", fail_data)
        post(client)
        response = client.getresponse()
        send_token.set()
        with pytest.raises(http.client.IncompleteRead):
            response.read()
        timing = wait_for(lambda: env.relay_metrics["requests"])[0]
        assert attempts == 2
        assert disconnected.wait(1)
        assert timing["outcome"] == "failed"
        assert timing["error_type"] == "ConnectError"
        assert timing["error_stage"] == "frame_rename"
        assert timing["frame_rename_retries"] == 1
        assert timing["abort_signal_acknowledged"] is True
        assert env.relay_metrics["model_requests"] == 1


@pytest.fixture
def publisher(tmp_path):
    (tmp_path / "responses").mkdir()
    env = object.__new__(TencentEnvironment)
    env.sandbox = LocalSandbox(tmp_path)
    env._closed = threading.Event()
    env._request_lock = threading.Lock()
    env._metrics_lock = threading.Lock()
    control = tencent.RelayRequest("model")
    ident = "a" * 32
    env._active_requests = {ident: control}
    return env, ident, control


def test_cancel_during_rename_failure_prevents_retry(publisher, monkeypatch):
    env, ident, control = publisher
    attempts = []

    def cancel_and_fail(command, **kwargs):
        attempts.append(command)
        control.cancel("agent_phase_finished")
        raise transport_failure()

    monkeypatch.setattr(env.sandbox, "run", cancel_and_fail)
    with pytest.raises(tencent.RelayCancelled, match="agent_phase_finished"):
        env._publish_frame(ident, 0, {"kind": "headers"})
    assert len(attempts) == 1
    assert "frame_rename_retries" not in control.timing


@pytest.mark.parametrize("error_kind", ["timeout", "deadline", "auth", "command"])
def test_rename_does_not_retry_nontransport_failures(publisher, monkeypatch, error_kind):
    env, ident, _control = publisher
    attempts = []
    original_run = env.sandbox.run

    def fail(command, **kwargs):
        attempts.append(command)
        if error_kind == "command":
            # A real failed mv keeps the uploaded source, so the fallback must
            # fail too instead of treating any nonzero exit as success.
            fields = shlex.split(command)
            return original_run(
                f"mv -- {shlex.quote(fields[2])} {shlex.quote(fields[3] + '/missing/file')}"
                f" || test ! -e {shlex.quote(fields[2])}"
            )
        if error_kind == "deadline":
            error = ConnectError(Code.DEADLINE_EXCEEDED, "deadline")
            error.__cause__ = TimeoutError("deadline")
        elif error_kind == "auth":
            error = ConnectError(Code.UNAUTHENTICATED, "denied")
        else:
            error = TimeoutError("timeout")
        raise error

    monkeypatch.setattr(env.sandbox, "run", fail)
    with pytest.raises((TimeoutError, ConnectError, subprocess.CalledProcessError)):
        env._publish_frame(ident, 0, {"kind": "headers"})
    assert len(attempts) == 1
