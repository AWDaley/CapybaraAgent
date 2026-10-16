import json
import uuid

import pytest

from tal.materializer import OutputMaterializer
from tal.safe_eval import SafeExpressionError, evaluate_expression
from tal.safe_paths import resolve_workspace_path
from tal.schemas import OutputSpec
from tal.verification import ExitCodeCheck, FileExistsCheck
from tools.external_tools import create_repl_scope, read_url, run_command


def test_workspace_paths_reject_traversal_and_absolute(temp_workspace):
    for path in ("../outside.txt", "C:/outside.txt", "/outside.txt"):
        try:
            resolve_workspace_path(temp_workspace, path)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe path accepted: {path}")


def test_materializer_rejects_unsafe_path_and_expression(temp_workspace):
    spec = OutputSpec(target_file="../outside.json", spec_type="text", template="nope")
    ok, message, _ = OutputMaterializer.materialize_to_file(spec, temp_workspace, {})
    assert not ok
    assert "Invalid output target" in message

    try:
        evaluate_expression("value.__class__", {"value": 1})
    except SafeExpressionError:
        pass
    else:
        raise AssertionError("attribute access must be rejected")

    try:
        evaluate_expression("str(value)", {"value": 1})
    except SafeExpressionError:
        pass
    else:
        raise AssertionError("function calls must be rejected")


def test_verification_rejects_shell_and_escaping_paths(temp_workspace):
    passed, message = ExitCodeCheck("python -c \"print('unsafe')\"").check(temp_workspace)
    assert not passed
    assert "disabled" in message

    passed, message = FileExistsCheck("../outside.txt").check(temp_workspace)
    assert not passed
    assert "Invalid file path" in message


def test_read_url_rejects_local_file_scheme():
    result = read_url(json.dumps({"url": "file:///etc/passwd"}))
    assert result.startswith("Error reading URL: Only http and https")


def test_command_rejects_absolute_and_parent_paths(temp_workspace):
    assert "outside the workspace" in run_command(json.dumps({"command": "python ../escape.py"}))
    assert "outside the workspace" in run_command(json.dumps({"command": "python C:/escape.py"}))


def test_repl_scopes_are_isolated_and_bound_execution():
    first = create_repl_scope()
    second = create_repl_scope()
    assert "42" in first.run({"code": "answer = 42\nprint(answer)"})
    assert "answer" not in second.globals
    result = first.run({"code": "while True:\n    pass"})
    assert "resource limit" in result


def test_session_storage_is_namespaced():
    from memory.session_manager import SessionManager
    first = SessionManager(session_namespace=str(uuid.uuid4()))
    second = SessionManager(session_namespace=str(uuid.uuid4()))
    assert first.sessions_dir != second.sessions_dir

@pytest.mark.parametrize("unsafe_path", [
    "../escape", "nested/../escape", "..\\escape",
    "C:/outside.txt", "C:\\outside.txt", "C:relative.txt",
    "\\\\server\\share\\file.txt", "//server/share/file.txt",
    "/tmp/outside", "\\Windows\\system.ini", "\\\\?\\C:\\secret.txt",
])
def test_cross_platform_absolute_and_traversal_rejected(temp_workspace, unsafe_path):
    with pytest.raises(ValueError):
        resolve_workspace_path(temp_workspace, unsafe_path)


def test_relative_nested_workspace_path_allowed(temp_workspace):
    import os
    assert os.path.commonpath([os.path.realpath(temp_workspace), resolve_workspace_path(temp_workspace, "reports/2026/out.json")]) == os.path.realpath(temp_workspace)


def test_workspace_symlink_escape_is_rejected(temp_workspace, tmp_path):
    target = tmp_path / "outside"
    target.mkdir()
    link = tmp_path / "linked"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Creating symlinks is unavailable on this platform")
    # Ensure the symlink itself is inside the temporary workspace.
    import os
    inner = os.path.join(temp_workspace, "out")
    os.symlink(target, inner, target_is_directory=True)
    with pytest.raises(ValueError):
        resolve_workspace_path(temp_workspace, "out/secret.txt")
