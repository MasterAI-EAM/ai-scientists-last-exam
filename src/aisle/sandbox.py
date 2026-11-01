"""Ephemeral Tencent Agent Sandbox execution; no task-private files are uploaded."""

import hashlib
import json
import os
import shlex
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from aisle.agent_worker import WorkerError, step

WORKER = Path(__file__).with_name("agent_worker.py")


def worker_hash():
    return hashlib.sha256(WORKER.read_bytes()).hexdigest()


def sandbox_settings():
    path = Path.home() / ".config" / "aisle" / "sandbox.json"
    settings = {}
    if path.exists():
        if path.stat().st_mode & 0o077:
            raise ValueError("sandbox config must have permissions 0600")
        settings = json.loads(path.read_text())
    for key in ("TENCENT_SANDBOX_API_KEY", "TENCENT_SANDBOX_DOMAIN", "TENCENT_SANDBOX_TEMPLATE"):
        if os.environ.get(key):
            settings[key] = os.environ[key]
    if not settings.get("TENCENT_SANDBOX_API_KEY"):
        raise ValueError("missing TENCENT_SANDBOX_API_KEY")
    return settings


class LocalExecutor:
    metadata = None

    def __enter__(self):
        self.metadata = {"provider": "local", "worker_sha256": worker_hash()}
        return self

    def step(self, payload):
        return step(payload)

    def __exit__(self, *args):
        return False


class TencentExecutor:
    def __init__(self):
        self.sandbox = None
        self.metadata = None
        self.directory = "/home/user/aisle_" + uuid4().hex

    def __enter__(self):
        from e2b_code_interpreter import Sandbox

        settings = sandbox_settings()
        self.sandbox = Sandbox.create(
            template=settings.get("TENCENT_SANDBOX_TEMPLATE", "sdt-275tcueb"),
            api_key=settings["TENCENT_SANDBOX_API_KEY"],
            domain=settings.get("TENCENT_SANDBOX_DOMAIN", "ap-guangzhou.tencentags.com"),
            validate_api_key=False,
            timeout=300,
        )
        try:
            self.sandbox.commands.run("umask 077; mkdir -p " + shlex.quote(self.directory))
            self.sandbox.files.write(self.directory + "/worker.py", WORKER.read_text())
            self.metadata = {
                "provider": "tencent",
                "sandbox_id": self.sandbox.sandbox_id,
                "sdk_version": version("e2b-code-interpreter"),
                "worker_sha256": worker_hash(),
                "template": settings.get("TENCENT_SANDBOX_TEMPLATE", "sdt-275tcueb"),
                "domain": settings.get("TENCENT_SANDBOX_DOMAIN", "ap-guangzhou.tencentags.com"),
            }
        except BaseException:
            self.sandbox.kill()
            raise
        return self

    def step(self, payload):
        # Keep the lease alive during active computation; external waiting closes it.
        self.sandbox.set_timeout(300)
        nonce = uuid4().hex
        input_path = self.directory + "/input_" + nonce + ".json"
        output_path = self.directory + "/output_" + nonce + ".json"
        self.sandbox.commands.run("umask 077; touch " + shlex.quote(input_path))
        self.sandbox.files.write(
            input_path, json.dumps(payload, ensure_ascii=False, allow_nan=False)
        )
        command = "python3 " + " ".join(
            map(
                shlex.quote,
                (
                    self.directory + "/worker.py",
                    input_path,
                    output_path,
                ),
            )
        )
        try:
            command_result = self.sandbox.commands.run(command, timeout=150)
            if command_result.exit_code != 0:
                raise WorkerError("sandbox worker process failed")
            result = json.loads(self.sandbox.files.read(output_path))
            if result.get("kind") == "worker_error":
                raise WorkerError(result.get("error", "sandbox worker failed"))
            return result
        finally:
            self.sandbox.commands.run(
                "rm -f " + shlex.quote(input_path) + " " + shlex.quote(output_path),
                timeout=10,
            )

    def __exit__(self, *args):
        if self.sandbox is not None:
            self.sandbox.kill()
        return False
