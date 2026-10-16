import os
import tempfile

from tal.manifest import TaskManifest
from tal.verification import (
    ExitCodeCheck,
    FileExistsCheck,
    NonEmptyOutputCheck,
    RegexMatchCheck,
    create_criterion_from_dict,
    run_verification,
)


def test_file_exists_verification():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "out.txt")
        with open(test_file, "w") as f:
            f.write("hello world")

        check = FileExistsCheck(path="out.txt", min_size_bytes=5)
        passed, msg = check.check(workspace_dir=tmpdir)
        assert passed is True
        assert "verified" in msg

        check_fail = FileExistsCheck(path="nonexistent.txt")
        passed_fail, _ = check_fail.check(workspace_dir=tmpdir)
        assert passed_fail is False


def test_exit_code_verification():
    check = ExitCodeCheck(command="echo test", expected_code=0)
    passed, message = check.check()
    assert passed is False
    assert "disabled" in message


def test_regex_match_verification():
    check = RegexMatchCheck(text="Total items: 42", pattern=r"Total items:\s*\d+")
    passed, _ = check.check()
    assert passed is True


def test_run_verification_composite():
    criteria = [
        {"type": "non_empty", "output": "valid answer"},
        {"type": "regex_match", "text": "result: 100", "pattern": r"\d+"}
    ]
    all_passed, messages = run_verification(criteria)
    assert all_passed is True
    assert len(messages) == 2


def test_canonical_json_and_manifest_hash():
    manifest = TaskManifest.compile(
        goal="Write a script to calculate fibonacci",
        available_tools={"write_file": 1, "run_command": 2},
        verification_criteria=[{"type": "file_exists", "path": "fib.py"}]
    )
    
    assert manifest.manifest_hash != ""
    assert len(manifest.manifest_hash) == 64  # SHA-256 hex string length
    
    # Hash is deterministic
    recalculated = manifest.compute_hash()
    assert recalculated == manifest.manifest_hash


def test_exit_code_verification_failure():
    check = ExitCodeCheck(command="python -c \"import sys; sys.exit(1)\"", expected_code=0)
    passed, msg = check.check()
    assert passed is False
    assert "disabled" in msg


def test_regex_match_verification_failure():
    check = RegexMatchCheck(text="No numbers here!", pattern=r"\d{4}-\d{2}-\d{2}")
    passed, msg = check.check()
    assert passed is False
    assert "did not match" in msg


def test_non_empty_output_check():
    # Passes: non-empty, non-error output
    check_pass = NonEmptyOutputCheck(output="Valid result: 42")
    passed, msg = check_pass.check()
    assert passed is True
    assert "non-empty" in msg.lower()

    # Fails: empty string
    check_empty = NonEmptyOutputCheck(output="")
    passed_empty, _ = check_empty.check()
    assert passed_empty is False

    # Fails: whitespace only
    check_ws = NonEmptyOutputCheck(output="   \n  ")
    passed_ws, _ = check_ws.check()
    assert passed_ws is False

    # Fails: starts with "error"
    check_err = NonEmptyOutputCheck(output="Error: something broke")
    passed_err, _ = check_err.check()
    assert passed_err is False


def test_create_criterion_from_dict_invalid_type():
    import pytest
    with pytest.raises(ValueError, match="Unknown verification criterion type"):
        create_criterion_from_dict({"type": "unknown_check"})


def test_infer_verification_from_goal():
    from tal.verification import FileExistsCheck, infer_verification_from_goal

    goal1 = "Use python_repl to generate primes and save to primes_report.txt and confirm."
    c1 = infer_verification_from_goal(goal1)
    assert len(c1) == 1
    assert isinstance(c1[0], FileExistsCheck)
    assert c1[0].path == "primes_report.txt"

    goal2 = "Create a script named fibonacci.py and save output to results.json"
    c2 = infer_verification_from_goal(goal2)
    assert len(c2) == 2
    paths = [c.path for c in c2]
    assert "fibonacci.py" in paths
    assert "results.json" in paths

    goal3 = "What is the capital of France?"
    c3 = infer_verification_from_goal(goal3)
    assert len(c3) == 0


def test_repl_variable_check():
    from tal.verification import REPLVariableCheck
    from tools.external_tools import python_repl, reset_repl_globals

    reset_repl_globals()
    python_repl({"code": "my_nodes = ['A', 'B', 'C']\nval = 42"})

    check_ok = REPLVariableCheck(var_name="my_nodes", assertion_code="len(my_nodes) == 3")
    passed, msg = check_ok.check()
    assert passed is True
    assert "passed" in msg

    check_fail_assert = REPLVariableCheck(var_name="my_nodes", assertion_code="len(my_nodes) == 10")
    passed, msg = check_fail_assert.check()
    assert passed is False
    assert "failed" in msg

    check_missing = REPLVariableCheck(var_name="nonexistent_var")
    passed, msg = check_missing.check()
    assert passed is False
    assert "not found" in msg


