"""Fail-closed OS execution boundary for model-driven tools.

Untrusted code must NEVER be interpreted inside the Capybara server process.
A pinned container image, a Docker/Podman executable, and a local workspace are
required for the supported stateless command runner. A persistent, isolated
Python REPL is not implemented: it is deliberately absent from safe mode.
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
from dataclasses import dataclass
from pathlib import Path

from tal.effect_classes import EffectClass, get_effect_class
from tal.safe_paths import resolve_workspace_path, validate_relative_workspace_path

_PINNED_IMAGE = re.compile(r"^[a-zA-Z0-9_./:-]+@sha256:[0-9a-f]{64}$")
_ALLOWED_COMMANDS = {"python", "python3", "ls", "cat"}


@dataclass(frozen=True)
class ExecutionPolicy:
    """Explicitly bounded sandbox resources and environment."""

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


class IsolatedToolExecutor:
    """Disposable container runner; no host interpreter or shell fallback."""

    def __init__(self, policy: ExecutionPolicy | None = None):
        self.policy = policy or ExecutionPolicy.from_environment()

    def run_command(self, args: str) -> str:
        if not self.policy.ready():
            return ("Error [policy_denied]: Container isolation unavailable. "
                    "Configure a Docker/Podman runtime and a digest-pinned sandbox image.")
        try:
            data = json.loads(args)
            command = data.get("command", "")
            if not isinstance(command, str) or not command.strip():
                return "Error [invalid_arguments]: Missing command"
            if any(char in command for char in "&|;$`><\n\r"):
                return "Error [policy_denied]: Shell metacharacters are not permitted"
            tokens = shlex.split(command)
            if not tokens or tokens[0] not in _ALLOWED_COMMANDS:
                return "Error [policy_denied]: Command not permitted in the isolated executor"
            if tokens[0] in {"python", "python3"} and (
                len(tokens) < 2 or tokens[1].startswith("-")
            ):
                return "Error [policy_denied]: Only explicit workspace Python scripts may run"
            for token in tokens[1:]:
                validate_relative_workspace_path(token)
            import tools.file_tools

            workspace = os.path.realpath(tools.file_tools.WORKSPACE_DIR)
            os.makedirs(workspace, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="capybara-sandbox-") as stage:
                command_args = list(tokens)
                mounts = ["--mount", f"type=bind,src={workspace},dst=/workspace"]
                if tokens[0] in {"python", "python3"}:
                    script = resolve_workspace_path(workspace, tokens[1])
                    if not os.path.isfile(script):
                        return "Error [invalid_arguments]: Workspace script does not exist"
                    # Snapshot approved bytes outside the writable workspace.
                    approved = Path(stage) / "approved.py"
                    approved.write_bytes(Path(script).read_bytes())
                    mounts += ["--mount", f"type=bind,src={approved},dst=/approved.py,readonly"]
                    command_args = ["python", "-I", "-B", "/approved.py", *tokens[2:]]
                cidfile = os.path.join(stage, "container.id")
                docker_args = [
                    self.policy.runtime, "run", "--rm", "--cidfile", cidfile,
                    "--network", "none", "--read-only",
                    "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                    "--pids-limit", str(self.policy.max_pids),
                    "--memory", f"{self.policy.max_memory_mb}m",
                    "--cpus", "0.5",
                    "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=64m",
                    "--workdir", "/workspace",
                    *mounts, self.policy.image, *command_args,
                ]
                # No shell expansion. A killed client also forces removal of the
                # container by ID; terminating only docker.exe is insufficient.
                proc = subprocess.Popen(
                    docker_args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True,
                )
                try:
                    stdout, stderr = proc.communicate(timeout=self.policy.max_seconds)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate()
                    self._force_remove(cidfile)
                    return "Error [tool_timeout]: Container terminated after execution deadline"
                if proc.returncode:
                    return f"Error [tool_execution_error]: {(stderr or stdout)[:2000]}"
                return (stdout or "Command completed (no output).")[:2000]
        except (json.JSONDecodeError, TypeError, ValueError, OSError) as exc:
            return f"Error [invalid_arguments]: {exc}"

    def _force_remove(self, cidfile: str) -> None:
        try:
            with open(cidfile, encoding="utf-8") as handle:
                cid = handle.read().strip()
            if cid and re.fullmatch(r"[0-9a-f]{12,64}", cid):
                subprocess.run([self.policy.runtime, "rm", "-f", cid],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired):
            # Timeout errors remain failures. The container runtime should also
            # enforce an external lease/lifetime in deployed environments.
            pass


def govern_agent_tools(registry: dict) -> dict:
    """Drop unsafe execution tools rather than falling back to host execution."""
    tools = dict(registry)
    if os.environ.get("CAPYBARA_UNSAFE_LOCAL_EXEC") == "1":
        return tools  # Explicit, local-only developer experimentation.
    runner = IsolatedToolExecutor()
    for name in list(tools):
        if get_effect_class(name) != EffectClass.EXEC:
            continue
        if name == "run_command" and runner.policy.ready():
            tools[name] = runner.run_command
        else:
            # In particular python_repl cannot share in-process globals with an
            # untrusted model. It needs a dedicated stateful isolated worker.
            tools.pop(name)
    return tools
