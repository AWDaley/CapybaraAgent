from tal.capability import compute_envelope
from tal.context_packer import ContextPacker, ExecutionPhase
from tal.epistemic import EpistemicState, EpistemicStore
from tal.slm_profile import build_slm_system_prompt


def test_phase_tool_filtering():
    packer = ContextPacker()
    tools = {
        "calc": lambda: None,
        "read_file": lambda: None,
        "write_file": lambda: None,
        "run_command": lambda: None,
        "web_search": lambda: None,
    }
    
    disc_tools = packer.filter_tools_for_phase(ExecutionPhase.DISCOVERY, tools)
    assert "web_search" in disc_tools
    assert "read_file" in disc_tools
    assert "write_file" not in disc_tools

    exec_tools = packer.filter_tools_for_phase(ExecutionPhase.EXECUTION, tools)
    assert len(exec_tools) == 5

    verif_tools = packer.filter_tools_for_phase(ExecutionPhase.VERIFICATION, tools)
    assert "run_command" in verif_tools
    assert "read_file" in verif_tools
    assert "web_search" not in verif_tools


def test_capability_envelope_denial():
    avail = {"calc": 1, "write_file": 2, "run_command": 3}
    envelope = compute_envelope(
        requested_tools=["calc", "write_file", "run_command", "drop_db"],
        available_tools=avail,
        policy_denials={"run_command": "Air-gapped mode"}
    )
    
    assert envelope.is_permitted("calc") is True
    assert envelope.is_permitted("write_file") is True
    assert envelope.is_permitted("run_command") is False
    assert envelope.is_permitted("drop_db") is False
    assert len(envelope.denied) == 2


def test_context_packer_pack_messages():
    packer = ContextPacker()
    store = EpistemicStore()
    store.add_fact("data.json exists", EpistemicState.OBSERVED, "tool:list_files")
    
    tools = {"read_file": 1, "write_file": 2}
    envelope = compute_envelope(requested_tools=list(tools.keys()), available_tools=tools)
    
    messages = packer.pack(
        phase=ExecutionPhase.EXECUTION,
        goal="Parse data.json and summarize",
        epistemic_store=store,
        tool_registry=tools,
        capabilities=envelope,
        active_step="Step 1: Read data.json"
    )
    
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "Phase: EXECUTION" in messages[0]["content"]
    assert "data.json exists" in messages[1]["content"]
    assert "data.json exists" not in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "Overall Goal: Parse data.json and summarize" in messages[1]["content"]


def test_context_packer_keeps_repository_index_as_untrusted_locator_data():
    messages = ContextPacker().pack(
        phase=ExecutionPhase.PLANNING,
        goal="Update the runner",
        epistemic_store=EpistemicStore(),
        tool_registry={},
        repository_context="- class StructuredPipelineRunner at tal/pipeline_runner.py:81",
    )
    assert "<repository-index>" in messages[1]["content"]
    assert "untrusted locator data" in messages[1]["content"]


def test_context_packer_does_not_duplicate_goal_when_it_is_the_active_step():
    goal = "Create the deterministic service graph."
    messages = ContextPacker().pack(
        phase=ExecutionPhase.EXECUTION,
        goal=goal,
        active_step=goal,
        epistemic_store=EpistemicStore(),
        tool_registry={},
    )

    assert messages[1]["content"].count(goal) == 1


def test_slm_prompt_profile_generation():
    envelope = compute_envelope(["calc", "time"], {"calc": 1, "time": 1})
    prompt = build_slm_system_prompt(["calc", "time"], envelope)
    assert "strict JSON format" in prompt
    assert "Authorized Tools: [calc, time]" in prompt
    assert "do not import or use os" in prompt
