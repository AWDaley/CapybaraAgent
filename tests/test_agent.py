from agent import BasicAgent


def dummy_tool(args): 
    return "4"

def desc(): 
    return '{"tool": "calc", "args": "..."}'

def test_direct_answer(mock_llm):
    mock_llm.responses = ['Thought: I know this.\nFinal Answer: Hello!']
    agent = BasicAgent(llm_client=mock_llm, verbose=False, structured_output=False)
    result = agent.run_turn("Say hello")
    assert result == "Hello!"

def test_tool_usage(mock_llm):
    registry = {"calc": dummy_tool}
    mock_llm.responses = [
        'Thought: I need to calculate.\nAction: {"tool": "calc", "args": "2+2"}',
        'Thought: I have the answer.\nFinal Answer: The answer is 4.'
    ]
    agent = BasicAgent(llm_client=mock_llm, tool_registry=registry, tool_descriptions_fn=desc, guardrails_enabled=False, verbose=False, structured_output=False)
    result = agent.run_turn("What is 2+2?")
    assert result == "The answer is 4."

def test_structured_output_mode(mock_llm):
    registry = {"calc": dummy_tool}
    mock_llm.responses = [
        '{"thought": "I need to calculate", "action": {"tool": "calc", "args": "2+2"}, "final_answer": null}',
        '{"thought": "I have the answer", "action": null, "final_answer": "The answer is 4."}'
    ]
    agent = BasicAgent(llm_client=mock_llm, tool_registry=registry, tool_descriptions_fn=desc, guardrails_enabled=False, verbose=False, structured_output=True)
    result = agent.run_turn("What is 2+2?")
    assert result == "The answer is 4."

def test_max_steps_limit(mock_llm):
    registry = {"calc": dummy_tool}
    # Provide endless tools without final answer
    mock_llm.responses = [
        '{"thought": "looping", "action": {"tool": "calc", "args": "2+2"}, "final_answer": null}'
    ] * 10
    agent = BasicAgent(llm_client=mock_llm, tool_registry=registry, tool_descriptions_fn=desc, guardrails_enabled=False, verbose=False, structured_output=True)
    result = agent.run_turn("loop", max_steps=3)
    assert "Error: Agent reached maximum steps" in result
