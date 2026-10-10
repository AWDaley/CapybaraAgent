from guardrails import get_safety_tier, request_confirmation


def test_get_safety_tier():
    assert get_safety_tier("calc") == "safe"
    assert get_safety_tier("write_file") == "safe"
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
