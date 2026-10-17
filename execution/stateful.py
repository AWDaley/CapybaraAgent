"""A model-driven, stateful Python REPL backed EXCLUSIVELY by a bounded OS container.

Never run execution/sandbox_worker.py with the host interpreter for model
input. This module owns a single disposable runtime process and terminates
the entire named container on missing responses, protocol errors, timeouts,
or run shutdown. No Docker socket, home directory or host network is mounted.
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any

from execution.isolated import ExecutionPolicy

_MAX_FRAME = 256 * 1024
_MAX_CODE = 60 * 1024
_MAX_STDERR = 2048
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z_0-9]{0,127}$")


class StatefulSandboxError(RuntimeError):
    """Unavailable or failed container/protocol boundary."""


def _reply_reader(pipe, pending: queue.Queue) -> None:
    try:
        while True:
            raw = pipe.readline(_MAX_FRAME + 1)
            if not raw:
                pending.put(None)
                return
            if len(raw) > _MAX_FRAME or not raw.endswith(b"\n"):
                pending.put(StatefulSandboxError("WORKER_FRAME_INVALID"))
                return
            pending.put(raw)
    except OSError:
        pending.put(None)


def _stderr_reader(pipe, output: bytearray) -> None:
    try:
        while True:
            data = pipe.read(8192)
            if not data:
                return
            remaining = _MAX_STDERR - len(output)
            if remaining > 0:
                output.extend(data[:remaining])
    except OSError:
        pass


class StatefulSandbox:
    """One task-scoped, digest-pinned Docker/Podman worker with stateful REPL."""

    def __init__(
        self, workspace_dir: str, policy: ExecutionPolicy | None = None,
        response_timeout_seconds: float = 15.0,
    ):
        self.policy = policy or ExecutionPolicy.from_environment()
        self.workspace_dir = os.path.realpath(os.fspath(workspace_dir))
        self.timeout = min(max(float(response_timeout_seconds), 0.1), 30.0)
        self.container_name = "capybara-worker-" + uuid.uuid4().hex
        self._lock = threading.RLock()
        self._process: subprocess.Popen | None = None
        self._requests: queue.Queue = queue.Queue(maxsize=8)
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr = bytearray()
        self._seq = 0
        self._closed = False
        self._dead = False
        self._worker_path = Path(__file__).with_name("sandbox_worker.py").resolve()

    @property
    def ready(self) -> bool:
        return (
            not self._dead and not self._closed
            and self.policy.ready()
            and os.path.isdir(self.workspace_dir)
            and self._worker_path.is_file()
        )

    def _command(self) -> list[str]:
        if not self.ready:
            raise StatefulSandboxError("ISOLATION_UNAVAILABLE")
        if self.policy.max_seconds <= 0 or self.policy.max_memory_mb < 128 or self.policy.max_pids < 2:
            raise StatefulSandboxError("ISOLATION_BUDGET_INVALID")
        # Unprivileged UID/GID where POSIX permits owner access to the temp
        # workspace; Windows Docker uses a dedicated unprivileged UID.
        identity = f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else "65534:65534"
        return [
            self.policy.runtime, "run", "--rm", "--interactive", "--name", self.container_name,
            "--network", "none", "--read-only", "--user", identity,
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", str(self.policy.max_pids),
            "--memory", f"{self.policy.max_memory_mb}m", "--cpus", "0.5",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m",
            "--workdir", "/workspace",
            "--mount", f"type=bind,src={self.workspace_dir},dst=/workspace",
            "--mount", f"type=bind,src={self._worker_path},dst=/worker.py,readonly",
            self.policy.image, "python", "-I", "-B", "-u", "/worker.py",
        ]

    def _start(self) -> None:
        if self._process is not None:
            return
        proc = subprocess.Popen(
            self._command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0,
        )
        self._process = proc
        self._stdout_thread = threading.Thread(
            target=_reply_reader, args=(proc.stdout, self._requests),
            daemon=True, name="capybara-worker-stdout",
        )
        self._stderr_thread = threading.Thread(
            target=_stderr_reader, args=(proc.stderr, self._stderr),
            daemon=True, name="capybara-worker-stderr",
        )
        self._stdout_thread.start()
        self._stderr_thread.start()
        try:
            hello = self._next_reply()
            if hello.get("id") != 0 or hello.get("ok") is not True or hello.get("output") != "ready":
                raise StatefulSandboxError("WORKER_HANDSHAKE_INVALID")
        except (OSError, ValueError, StatefulSandboxError):
            self._terminate()
            raise

    def _next_reply(self) -> dict:
        try:
            frame = self._requests.get(timeout=self.timeout)
        except queue.Empty as exc:
            self._terminate()
            raise StatefulSandboxError("WORKER_TIMEOUT") from exc
        if isinstance(frame, Exception):
            self._terminate()
            raise StatefulSandboxError("WORKER_PROTOCOL_INVALID") from frame
        if frame is None:
            self._terminate()
            raise StatefulSandboxError("WORKER_EXITED")
        try:
            result = json.loads(frame)
            if not isinstance(result, dict):
                raise ValueError("Worker reply must be JSON object")
            return result
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._terminate()
            raise StatefulSandboxError("WORKER_PROTOCOL_INVALID") from exc

    def _exchange(self, operation: str, **fields: Any) -> dict:
        with self._lock:
            if self._closed or self._dead:
                raise StatefulSandboxError("WORKER_UNAVAILABLE")
            try:
                self._start()
                self._seq += 1
                message = json.dumps(
                    {"id": self._seq, "op": operation, **fields},
                    separators=(",", ":"), allow_nan=False,
                ).encode("utf-8") + b"\n"
                if len(message) > 65_536:
                    raise ValueError("WORKER_REQUEST_TOO_LARGE")
                if not self._process or not self._process.stdin:
                    raise StatefulSandboxError("WORKER_UNAVAILABLE")
                self._process.stdin.write(message)
                self._process.stdin.flush()
                reply = self._next_reply()
                if reply.get("id") != self._seq or type(reply.get("ok")) is not bool:
                    raise StatefulSandboxError("WORKER_REPLY_MISMATCH")
                return reply
            except (OSError, TypeError, ValueError, StatefulSandboxError):
                self._terminate()
                raise

    def execute_tool(self, args: str) -> str:
        """ToolResult-compatible string. Never executes the code on host."""
        try:
            data = json.loads(args)
            code = data.get("code") if isinstance(data, dict) else None
            if not isinstance(code, str) or not 0 < len(code.encode("utf-8")) <= _MAX_CODE:
                raise ValueError("WORKER_CODE_INVALID")
            result = self._exchange("exec", code=code)
            if not result["ok"]:
                return "Error: " + str(result.get("output") or result.get("error"))[:500]
            return str(result.get("output", ""))[:2048]
        except (OSError, TypeError, ValueError, StatefulSandboxError) as exc:
            return "Error: isolated worker unavailable or invalid: " + str(exc)[:150]

    def snapshot(self, names: tuple[str, ...] | list[str]) -> dict:
        if len(names) > 96 or any(not isinstance(n, str) or not _IDENTIFIER.fullmatch(n) for n in names):
            raise StatefulSandboxError("WORKER_SNAPSHOT_KEYS_INVALID")
        reply = self._exchange("snapshot", names=list(names))
        if not reply["ok"] or not isinstance(reply.get("state"), dict):
            raise StatefulSandboxError("WORKER_SNAPSHOT_INVALID")
        return reply["state"]

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._terminate()

    def _terminate(self) -> None:
        self._dead = True
        if self._process is not None:
            try:
                self._process.kill()
            except OSError:
                pass
        # Remove by randomly generated name even when the runtime never wrote
        # its CID file; all stop paths must attempt to kill the container.
        if self.policy.runtime in {"docker", "podman"}:
            try:
                subprocess.run(
                    [self.policy.runtime, "rm", "-f", self.container_name],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=5, check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        if self._process is not None:
            try:
                self._process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def __enter__(self):
        if not self.ready:
            raise StatefulSandboxError("ISOLATION_UNAVAILABLE")
        self._start()
        return self

    def __exit__(self, *_):
        self.close()
