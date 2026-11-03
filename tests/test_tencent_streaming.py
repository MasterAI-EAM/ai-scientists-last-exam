"""Exercise the sandbox RPC consumer over real local HTTP connections."""

from __future__ import annotations

import base64
import http.client
import json
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import contextmanager
from http.server import ThreadingHTTPServer

import pytest

from integrations.tencent import RELAY_SOURCE


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.01)
    raise AssertionError("Relay condition was not observed before the test deadline")


@contextmanager
def relay_server(tmp_path):
    namespace = {"__name__": "test_sandbox_relay"}
    # Execute the exact trusted source deployed in the sandbox, not a test imitation.
    exec(compile(RELAY_SOURCE, "<sandbox-relay>", "exec"), namespace)  # noqa: S102
    (tmp_path / "requests").mkdir()
    (tmp_path / "responses").mkdir()
    namespace["root"] = tmp_path
    server = ThreadingHTTPServer(("127.0.0.1", 0), namespace["Handler"])
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


def request_id(tmp_path):
    path = wait_for(lambda: next((tmp_path / "requests").glob("*.json"), None))
    request = json.loads(path.read_text())
    assert request["method"] == "POST"
    assert request["path"] == "/v1/chat/completions"
    return request["id"]


def publish(tmp_path, ident, sequence, frame):
    path = tmp_path / "responses" / f"{ident}.{sequence:08d}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(frame))
    temporary.replace(path)


def data_frame(body):
    return {"kind": "data", "body": base64.b64encode(body).decode()}


def start_request(server):
    client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    client.request("POST", "/v1/chat/completions", body=b"{}")
    return client


def test_headers_and_first_token_arrive_before_the_generation_finishes(tmp_path):
    """A buffered implementation cannot return either of these reads."""
    with relay_server(tmp_path) as server:
        client = start_request(server)
        try:
            ident = request_id(tmp_path)
            publish(
                tmp_path,
                ident,
                0,
                {"kind": "headers", "status": 200, "content_type": "text/event-stream"},
            )
            response = client.getresponse()
            assert response.status == 200
            assert response.getheader("Content-Type") == "text/event-stream"
            first = b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'
            publish(tmp_path, ident, 1, data_frame(first))
            assert response.read1(4096) == first
            # No EOF exists yet: model generation may keep running after the
            # native SDK has received its headers and first actual token.
            assert not (tmp_path / "responses" / f"{ident}.00000002.json").exists()
            final = b'data: {"usage":{"total_tokens":42}}\n\ndata: [DONE]\n\n'
            publish(tmp_path, ident, 2, data_frame(final))
            publish(tmp_path, ident, 3, {"kind": "end"})
            assert response.read() == final
        finally:
            client.close()


def test_stream_preserves_bytes_across_unicode_and_sse_frame_boundaries(tmp_path):
    payload = (
        'data: {"choices":[{"delta":{"content":"颜色"}}]}\n\n'
        'data: {"usage":{"prompt_tokens":7,"completion_tokens":2}}\n\n'
        "data: [DONE]\n\n"
    ).encode()
    # Split in the middle of a multibyte character and an SSE event delimiter.
    unicode_start = payload.index("颜色".encode())
    chunks = [payload[: unicode_start + 1], payload[unicode_start + 1 : -3], payload[-3:]]
    with relay_server(tmp_path) as server:
        client = start_request(server)
        try:
            ident = request_id(tmp_path)
            publish(
                tmp_path,
                ident,
                0,
                {"kind": "headers", "status": 200, "content_type": "text/event-stream"},
            )
            for sequence, body in reversed(list(enumerate(chunks, 1))):
                publish(tmp_path, ident, sequence, data_frame(body))
            publish(tmp_path, ident, 4, {"kind": "end"})
            assert client.getresponse().read() == payload
        finally:
            client.close()


def test_non_stream_error_keeps_http_status_and_json_body(tmp_path):
    body = b'{"error":{"code":"rate_limit","message":"retry later"}}'
    with relay_server(tmp_path) as server:
        client = start_request(server)
        try:
            ident = request_id(tmp_path)
            publish(
                tmp_path,
                ident,
                0,
                {"kind": "headers", "status": 429, "content_type": "application/json"},
            )
            publish(tmp_path, ident, 1, data_frame(body))
            publish(tmp_path, ident, 2, {"kind": "end"})
            response = client.getresponse()
            assert response.status == 429
            assert response.getheader("Content-Type") == "application/json"
            assert response.read() == body
        finally:
            client.close()


@pytest.mark.parametrize("after_headers", [False, True])
def test_disconnected_client_cancels_the_upstream_request(tmp_path, after_headers):
    with relay_server(tmp_path) as server:
        wire = socket.create_connection(("127.0.0.1", server.server_port), timeout=3)
        try:
            wire.sendall(
                b"POST /v1/chat/completions HTTP/1.1\r\nHost: localhost\r\n"
                b"Content-Length: 2\r\n\r\n{}"
            )
            ident = request_id(tmp_path)
            if after_headers:
                publish(
                    tmp_path,
                    ident,
                    0,
                    {"kind": "headers", "status": 200, "content_type": "text/event-stream"},
                )
                publish(tmp_path, ident, 1, data_frame(b"data: first\n\n"))
                received = b""
                while b"data: first" not in received:
                    chunk = wire.recv(4096)
                    assert chunk, "Relay closed before forwarding the first token"
                    received += chunk
            wire.shutdown(socket.SHUT_RDWR)
        finally:
            wire.close()
        wait_for(lambda: (tmp_path / "requests" / f"{ident}.cancel").exists())


def test_incomplete_frame_upload_is_not_consumed_or_reordered(tmp_path):
    with relay_server(tmp_path) as server, ThreadPoolExecutor(max_workers=1) as pool:
        client = start_request(server)
        try:
            ident = request_id(tmp_path)
            publish(
                tmp_path,
                ident,
                0,
                {"kind": "headers", "status": 200, "content_type": "text/event-stream"},
            )
            response = client.getresponse()
            (tmp_path / "responses" / f"{ident}.00000001.tmp").write_text('{"kind":')
            publish(tmp_path, ident, 2, data_frame(b"second"))
            publish(tmp_path, ident, 3, {"kind": "end"})
            reading = pool.submit(response.read)
            with pytest.raises(TimeoutError):
                reading.result(timeout=0.15)
            publish(tmp_path, ident, 1, data_frame(b"first"))
            assert reading.result(timeout=3) == b"firstsecond"
        finally:
            client.close()


def test_upstream_failure_does_not_forge_a_successful_stream_end(tmp_path):
    first = b'data: {"choices":[]}\n\n'
    with relay_server(tmp_path) as server:
        client = start_request(server)
        try:
            ident = request_id(tmp_path)
            publish(
                tmp_path,
                ident,
                0,
                {"kind": "headers", "status": 200, "content_type": "text/event-stream"},
            )
            publish(tmp_path, ident, 1, data_frame(first))
            publish(tmp_path, ident, 2, {"kind": "error"})
            response = client.getresponse()
            with pytest.raises(http.client.IncompleteRead) as error:
                response.read()
            assert error.value.partial == first
        finally:
            client.close()
