"""Durable Agent loops. Sandbox owns decisions; controller transports model HTTP."""

import fcntl
import os
from contextlib import contextmanager
from time import time
from urllib.parse import urlsplit
from uuid import uuid4

from jsonschema import ValidationError

from aisle.agent_worker import WorkerError, _chat, _usage
from aisle.contracts import AgentSpec, canonical, digest
from aisle.sandbox import LocalExecutor, TencentExecutor


@contextmanager
def _run_lock(engine, run_id):
    engine.store.read("runs", run_id)
    directory = engine.store.root / "controller-locks"
    directory.mkdir(exist_ok=True)
    with (directory / (digest(run_id) + ".lock")).open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("this run already has an active controller") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _add_usage(run, usage):
    for key in ("model_calls", "input_tokens", "output_tokens"):
        value = usage.get(key, 0)
        if type(value) is not int or value < 0:
            raise WorkerError("worker returned invalid model usage")
        run["cost"][key] = run["cost"].get(key, 0) + value
    if usage:
        run["cost"]["usage_missing_calls"] = run["cost"].get("usage_missing_calls", 0) + int(
            usage.get("usage_missing", False)
        )


def _persist_output(engine, run_id, output, usage_recorded=False):
    checkpoint = output["checkpoint"]
    if output["kind"] == "action":
        checkpoint["pending_proposal"] = {
            "action": output["action"],
            "key": "agent_" + uuid4().hex,
        }
    if output["kind"] == "finish":
        checkpoint["pending_finish"] = output.get("reason", "agent_finished")
    usage = output.get("usage", {})
    with engine.store.connect() as db:
        run = engine.store.get(db, "runs", run_id)
        run["checkpoint"] = checkpoint
        if not usage_recorded:
            _add_usage(run, usage)
            if usage:
                engine.store.event(
                    db,
                    run_id,
                    "model_response",
                    {
                        "usage": usage,
                        "requested_model": run["agent"]["model"],
                        "response_model": output.get("response_model"),
                        "kind": output["kind"],
                    },
                )
        if usage_recorded:
            run["pending_model_request"] = None
        engine.store.put(db, "runs", run)


def _bind_endpoint(engine, run_id, base_url):
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("model base URL must be an HTTP(S) endpoint")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("model base URL must not contain credentials, query or fragment")
    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions"
    with engine.store.connect() as db:
        run = engine.store.get(db, "runs", run_id)
        if run.get("model_endpoint") not in {None, endpoint}:
            raise ValueError("model endpoint changed since the run was bound")
        run["model_endpoint"] = endpoint
        engine.store.put(db, "runs", run)
    return endpoint


def _start_request(engine, run_id, output, endpoint):
    request_id = "model_" + uuid4().hex
    request_evidence = engine.store.evidence(canonical(output["request"]).encode())
    pending = {
        "id": request_id,
        "status": "started",
        "request": output["request"],
        "request_sha256": digest(output["request"]),
        "started_at": time(),
    }
    with engine.store.connect() as db:
        run = engine.store.get(db, "runs", run_id)
        run["checkpoint"] = output["checkpoint"]
        run["pending_model_request"] = pending
        run["cost"]["model_request_attempts"] = run["cost"].get("model_request_attempts", 0) + 1
        engine.store.put(db, "runs", run)
        engine.store.event(
            db,
            run_id,
            "model_request_started",
            {
                "request_id": request_id,
                "request_sha256": pending["request_sha256"],
                "request_evidence": request_evidence,
                "endpoint": endpoint,
                "model": output["request"].get("model"),
            },
        )
    return pending


def _response_received(engine, run_id, request_id, response):
    usage = _usage(response)
    response_evidence = engine.store.evidence(canonical(response).encode())
    with engine.store.connect() as db:
        run = engine.store.get(db, "runs", run_id)
        pending = run["pending_model_request"]
        if pending["id"] != request_id or pending["status"] != "started":
            raise ValueError("model request is not awaiting a response")
        pending.update(status="response_received", response=response, received_at=time())
        _add_usage(run, usage)
        engine.store.put(db, "runs", run)
        engine.store.event(
            db,
            run_id,
            "model_response",
            {
                "request_id": request_id,
                "usage": usage,
                "requested_model": pending["request"].get("model"),
                "response_model": response.get("model"),
                "response_id": response.get("id"),
                "response_evidence": response_evidence,
                "finish_reason": (response.get("choices") or [{}])[0].get("finish_reason"),
                "latency_seconds": pending["received_at"] - pending["started_at"],
            },
        )


def _request_unknown(engine, run_id, reason):
    with engine.store.connect() as db:
        run = engine.store.get(db, "runs", run_id)
        pending = run.get("pending_model_request")
        if pending and pending["status"] == "started":
            run["cost"]["usage_unknown_calls"] = run["cost"].get("usage_unknown_calls", 0) + 1
            engine.store.event(
                db,
                run_id,
                "model_usage_unknown",
                {
                    "request_id": pending["id"],
                    "request_sha256": pending["request_sha256"],
                    "reason": reason,
                    "may_have_reached_provider": True,
                },
            )
            run["pending_model_request"] = None
            engine.store.put(db, "runs", run)


