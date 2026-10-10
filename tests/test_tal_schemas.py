
import pytest

from tal.schemas import (
    CalcParams,
    HelpParams,
    PythonReplParams,
    ReadFileParams,
    RecallParams,
    SchemaViolationError,
    TimeParams,
    WriteFileParams,
    validate_tool_args,
)
from tal.schemas import PipelineStep


def test_calc_params_valid():
    params = CalcParams.from_json('{"expression": "2 + 2"}', "calc")
    assert params.expression == "2 + 2"
    assert params.to_dict() == {"expression": "2 + 2"}


def test_calc_params_closed_schema_extra_fields():
    with pytest.raises(SchemaViolationError) as exc_info:
        CalcParams.from_json('{"expression": "2 + 2", "extra_key": "bad"}', "calc")
    assert "extra_key" in str(exc_info.value)
    assert "forbidden" in str(exc_info.value).lower() or "schema violation" in str(exc_info.value).lower()


def test_calc_params_missing_required():
    with pytest.raises(SchemaViolationError) as exc_info:
        CalcParams.from_json('{}', "calc")
    assert "expression" in str(exc_info.value)


def test_write_file_params():
    params = WriteFileParams.from_json('{"path": "test.txt", "content": "hello"}', "write_file")
    assert params.path == "test.txt"
    assert params.content == "hello"


def test_write_file_extra_field_rejected():
    with pytest.raises(SchemaViolationError):
        WriteFileParams.from_json('{"path": "test.txt", "content": "hello", "mode": "w"}', "write_file")


def test_read_file_optional_pagination():
    params = ReadFileParams.from_json('{"path": "test.txt", "start_line": 1, "end_line": 10}', "read_file")
    assert params.path == "test.txt"
    assert params.start_line == 1
    assert params.end_line == 10

    params_no_lines = ReadFileParams.from_json('{"path": "test.txt"}', "read_file")
    assert params_no_lines.start_line is None
    assert params_no_lines.end_line is None


def test_recall_empty_args():
    params = RecallParams.from_json('{}', "recall")
    assert params.key == ""


def test_pipeline_step_parses_declared_state_exports():
    step = PipelineStep.from_dict({
        "step_id": "persist_state",
        "objective": "Persist safe state",
        "state_exports": ["orders", "ledger_events"],
    })
    assert step.state_exports == ["orders", "ledger_events"]


def test_pipeline_step_rejects_unsafe_state_export_name():
    with pytest.raises(ValueError, match="state_exports"):
        PipelineStep.from_dict({
            "step_id": "bad_export",
            "objective": "Bad export",
            "state_exports": ["not-valid"],
        })

    params_with_key = RecallParams.from_json('{"key": "my_fact"}', "recall")
    assert params_with_key.key == "my_fact"


def test_time_and_help_empty_args():
    p_time = TimeParams.from_json('{}', "time")
    assert p_time.to_dict() == {}
    p_help = HelpParams.from_json('', "help")
    assert p_help.to_dict() == {}


def test_validate_tool_args_helper():
    valid = validate_tool_args("calc", '{"expression": "10 * 5"}')
    assert isinstance(valid, CalcParams)
    assert valid.expression == "10 * 5"

    with pytest.raises(SchemaViolationError):
        validate_tool_args("calc", '{"wrong": "format"}')


def test_schema_auto_strips_leaked_meta_fields():
    # SLMs commonly leak top-level ReAct keys into tool args
    payload = {
        "path": "script.py",
        "content": "print('hello')",
        "final_answer": None,
        "thought": "Writing script",
        "tool": "write_file",
        "action": None
    }
    params = WriteFileParams.from_dict(payload, "write_file")
    assert params.path == "script.py"
    assert params.content == "print('hello')"

    # Verify python_repl also ignores leaked meta fields
    repl_payload = {
        "code": "1 + 1",
        "final_answer": None,
        "thought": "calculating"
    }
    repl_params = PythonReplParams.from_dict(repl_payload, "python_repl")
    assert repl_params.code == "1 + 1"
