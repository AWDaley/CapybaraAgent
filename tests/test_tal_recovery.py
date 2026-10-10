from tal.execution import ExecutionErrorCode, ToolResult
from tal.recovery import RecoveryCategory, diagnose_tool_result, diagnose_verification_messages


def test_syntax_tool_failure_generates_minimal_recovery_delta():
    result = ToolResult.failure(
        ExecutionErrorCode.PREFLIGHT_SYNTAX_ERROR,
        "Python syntax error at line 3",
    )

    diagnostic = diagnose_tool_result(result)

    assert diagnostic.category == RecoveryCategory.SYNTAX
    assert "line" in diagnostic.actual
    assert "syntax" in diagnostic.next_action.lower()


def test_verification_messages_become_expected_actual_delta():
    diagnostic = diagnose_verification_messages(["REPL assertion failed: 'value == 42' evaluated to False (41)."])

    assert diagnostic.category == RecoveryCategory.VERIFICATION
    assert "acceptance" in diagnostic.expected
    assert "41" in diagnostic.actual
