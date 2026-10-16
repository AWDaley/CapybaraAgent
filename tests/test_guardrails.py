from guardrails import get_safety_tier, request_confirmation


def test_get_safety_tier():
    assert get_safety_tier("calc") == "safe"
    assert get_safety_tier("write_file") == "dangerous"
    assert get_safety_tier("web_search") == "moderate"
    assert get_safety_tier("run_command") == "dangerous"
    assert get_safety_tier("python_repl") == "dangerous"
    # Unknown tools default to dangerous
    assert get_safety_tier("unknown_tool_123") == "dangerous"

def test_request_confirmation_callback_approve():
    def mock_approval(tool, args):
        return True
    
    result = request_confirmation("run_command", "ls", approval_callback=mock_approval)
    assert result == True

def test_request_confirmation_callback_reject():
    def mock_approval(tool, args):
        return False
        
    result = request_confirmation("run_command", "rm -rf /", approval_callback=mock_approval)
    assert result == False


def test_tal_guardrails_flag_cannot_skip_write_approval():
    from agent import BasicAgent
    from tal.context_packer import ExecutionPhase
    from tal.execution import ExecutionErrorCode

    called = []
    agent = BasicAgent(
        tal_mode=True, guardrails_enabled=False,
        tool_registry={"write_file": lambda args: called.append(args) or "written"},
    )
    agent.current_phase = ExecutionPhase.EXECUTION
    result = agent.act_result(
        "write_file", '{"path":"unsafe.txt","content":"x"}',
        approval_callback=lambda *_: False,
    )
    assert result.error_code == ExecutionErrorCode.APPROVAL_DENIED.value
    assert called == []


def test_one_use_action_approval_is_bound_to_exact_arguments():
    import pytest
    from tal.authorization import AuthorizationDenied, ToolAuthorizationService

    svc = ToolAuthorizationService()
    fields = dict(task_id="task", manifest_hash="hash", session_id="session",
                  tool_name="write_file", phase="execution")
    action = svc.issue(**fields, arguments='{"path":"a.txt","content":"x"}',
                       requires_approval=True, approval_granted=True)
    with pytest.raises(AuthorizationDenied):
        svc.consume(action, **fields, arguments='{"path":"b.txt","content":"x"}')
    with pytest.raises(AuthorizationDenied):
        svc.consume(action, **fields, arguments='{"path":"a.txt","content":"x"}')
    good = svc.issue(**fields, arguments='{"path":"a.txt","content":"x"}',
                     requires_approval=True, approval_granted=True)
    svc.consume(good, **fields, arguments='{"content":"x","path":"a.txt"}')
    with pytest.raises(AuthorizationDenied):
        svc.consume(good, **fields, arguments='{"path":"a.txt","content":"x"}')
