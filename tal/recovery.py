"""Structured failure diagnostics for small, actionable SLM repair turns."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum

from .execution import ExecutionErrorCode, ToolResult


class RecoveryCategory(str, Enum):
    SYNTAX = "syntax"
    SCHEMA = "schema"
    VERIFICATION = "verification"
    TIMEOUT = "timeout"
    POLICY = "policy"
    PROVIDER = "provider"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RecoveryDiagnostic:
    category: RecoveryCategory
    expected: str
    actual: str
    next_action: str
    retry_safe: bool = True

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_prompt(self) -> str:
        return (
            "### Recovery Delta\n"
            f"- Category: {self.category.value}\n"
            f"- Expected: {self.expected}\n"
            f"- Actual: {self.actual}\n"
            f"- Next action: {self.next_action}"
        )


def diagnose_tool_result(result: ToolResult) -> RecoveryDiagnostic:
    """Turn a typed tool result into the minimum corrective context."""
    code = result.error_code or ExecutionErrorCode.UNKNOWN.value
    actual = result.stderr or result.stdout or result.message or "Tool returned no diagnostic."
    if code == ExecutionErrorCode.PREFLIGHT_SYNTAX_ERROR.value:
        return RecoveryDiagnostic(RecoveryCategory.SYNTAX, "Valid Python syntax", actual, "Repair only the syntax near the reported line.")
    if code == ExecutionErrorCode.INVALID_ARGUMENTS.value:
        return RecoveryDiagnostic(RecoveryCategory.SCHEMA, "Schema-valid tool arguments", actual, "Change only the invalid fields and preserve the intended action.")
    if code in {ExecutionErrorCode.DEADLINE_EXHAUSTED.value, ExecutionErrorCode.TOOL_TIMEOUT.value, ExecutionErrorCode.PROVIDER_TIMEOUT.value}:
        return RecoveryDiagnostic(RecoveryCategory.TIMEOUT, "Completion within the remaining budget", actual, "Checkpoint valid state and split the next action into a smaller unit.", retry_safe=False)
    if code in {ExecutionErrorCode.POLICY_DENIED.value, ExecutionErrorCode.APPROVAL_DENIED.value}:
        return RecoveryDiagnostic(RecoveryCategory.POLICY, "A permitted approved action", actual, "Select a permitted read-only or approved alternative.", retry_safe=False)
    if code == ExecutionErrorCode.PROVIDER_UNAVAILABLE.value:
        return RecoveryDiagnostic(RecoveryCategory.PROVIDER, "A reachable model provider", actual, "Resume from the latest checkpoint after provider availability is restored.", retry_safe=False)
    return RecoveryDiagnostic(RecoveryCategory.UNKNOWN, "A successful tool result", actual, "Use a different repair strategy; do not repeat the same failing call.")


def diagnose_verification_messages(messages: list[str]) -> RecoveryDiagnostic:
    """Convert declarative verifier output into expected-versus-actual repair context."""
    actual = "\n".join(str(message) for message in messages if str(message).strip()) or "Verification returned no details."
    lowered = actual.lower()
    if "syntaxerror" in lowered or "syntax error" in lowered:
        return RecoveryDiagnostic(RecoveryCategory.SYNTAX, "A parseable artifact", actual, "Repair the reported syntax error and rerun the syntax gate.")
    if "json" in lowered or "required key" in lowered or "schema" in lowered:
        return RecoveryDiagnostic(RecoveryCategory.SCHEMA, "Artifact content that satisfies the declared schema", actual, "Update only the missing or invalid schema fields.")
    return RecoveryDiagnostic(RecoveryCategory.VERIFICATION, "All declared acceptance criteria", actual, "Change the smallest state or artifact needed to satisfy the failed criterion.")