def test_repl_graph_check_requires_exact_keys_and_edges():
    from tal.verification import REPLGraphCheck, create_criterion_from_dict
    from tools.external_tools import python_repl, reset_repl_globals

    reset_repl_globals()
    python_repl({
        "code": (
            "service_graph = {\n"
            "    'API_GATEWAY': ['ORDER_SVC'],\n"
            "    'AUDIT_STORE': [],\n"
            "}"
        )
    })

    expected = {
        "API_GATEWAY": ["ORDER_SVC"],
        "AUDIT_STORE": [],
    }
    check = REPLGraphCheck("service_graph", expected)
    passed, message = check.check()
    assert passed is True
    assert "exact keys" in message

    criteria_check = create_criterion_from_dict({
        "type": "repl_graph",
        "variable": "service_graph",
        "expected_graph": expected,
    })
    passed, _ = criteria_check.check()
    assert passed is True

    python_repl({"code": "service_graph.pop('AUDIT_STORE')"})
    passed, message = check.check()
    assert passed is False
    assert "missing keys" in message


def test_json_schema_check():
    import json

    from tal.verification import JSONSchemaCheck

    with tempfile.TemporaryDirectory() as tmpdir:
        json_file = os.path.join(tmpdir, "data.json")
        sample_data = {
            "metadata": {"version": "1.0"},
            "nodes": [{"id": f"node_{i}"} for i in range(12)],
            "edges": [{"source": "a", "target": "b"}]
        }
        with open(json_file, "w") as f:
            json.dump(sample_data, f)

        # Pass: all keys and min items satisfied
        check = JSONSchemaCheck(
            path="data.json",
            required_keys=["metadata", "nodes", "edges"],
            min_items={"nodes": 10}
        )
        passed, msg = check.check(workspace_dir=tmpdir)
        assert passed is True

        # Fail: missing required key
        check_missing_key = JSONSchemaCheck(
            path="data.json",
            required_keys=["attack_paths"]
        )
        passed, msg = check_missing_key.check(workspace_dir=tmpdir)
        assert passed is False
        assert "missing required key" in msg

        # Fail: item count under threshold
        check_count_fail = JSONSchemaCheck(
            path="data.json",
            min_items={"nodes": 20}
        )
        passed, msg = check_count_fail.check(workspace_dir=tmpdir)
        assert passed is False
        assert "expected minimum 20" in msg


def test_cross_entity_consistency_check():
    import json

    from tal.verification import CrossEntityConsistencyCheck

    with tempfile.TemporaryDirectory() as tmpdir:
        json_file = os.path.join(tmpdir, "graph.json")
        md_file = os.path.join(tmpdir, "report.md")

        with open(json_file, "w") as f:
            json.dump({
                "nodes": [{"id": "DMZ_WEB_01"}, {"id": "APP_SRV_01"}, {"id": "CORE_DB_01"}]
            }, f)

        with open(md_file, "w") as f:
            f.write("# Incident Report\nInfected host DMZ_WEB_01 laterally moved to APP_SRV_01 and compromised CORE_DB_01.")

        check = CrossEntityConsistencyCheck(
            source_json_path="graph.json",
            target_file_path="report.md",
            min_match_ratio=0.8
        )
        passed, msg = check.check(workspace_dir=tmpdir)
        assert passed is True

        # Fail when MD file has different entities
        with open(md_file, "w") as f:
            f.write("# Incident Report\nInfected host N01 moved to N02.")

        passed, msg = check.check(workspace_dir=tmpdir)
        assert passed is False
        assert "Cross-entity check failed" in msg


def test_ast_syntax_check():
    from tal.verification import ASTSyntaxCheck

    with tempfile.TemporaryDirectory() as tmpdir:
        valid_py = os.path.join(tmpdir, "valid.py")
        invalid_py = os.path.join(tmpdir, "invalid.py")

        with open(valid_py, "w") as f:
            f.write("def add(a, b):\n    return a + b\n")

        with open(invalid_py, "w") as f:
            f.write("def add(a, b)\n    return a + b\n")

        check_ok = ASTSyntaxCheck(path="valid.py")
        passed, msg = check_ok.check(workspace_dir=tmpdir)
        assert passed is True

        check_bad = ASTSyntaxCheck(path="invalid.py")
        passed, msg = check_bad.check(workspace_dir=tmpdir)
        assert passed is False
        assert "SyntaxError" in msg


def test_missing_acceptance_criteria_cannot_claim_verified_completion():
    passed, messages = run_verification([])
    assert passed is False
    assert "unverified" in messages[0]


def test_fresh_file_does_not_accept_stale_content(temp_workspace):
    from tal.verification import initial_workspace_digest, FreshFileCheck

    target = os.path.join(temp_workspace, "report.txt")
    with open(target, "w", encoding="utf-8") as f:
        f.write("stale content")
    baseline = initial_workspace_digest(temp_workspace, "report.txt")
    gate = FreshFileCheck("report.txt", baseline)
    passed, _ = gate.check(temp_workspace)
    assert not passed
    with open(target, "w", encoding="utf-8") as f:
        f.write("new content")
    passed, _ = gate.check(temp_workspace)
    assert passed


def test_model_completion_without_criteria_is_unverified():
    from agent import BasicAgent
    from tal.outcomes import OutcomeStatus
    from llm_client import LLMClient

    class ScriptedLLM(LLMClient):
        def __init__(self):
            super().__init__("scripted")
        def generate(self, messages, json_mode=False, timeout_seconds=None, response_schema=None):
            return '{"thought":"","action":null,"final_answer":"done"}'
        def generate_with_retry(self, *args, **kwargs):
            return self.generate([])
        @staticmethod
        def list_models():
            return []

    agent = BasicAgent(llm_client=ScriptedLLM(), tal_mode=True)
    result = agent.run_turn_with_trace("Answer a conversational question", max_steps=2)
    assert result["outcome"] == OutcomeStatus.COMPLETED_UNVERIFIED.value
