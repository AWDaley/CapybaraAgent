"""Fail-closed OS execution boundary for model-driven tools.

Supported: isolated, stateless, digest-pinned Docker/Podman command execution.
Unsupported in safe mode: in-process or persistent untrusted Python REPL.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from tal.effect_classes import EffectClass, get_effect_class
from tal.safe_paths import resolve_workspace_path, validate_relative_workspace_path

_PINNED_IMAGE = re.compile(r"^[a-zA-Z0-9_./:-]+@sha256:[0-9a-f]{64}$")
_ALLOWED_COMMANDS = {"python", "python3", "ls", "cat"}
_MAX_SCRIPT_BYTES = 1024 * 1024
_MAX_OUTPUT_BYTES = 4096


@dataclass(frozen=True)
class ExecutionPolicy:
    runtime: str = ""
    image: str = ""
    max_seconds: int = 15
    max_memory_mb: int = 256
    max_pids: int = 32

    @classmethod
    def from_environment(cls) -> "ExecutionPolicy":
        return cls(
            runtime=os.environ.get("CAPYBARA_CONTAINER_RUNTIME", "").strip(),
            image=os.environ.get("CAPYBARA_SANDBOX_IMAGE", "").strip(),
        )

    def ready(self) -> bool:
        return (
            self.runtime in {"docker", "podman"}
            and bool(_PINNED_IMAGE.fullmatch(self.image))
            and shutil.which(self.runtime) is not None
        )


@dataclass(frozen=True)
class PreparedCommand:
    """The exact executable bytes approved by the user, before any effects."""

    command_args: tuple[str, ...]
    workspace_dir: str
    script_bytes: bytes | None = None
    script_sha256: str | None = None


def _drain_bounded(pipe, output: bytearray) -> None:
    """Drain even hostile unlimited output without consuming unbounded RAM."""
    try:
        while True:
            chunk = pipe.read(8192)
            if not chunk:
                break
            remaining = _MAX_OUTPUT_BYTES - len(output)
            if remaining > 0:
                output.extend(chunk[:remaining])
    finally:
        pipe.close()


class IsolatedToolExecutor:
    """Disposable container runner; never fall back to the host interpreter."""

    def __init__(self, policy: ExecutionPolicy | None = None):
        self.policy = policy or ExecutionPolicy.from_environment()

    def prepare_command(self, args: str) -> PreparedCommand:
        """Validate and freeze the script bytes *before* asking for approval."""
        data = json.loads(args)
        if not isinstance(data, dict):
            raise ValueError("Command arguments must be a JSON object")
        command = data.get("command", "")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("A nonempty command is required")
        if any(char in command for char in "&|;$`><\n\r"):
            raise ValueError("Shell operators are not permitted")
        tokens = shlex.split(command)
        if not tokens or tokens[0] not in _ALLOWED_COMMANDS:
            raise ValueError("Command is not in the isolated executor allowlist")
        for token in tokens[1:]:
            validate_relative_workspace_path(token)
        import tools.file_tools

        workspace = os.path.realpath(tools.file_tools.WORKSPACE_DIR)
        if tokens[0] in {"python", "python3"}:
            if len(tokens) < 2 or tokens[1].startswith("-"):
                raise ValueError("Only explicit workspace Python script files may run")
            script = Path(resolve_workspace_path(workspace, tokens[1]))
            if not script.is_file() or script.stat().st_size > _MAX_SCRIPT_BYTES:
                raise ValueError("Script is unavailable or exceeds the 1 MiB limit")
            content = script.read_bytes()
            if len(content) > _MAX_SCRIPT_BYTES:
                raise ValueError("Script exceeds the 1 MiB limit")
            return PreparedCommand(
                command_args=("python", "-I", "-B", "/approved.py", *tokens[2:]),
                workspace_dir=workspace, script_bytes=content,
                script_sha256=hashlib.sha256(content).hexdigest(),
            )
        return PreparedCommand(command_args=tuple(tokens), workspace_dir=workspace)

    def run_command(self, args: str) -> str:
        if not self.policy.ready():
            return ("Error [policy_denied]: Container isolation unavailable. "
                    "Configure Docker/Podman and a digest-pinned image.")
        try:
            return self.run_prepared(self.prepare_command(args))
        except (ValueError, OSError, TypeError, json.JSONDecodeError) as exc:
            return f"Error [invalid_arguments]: {exc}"

    def run_prepared(self, prepared: PreparedCommand) -> str:
        """Execute only the snapshotted bytes; workspace edits cannot change them."""
        if not self.policy.ready():
            return "Error [policy_denied]: Container isolation unavailable"
        try:
            with tempfile.TemporaryDirectory(prefix="capybara-sandbox-") as stage:
                mounts = ["--mount", f"type=bind,src={prepared.workspace_dir},dst=/workspace"]
                if prepared.script_bytes is not None:
                    approved = Path(stage) / "approved.py"
                    approved.write_bytes(prepared.script_bytes)
                    mounts += ["--mount", f"type=bind,src={approved},dst=/approved.py,readonly"]
                cidfile = os.path.join(stage, "container.id")
                user = f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else "65534:65534"
                command = [
                    self.policy.runtime, "run", "--rm", "--cidfile", cidfile,
                    "--network", "none", "--read-only", "--user", user,
                    "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                    "--pids-limit", str(self.policy.max_pids),
                    "--memory", f"{self.policy.max_memory_mb}m", "--cpus", "0.5",
                    "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=64m",
                    "--workdir", "/workspace",
                    *mounts, self.policy.image, *prepared.command_args,
                ]
                proc = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                out, err = bytearray(), bytearray()
                stdout_reader = threading.Thread(target=_drain_bounded, args=(proc.stdout, out), daemon=True)
                stderr_reader = threading.Thread(target=_drain_bounded, args=(proc.stderr, err), daemon=True)
                stdout_reader.start()
                stderr_reader.start()
                try:
                    proc.wait(timeout=self.policy.max_seconds)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    self._force_remove(cidfile)
                    proc.wait(timeout=5)
                    return "Error [tool_timeout]: Container force-terminated at deadline"
                finally:
                    stdout_reader.join(timeout=5)
                    stderr_reader.join(timeout=5)
                if proc.returncode:
                    return f"Error [tool_execution_error]: {(err or out).decode('utf-8', 'replace')[:2000]}"
                return out.decode("utf-8", "replace")[:2000] or "Command completed (no output)."
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"Error [tool_execution_error]: {exc}"

    def _force_remove(self, cidfile: str) -> None:
        try:
            cid = Path(cidfile).read_text(encoding="utf-8").strip()
            if re.fullmatch(r"[0-9a-f]{12,64}", cid):
                subprocess.run(
                    [self.policy.runtime, "rm", "-f", cid],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=5, check=False,
                )
        except (OSError, subprocess.TimeoutExpired):
            pass


def govern_agent_tools(registry: dict) -> dict:
    """No model-driven host execution unless explicitly opted into dev mode."""
    tools = dict(registry)
    if os.environ.get("CAPYBARA_UNSAFE_LOCAL_EXEC") == "1":
        return tools
    runner = IsolatedToolExecutor()
    for name in list(tools):
        if get_effect_class(name) != EffectClass.EXEC:
            continue
        if name == "run_command" and runner.policy.ready():
            tools[name] = runner.run_command
        elif name == "python_repl":
            # Only the exact bound method of a live, OS-backed sandbox may
            # survive tool governance. An arbitrary callable named
            # "python_repl" remains prohibited even with a valid image.
            from execution.stateful import StatefulSandbox

            tool = tools[name]
            owner = getattr(tool, "__self__", None)
            if not (
                isinstance(owner, StatefulSandbox)
                and getattr(tool, "__func__", None) is StatefulSandbox.execute_tool
                and owner.ready
            ):
                tools.pop(name)
        else:
            tools.pop(name)
    return tools
