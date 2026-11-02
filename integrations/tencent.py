"""Harbor's native Qwen Code harness on Tencent AGS via its E2B-compatible SDK.

The provider transports HTTP only. Qwen Code owns all reasoning and tool use;
Harbor owns trial orchestration and runs the unmodified task verifier in Tencent.
A root-owned network namespace exposes only a narrow localhost RPC relay. Model
credentials and the scientific simulator stay on the trusted host. This adapter
is intentionally task-specific: it does not claim Docker Compose compatibility.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import io
import json
import os
import re
import shlex
import tarfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from e2b.sandbox.commands.command_handle import CommandExitException
from e2b_code_interpreter import Sandbox
from harbor.agents.installed.qwen_code import QwenCode
from harbor.environments.base import BaseEnvironment, ExecResult, transfer_tar_filter
from harbor.environments.capabilities import EnvironmentCapabilities
from harbor.models.task.config import NetworkMode, NetworkPolicy

QWEN_VERSION = "0.26.5"
QWEN_INTEGRITY = (
    "iqcBqLQDmKvOtRcVvF78l7bf0NpdymGFBo0qNY0ausPezht+PLXkh15vnIILaBKtM4BabtHSv60xWftMomJ7hw=="
)
BRIDGE_DIR = "/root/aisle-rpc"


@dataclass(frozen=True)
class Connections:
    tencent_key: str = field(repr=False)
    model_key: str = field(repr=False)
    model_base: str
    template: str = "sdt-275tcueb"
    domain: str = "ap-guangzhou.tencentags.com"

    @classmethod
    def read(cls, path: Path | None) -> Connections:
        """Read only the explicitly supplied private connection export."""
        if path is None:
            try:
                return cls(
                    tencent_key=os.environ["TENCENT_SANDBOX_API_KEY"],
                    model_key=os.environ["DASHSCOPE_API_KEY"],
                    model_base=os.environ.get(
                        "DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"
                    ),
                    template=os.environ.get("TENCENT_SANDBOX_TEMPLATE", "sdt-275tcueb"),
                    domain=os.environ.get("TENCENT_SANDBOX_DOMAIN", "ap-guangzhou.tencentags.com"),
                )
            except KeyError:
                raise ValueError("Set TENCENT_SANDBOX_API_KEY and DASHSCOPE_API_KEY") from None
        if path.stat().st_mode & 0o077:
            raise ValueError("Connection export must have mode 0600 (or stricter)")
        content = path.read_text()

        def extract(pattern: str) -> str:
            match = re.search(pattern, content)
            if not match:
                raise ValueError("Required connection setting missing from private export")
            return match.group(1)

        return cls(
            tencent_key=extract(r'api_key="([^\"]+)"'),
            model_key=extract(r"DASHSCOPE_API_KEY=(\S+)"),
            model_base=extract(r"DASHSCOPE_API_BASE=(\S+)"),
        )


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PermissionError("Upstream redirects are not permitted")


def verified_bundle(path: Path) -> bytes:
    payload = path.read_bytes()
    if base64.b64encode(hashlib.sha512(payload).digest()).decode() != QWEN_INTEGRITY:
        raise ValueError("Qwen Code bundle does not match the pinned npm SHA512 integrity")
    return payload


def route_request(path: str, method: str, policy: NetworkPolicy) -> str:
    """Resolve only two explicitly supported upstreams, never a client URL."""
    host = None
    if (
        path in {"/history", "/health"}
        and method == "GET"
        or path in {"/propose", "/seal"}
        and method == "POST"
    ):
        host = "simulator"
    elif path == "/v1/chat/completions" and method == "POST":
        host = "dashscope.aliyuncs.com"
    if host is None:
        raise PermissionError("Unsupported relay route")
    if policy.network_mode == NetworkMode.NO_NETWORK or (
        policy.network_mode == NetworkMode.ALLOWLIST and host not in policy.allowed_hosts
    ):
        raise PermissionError("Destination is disabled in the current Harbor phase")
    return host


# Runs as root inside an otherwise disconnected Linux network namespace. Neither
# agent nor verifier can write the queue; only trusted provider commands can.
RELAY_SOURCE = r"""
import base64, fcntl, json, os, socket, struct, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
root = Path("/root/aisle-rpc")
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
    req = struct.pack("16sh", b"lo", 0)
    flags = struct.unpack("16sh", fcntl.ioctl(sock, 0x8913, req)[:18])[1]
    fcntl.ioctl(sock, 0x8914, struct.pack("16sh", b"lo", flags | 1))