def _finish(engine, run_id, reason):
    engine.finish(run_id)
    with engine.store.connect() as db:
        engine.store.event(db, run_id, "agent_finished", {"reason": reason})
    return engine.state(run_id)


def run_agent_loop(engine, run_id, provider="local"):
    """Run until completion or external waiting with no model credentials in Sandbox.

    The worker builds the exact model request and parses the response. The trusted
    controller forwards that request unchanged, stores the response before parsing,
    and owns scoring. A failed phase-two RPC resumes from the saved response without
    another API call. An interrupted API request is explicitly marked usage-unknown.
    SQLite/file locks require one controller host in this MVP.
    """
    if provider not in {"local", "tencent"}:
        raise ValueError("provider must be local or tencent")
    with _run_lock(engine, run_id):
        state = engine.state(run_id)
        if state["status"] != "running":
            return state
        agent = AgentSpec.model_validate(state["agent"])
        if agent.skills:
            raise ValueError("skills are not supported by harness version 1.0")
        if agent.harness_version != "1.0":
            raise ValueError("only harness version 1.0 is implemented")
        credentials, endpoint = {}, None
        if agent.harness != "scripted":
            credentials = {
                "base_url": os.environ.get(agent.base_url_env, ""),
                "api_key": os.environ.get(agent.api_key_env, ""),
            }
            if not all(credentials.values()):
                raise ValueError("model base URL and API key environment variables are required")
            endpoint = _bind_endpoint(engine, run_id, credentials["base_url"])
        # No live controller holds the OS lock now; a 'started' request left by a
        # dead process has uncertain provider consumption, not zero consumption.
        _request_unknown(engine, run_id, "previous_controller_interrupted")
        executor_type = LocalExecutor if provider == "local" else TencentExecutor
        with executor_type() as executor:
            previous_worker = state["checkpoint"].get("worker_sha256")
            if previous_worker and previous_worker != executor.metadata["worker_sha256"]:
                raise ValueError("worker implementation changed since the previous checkpoint")
            metadata = {
                **executor.metadata,
                "model_transport": "controller",
                "harness_fingerprint": digest(
                    {
                        "agent": agent.model_dump(),
                        "worker_sha256": executor.metadata["worker_sha256"],
                    }
                ),
            }
            with engine.store.connect() as db:
                engine.store.event(db, run_id, "executor_started", metadata)
            try:
                while True:
                    state = engine.state(run_id)
                    if state["status"] != "running":
                        return state
                    checkpoint = state["checkpoint"]
                    if checkpoint.get("pending_finish"):
                        return _finish(engine, run_id, checkpoint["pending_finish"])
                    pending = checkpoint.get("pending_proposal")
                    if pending:
                        try:
                            engine.submit(run_id, pending["action"], pending["key"])
                        except (ValueError, ValidationError) as exc:
                            if engine.state(run_id)["status"] != "running":
                                raise
                            checkpoint["validation_error"] = (
                                str(exc.message)[:500]
                                if isinstance(exc, ValidationError)
                                else str(exc)[:500]
                            )
                        checkpoint.pop("pending_proposal", None)
                        engine.checkpoint(run_id, checkpoint)
                        continue
                    record = engine.store.read("runs", run_id)
                    request = record.get("pending_model_request")
                    payload = {
                        "state": state,
                        "agent": agent.model_dump(),
                        "model_transport": "controller",
                    }
                    usage_recorded = bool(request and request["status"] == "response_received")
                    if usage_recorded:
                        payload["model_response"] = request["response"]
                    elif (
                        agent.harness != "scripted"
                        and state["cost"].get("model_request_attempts", 0) >= agent.max_turns
                    ):
                        return _finish(engine, run_id, "model_request_attempt_limit")
                    output = executor.step(payload)
                    output["checkpoint"]["worker_sha256"] = executor.metadata["worker_sha256"]
                    if output.get("kind") == "model_request":
                        if usage_recorded:
                            raise WorkerError("worker did not consume the saved model response")
                        request = _start_request(engine, run_id, output, endpoint)
                        try:
                            response = _chat(request["request"], credentials)
                            _response_received(engine, run_id, request["id"], response)
                        except BaseException:
                            _request_unknown(engine, run_id, "model_transport_interrupted")
                            raise
                        continue
                    if output.get("kind") not in {"action", "finish", "retry"}:
                        raise WorkerError("invalid worker response kind")
                    _persist_output(engine, run_id, output, usage_recorded=usage_recorded)
            except BaseException as exc:
                with engine.store.connect() as db:
                    engine.store.event(db, run_id, "executor_error", {"type": type(exc).__name__})
                raise
            finally:
                with engine.store.connect() as db:
                    engine.store.event(db, run_id, "executor_stopped", metadata)
