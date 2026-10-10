"""Typed execution results shared by the agent, tools, and event log."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ExecutionErrorCode(str, Enum):
    INVALID_ARGUMENTS = "invalid_arguments"
    PREFLIGHT_SYNTAX_ERROR = "preflight_syntax_error"
    POLICY_DENIED = "policy_denied"
    APPROVAL_DENIED = "approval_denied"
    TOOL_NOT_FOUND = "tool_not_found"
    DEADLINE_EXHAUSTED = "deadline_exhausted"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_EXECUTION_ERROR = "tool_execution_error"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ToolResult:
    """A stable result contract without breaking legacy string observations."""

    ok: bool
    error_code: str | None = None
    stdout: str = ""
    stderr: str = ""
    message: str = ""
    duration_seconds: float = 0.0
    artifacts: tuple[str, ...] = ()
    retry_safe: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(
        cls,
        stdout: str = "",
        duration_seconds: float = 0.0,
        artifacts: tuple[str, ...] = (),
        metadata: dict[str, Any] | None = None,
    ) -> "ToolResult":
        return cls(
            ok=True,
            stdout=stdout,
            duration_seconds=round(max(0.0, duration_seconds), 4),
            artifacts=artifacts,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def failure(
        cls,
        error_code: ExecutionErrorCode | str,
        message: str,
        stdout: str = "",
        stderr: str = "",
        duration_seconds: float = 0.0,
        retry_safe: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> "ToolResult":
        return cls(
            ok=False,
            error_code=str(error_code.value if isinstance(error_code, ExecutionErrorCode) else error_code),
            stdout=stdout,
            stderr=stderr,
            message=message,
            duration_seconds=round(max(0.0, duration_seconds), 4),
            retry_safe=retry_safe,
            metadata=dict(metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["artifacts"] = list(self.artifacts)
        return data

    def to_observation(self) -> str:
        """Return the legacy string consumed by existing prompts and UI code."""
        if self.ok:
            return self.stdout or "Tool executed successfully (no output)."
        if self.stdout.startswith("Error"):
            return self.stdout
        prefix = f"Error [{self.error_code}]:" if self.error_code else "Error:"
        detail = self.message or self.stderr or "Tool execution failed."
        return f"{prefix} {detail}"


def classify_legacy_tool_output(output: str) -> ExecutionErrorCode | None:
    """Classify existing tool strings while tools migrate to ToolResult."""
    text = str(output or "").strip().lower()
    if not text.startswith("error") and "traceback (most recent call last)" not in text and "stderr:" not in text:
        return None
    if "syntaxerror" in text or "syntax error" in text:
        return ExecutionErrorCode.PREFLIGHT_SYNTAX_ERROR
    if "timed out" in text or "resource limit" in text:
        return ExecutionErrorCode.TOOL_TIMEOUT
    if "deadline exhausted" in text:
        return ExecutionErrorCode.DEADLINE_EXHAUSTED
    if "denied" in text or "not permitted" in text:
        return ExecutionErrorCode.POLICY_DENIED
    if "not found" in text:
        return ExecutionErrorCode.TOOL_NOT_FOUND
    return ExecutionErrorCode.TOOL_EXECUTION_ERROR
