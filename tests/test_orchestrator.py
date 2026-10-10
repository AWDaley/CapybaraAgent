from agents.orchestrator import OrchestratorAgent


def test_delegate_parsing(mock_llm):
    mock_llm.responses = [
        "1. DELEGATE: researcher: Find the weather in Tokyo\n"
        "DELEGATE: coder: Write a Python script"
    ]
    orchestrator = OrchestratorAgent(llm_client=mock_llm, verbose=False)
    delegations = orchestrator.delegate("Do something")
    
    assert len(delegations) == 2
    assert delegations[0] == ("researcher", "Find the weather in Tokyo")
    assert delegations[1] == ("coder", "Write a Python script")

def test_delegate_fallback(mock_llm):
    mock_llm.responses = ["I will just do it myself without delegating properly."]
    orchestrator = OrchestratorAgent(llm_client=mock_llm, verbose=False)
    delegations = orchestrator.delegate("Do something")
    
    assert len(delegations) == 0