(root / "pid").write_text(str(os.getpid()))
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self): self.handle_request()
    def do_POST(self): self.handle_request()
    def handle_request(self):
        count = int(self.headers.get("Content-Length", "0"))
        if count < 0 or count > 4000000:
            self.send_error(413); return
        ident = uuid.uuid4().hex
        req = {"id": ident, "method": self.command, "path": self.path,
               "body": base64.b64encode(self.rfile.read(count)).decode()}
        pending = root / "requests" / (ident + ".tmp")
        pending.write_text(json.dumps(req))
        pending.rename(pending.with_suffix(".json"))
        response = root / "responses" / (ident + ".json")
        deadline = time.monotonic() + 300
        while not response.exists() and time.monotonic() < deadline: time.sleep(.05)
        if not response.exists(): self.send_error(504); return
        data = json.loads(response.read_text()); response.unlink()
        body = base64.b64decode(data["body"])
        self.send_response(data["status"])
        self.send_header("Content-Type", data.get("content_type", "application/json"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try: self.wfile.write(body)
        except BrokenPipeError: pass
ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
"""


class TencentEnvironment(BaseEnvironment):
    """Single-task provider: Tencent executes harness, tools, and verifier."""

    def __init__(
        self,
        *args,
        connections_path: str | None,
        qwen_bundle: str,
        simulator_url: str,
        private_dir: str,
        expected_model: str,
        seal_token_path: str,
        sandbox_timeout_secs: int = 1800,
        **kwargs,
    ):
        self.connections = Connections.read(Path(connections_path) if connections_path else None)
        if self.connections.model_base != "https://dashscope.aliyuncs.com/compatible-mode/v1":
            raise ValueError("This task adapter requires the frozen Dashscope destination")
        self.qwen_bundle = Path(qwen_bundle)
        self.simulator_url = simulator_url.rstrip("/")
        if not self.simulator_url.startswith("http://127.0.0.1:"):
            raise ValueError("Trusted simulator must be a host loopback HTTP service")
        self.expected_model = expected_model
        self.seal_token_path = Path(seal_token_path)
        self._agent_stopped = False
        self._experiment_lock = threading.Lock()
        self.private_dir = Path(private_dir)
        self.private_dir.mkdir(parents=True, exist_ok=True)
        self.sandbox_timeout_secs = sandbox_timeout_secs
        self.sandbox = None
        self.namespace_pid = None
        self._closed = threading.Event()
        self.cleanup_confirmed = False
        self._relay_thread = None
        self._request_ids: set[str] = set()
        self.relay_metrics = {"model_requests": 0, "experiment_requests": 0, "relay_errors": 0}
        kwargs["enable_environment_dir_upload"] = False
        super().__init__(*args, **kwargs)

    @staticmethod
    def type() -> str:
        return "tencent-ags"

    @property
    def capabilities(self) -> EnvironmentCapabilities:
        return EnvironmentCapabilities(
            disable_internet=True,
            network_allowlist=True,
            network_allowlist_hostnames=True,
            network_allowlist_ipv4_addresses=True,
            dynamic_network_policy=True,
        )

    def _validate_definition(self):
        if not (self.environment_dir / "color_tool.py").is_file():
            raise ValueError("Tencent adapter expects the color_001 environment")

    def validate_network_policy_support(self, network_policy=None):
        super().validate_network_policy_support(network_policy)
        policy = network_policy or self.network_policy
        if set(policy.allowed_hosts) - {
            "simulator",
            "dashscope.aliyuncs.com",
            "127.0.0.1",
            "localhost",
        }:
            raise ValueError("Tencent relay supports only simulator and Dashscope")

    async def _apply_network_policy(self, network_policy):
        # The root relay validates the policy on every request, in addition to
        # the namespace having no external interface or route at any phase.
        self._network_policy = network_policy

    def _run_root(self, command, timeout=60):
        return self.sandbox.commands.run(command, user="root", timeout=timeout)

    async def start(self, force_build=False):
        startup = asyncio.create_task(asyncio.to_thread(self._start_sync))
        try:
            await asyncio.shield(startup)
        except BaseException:
            # Cancelling to_thread does not stop its OS thread. Wait for it to
            # return ownership of any sandbox before cleaning up, even on cancel.
            with contextlib.suppress(Exception):
                await startup
            await self.stop(delete=True)
            raise

    def _start_sync(self):
        bundle = verified_bundle(self.qwen_bundle)
        self.sandbox = Sandbox.create(
            template=self.connections.template,
            api_key=self.connections.tencent_key,
            validate_api_key=False,
            domain=self.connections.domain,
            timeout=self.sandbox_timeout_secs,
        )
        self._run_root(
            "set -eu; useradd -m -s /bin/bash agent; "
            "mkdir -p /opt/qwen-code /app /workspace /logs/agent /logs/verifier /tests "
            "/root/aisle-rpc/requests /root/aisle-rpc/responses /home/agent/.nvm /run/aisle-verifier; "
            "chmod 700 /run/aisle-verifier; "
            "chmod 700 /root/aisle-rpc; "
            "chown -R agent:agent /workspace /logs/agent /home/agent; "
            "printf '127.0.0.1 simulator\\n' >> /etc/hosts; "
            "printf 'export PATH=/usr/local/bin:/usr/bin:/bin:$PATH\\n' "
            "> /home/agent/.nvm/nvm.sh"
        )
        # AGS rejects/ times out on a single large multipart upload. Transfer
        # immutable runtime bytes in bounded pieces, then verify before extract.
        pieces = [
            (i, bundle[offset : offset + 1024 * 1024])
            for i, offset in enumerate(range(0, len(bundle), 1024 * 1024))
        ]

        def send_piece(piece):
            index, payload = piece
            self.sandbox.files.write(
                f"/root/qwen.part{index:04d}", payload, user="root", request_timeout=90
            )

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(send_piece, pieces))
        self._run_root("cat /root/qwen.part* > /root/qwen.tgz; rm /root/qwen.part*")
        actual = self._run_root("sha256sum /root/qwen.tgz").stdout.split()[0]
        if actual != hashlib.sha256(bundle).hexdigest():
            raise RuntimeError("Tencent runtime upload digest mismatch")
        self._run_root(
            "tar -xzf /root/qwen.tgz --strip-components=1 -C /opt/qwen-code; "
            "ln -s /opt/qwen-code/cli-entry.js /usr/local/bin/qwen; "
            "chmod -R a+rX /opt/qwen-code; chmod +x /opt/qwen-code/cli-entry.js; "
            "rm /root/qwen.tgz"
        )
        for source, target in (
            (self.environment_dir / "color_tool.py", "/app/color_tool.py"),
            (self.environment_dir.parent / "input.json", "/app/input.json"),
        ):
            self.sandbox.files.write(target, source.read_bytes(), user="root")
        self.sandbox.files.write(
            "/run/aisle-verifier/token", self.seal_token_path.read_text(), user="root"
        )
        self._run_root("chmod 600 /run/aisle-verifier/token")
        self.sandbox.files.write(f"{BRIDGE_DIR}/relay.py", RELAY_SOURCE, user="root")
        self.sandbox.commands.run(
            f"unshare --net /usr/local/bin/python {BRIDGE_DIR}/relay.py",
            user="root",
            background=True,
            timeout=0,
        )
        for _ in range(50):
            try:
                self.namespace_pid = int(self.sandbox.files.read(f"{BRIDGE_DIR}/pid", user="root"))
                break
            except Exception:  # noqa: BLE001 - SDK provider boundary; do not log credentials
                time.sleep(0.1)
        if not self.namespace_pid:
            raise RuntimeError("Tencent template cannot create the isolated relay namespace")
        self._relay_thread = threading.Thread(target=self._relay_loop, daemon=True)
        self._relay_thread.start()
        result = self._exec_sync("qwen --version", user="agent", timeout_sec=30)
        if result.return_code or QWEN_VERSION not in (result.stdout or ""):
            raise RuntimeError("Pinned Qwen Code bundle failed its Tencent startup check")
        isolation = self._run_root(f"nsenter -t {self.namespace_pid} -n cat /proc/net/dev").stdout
        if "eth" in isolation:
            raise RuntimeError("Agent namespace unexpectedly has an external interface")
        protected = self._exec_sync(
            "test ! -r /root/aisle-rpc/relay.py && test ! -r /run/aisle-verifier/token "
            "&& test ! -w /tests "
            "&& test ! -w /logs && test ! -w /logs/verifier "
            "&& test ! -e /app/lightgbm_lab_model.joblib && id -u",
            user="agent",
        )
        if protected.return_code or protected.stdout.strip() == "0":
            raise RuntimeError("Tencent agent filesystem/user isolation probe failed")
        (self.private_dir / "runtime.json").write_text(
            json.dumps(
                {
                    "qwen_code_version": QWEN_VERSION,
                    "agent_network_namespace": "loopback-only",
                    "network_interfaces": isolation.strip(),
                    "agent_uid": int(protected.stdout.strip()),
                    "protected_paths_probe_passed": True,
                    "qwen_version_stdout": result.stdout.strip(),
                },
                indent=2,
            )
        )

    def _relay_loop(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            while not self._closed.wait(0.15):
                try:
                    entries = self.sandbox.files.list(f"{BRIDGE_DIR}/requests", user="root")
                    for entry in entries:
                        if not entry.name.endswith(".json") or entry.name in self._request_ids:
                            continue
                        self._request_ids.add(entry.name)
                        payload = json.loads(self.sandbox.files.read(entry.path, user="root"))
                        pool.submit(self._relay_request, payload)
                except Exception:  # noqa: BLE001 - SDK provider boundary; do not log credentials
                    if not self._closed.is_set():
                        self.relay_metrics["relay_errors"] += 1

    def _forward_request(self, host, payload):
        body = base64.b64decode(payload["body"])
        headers = {"Content-Type": "application/json"}
        if host == "simulator":
            endpoint = self.simulator_url + payload["path"]
            self.relay_metrics["experiment_requests"] += 1
        else:
            model_payload = json.loads(body)
            if model_payload.get("model") != self.expected_model:
                raise PermissionError("The trial model is frozen")
            # Normalize the validated object so duplicate JSON keys cannot have
            # different meanings in our validator and the upstream parser.
            body = json.dumps(model_payload, ensure_ascii=False).encode()
            endpoint = self.connections.model_base + "/chat/completions"
            headers["Authorization"] = f"Bearer {self.connections.model_key}"
            self.relay_metrics["model_requests"] += 1
        request = Request(
            endpoint, data=body if body else None, headers=headers, method=payload["method"]
        )
        try:
            response = build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=240)
        except HTTPError as error:
            response = error
        with response:
            return {
                "status": response.status,
                "content_type": response.headers.get("Content-Type", "application/json"),
                "body": base64.b64encode(response.read()).decode(),
            }

    def _relay_request(self, payload):
        try:
            host = route_request(payload["path"], payload["method"], self.network_policy)
            # The grading boundary waits for any dispatched scientific request.
            with self._experiment_lock if host == "simulator" else contextlib.nullcontext():
                result = self._forward_request(host, payload)
        except Exception as error:  # noqa: BLE001 - redact errors at the RPC boundary
            self.relay_metrics["relay_errors"] += 1
            message = "route_denied" if isinstance(error, PermissionError) else "transport_failed"
            result = {
                "status": 403 if message == "route_denied" else 502,
                "body": base64.b64encode(json.dumps({"error": message}).encode()).decode(),
            }
        try:
            remote = f"{BRIDGE_DIR}/responses/{payload['id']}.json"
            self.sandbox.files.write(remote, json.dumps(result), user="root")
        except Exception:  # noqa: BLE001 - SDK errors must not expose connection details
            self.relay_metrics["relay_errors"] += 1

    def _stop_agent_for_verifier(self):
        # The task verifier subsequently authenticates /seal; the server's own
        # ledger lock decides the last accepted experiment across every provider.
        self._run_root("pkill -KILL -u agent || test $? -eq 1")
        self._run_root("! pgrep -u agent >/dev/null")
        self._agent_stopped = True
        (self.private_dir / "verification-boundary.json").write_text(
            json.dumps(
                {
                    "agent_processes_stopped": True,
                    "ledger_seal": "unmodified task verifier authenticates POST /seal",
                },
                indent=2,
            )
        )

    async def stop(self, delete=True):
        self._closed.set()
        if self._relay_thread:
            await asyncio.to_thread(self._relay_thread.join, 5)
        (self.private_dir / "relay-metrics.json").write_text(
            json.dumps(self.relay_metrics, indent=2)
        )
        if self.sandbox and delete:
            await asyncio.to_thread(self.sandbox.kill)
            self.sandbox = None
            self.cleanup_confirmed = True
        (self.private_dir / "cleanup.json").write_text(
            json.dumps({"sandbox_deleted": self.cleanup_confirmed})
        )

    def _exec_sync(self, command, cwd=None, env=None, timeout_sec=None, user=None):
        user = str(user or "root")
        if user not in {"agent", "root"}:
            raise ValueError("Tencent task provider supports agent and root users only")
        home = "/home/agent" if user == "agent" else "/root"
        command = (
            f"nsenter -t {self.namespace_pid} -n -- setpriv --reuid={user} --regid={user} "
            f"--init-groups --no-new-privs env HOME={home} USER={user} "
            f"bash -c {shlex.quote(command)}"
        )
        try:
            result = self.sandbox.commands.run(
                command,
                cwd=cwd or "/workspace",
                envs=env,
                user="root",
                timeout=timeout_sec if timeout_sec is not None else 0,
            )
            return ExecResult(
                stdout=result.stdout, stderr=result.stderr, return_code=result.exit_code
            )
        except CommandExitException as error:
            return ExecResult(stdout=error.stdout, stderr=error.stderr, return_code=error.exit_code)

    async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
        effective_user = self._resolve_user(user)
        if (
            str(effective_user or "root") == "root"
            and "/tests/test.sh" in command
            and not self._agent_stopped
        ):
            await asyncio.to_thread(self._stop_agent_for_verifier)
        merged = self._merge_env(env) or {}
        merged.setdefault("COLOR_SIM_URL", "http://simulator:8000")
        merged.setdefault("NO_PROXY", "localhost,127.0.0.1,simulator")
        return await asyncio.to_thread(
            self._exec_sync, command, cwd, merged, timeout_sec, self._resolve_user(user)
        )

    async def upload_file(self, source_path, target_path):
        await asyncio.to_thread(
            self.sandbox.files.write, target_path, Path(source_path).read_bytes(), user="root"
        )

    async def download_file(self, source_path, target_path):
        payload = await asyncio.to_thread(
            self.sandbox.files.read, source_path, format="bytes", user="root"
        )
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    async def upload_dir(self, source_dir, target_dir):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            archive.add(source_dir, arcname=".")
        await asyncio.to_thread(
            self.sandbox.files.write, "/root/upload.tgz", buffer.getvalue(), user="root"
        )
        await asyncio.to_thread(
            self._run_root,
            f"mkdir -p {shlex.quote(target_dir)}; tar -xzf /root/upload.tgz -C {shlex.quote(target_dir)}; rm /root/upload.tgz",
        )

    async def download_dir(self, source_dir, target_dir):
        await asyncio.to_thread(
            self._run_root,
            f"tar -czf /root/download.tgz -C {shlex.quote(source_dir)} .",
        )
        payload = await asyncio.to_thread(
            self.sandbox.files.read, "/root/download.tgz", format="bytes", user="root"
        )
        destination = Path(target_dir)
        destination.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            archive.extractall(destination, filter=transfer_tar_filter)


class PreinstalledQwenCode(QwenCode):
    """Only offline installation differs; run and trajectory are Harbor's own."""

    async def install(self, environment):
        # Harbor prepares output directories after environment.start(), possibly
        # with permissive modes. Restore trust boundaries before the harness runs.
        protected = await environment.exec(
            "install -d -o root -g root -m 0755 /tests /logs; "
            "install -d -o root -g root -m 0700 /logs/verifier",
            user="root",
        )
        if protected.return_code:
            raise RuntimeError("Unable to protect verifier paths")
        probe = await self.exec_as_agent(
            environment,
            command="test ! -w /tests && test ! -w /logs && test ! -w /logs/verifier && id -u",
        )
        if probe.return_code or probe.stdout.strip() == "0":
            raise RuntimeError("Agent can modify verifier paths")
        (environment.private_dir / "execution-permissions.json").write_text(
            json.dumps(
                {
                    "agent_uid": int(probe.stdout.strip()),
                    "verifier_paths_not_agent_writable": True,
                    "probe_phase": "agent setup, after Harbor log directory preparation",
                },
                indent=2,
            )
        )
        result = await self.exec_as_agent(environment, command="qwen --version")
        if result.return_code or QWEN_VERSION not in (result.stdout or ""):
            raise RuntimeError("Tencent provider did not install the pinned official Qwen Code")
