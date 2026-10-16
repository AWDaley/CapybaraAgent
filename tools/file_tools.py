import json
import os
from typing import Any

from tal.safe_paths import resolve_workspace_path

# Sandbox directory for file operations
# Sandbox directory for file operations
WORKSPACE_DIR = os.path.realpath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "workspace"))
os.makedirs(WORKSPACE_DIR, exist_ok=True)

def _get_safe_path(filename: str) -> str:
    """Ensures the file path stays within the sandbox directory."""
    return resolve_workspace_path(WORKSPACE_DIR, filename)

def _parse_tool_args(args: Any) -> dict:
    """Helper to parse tool args whether dict, JSON string, or repairable string."""
    if isinstance(args, dict):
        return args
    try:
        return json.loads(str(args))
    except (json.JSONDecodeError, TypeError):
        try:
            from tal.repair import repair_json_string
            return json.loads(repair_json_string(str(args)))
        except Exception:
            raise json.JSONDecodeError("Invalid JSON", str(args), 0)

def write_file(args: str) -> str:
    """Writes content to a file in the workspace. Expects JSON args."""
    try:
        data = _parse_tool_args(args)
        filename = data.get("path", "")
        content = data.get("content", "")
        
        if not filename:
            return "Error: 'path' must be provided."
            
        MAX_FILE_SIZE = 1 * 1024 * 1024  # 1 MB limit
        if len(content.encode('utf-8')) > MAX_FILE_SIZE:
            return "Error: File content exceeds maximum allowed size of 1MB."
            
        # AST Syntax Guard for Python files
        if filename.endswith(".py"):
            import ast
            try:
                ast.parse(content)
            except SyntaxError as se:
                return f"Error: Python SyntaxError in '{filename}' at line {se.lineno}: {se.msg}. The script appears truncated or malformed. Please output the complete, valid script."

        safe_path = _get_safe_path(filename)
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"File written successfully: {filename}"
    except json.JSONDecodeError:
        return "Error: Arguments must be valid JSON: {\"path\": \"...\", \"content\": \"...\"}"
    except Exception as e:
        return f"Error writing file: {e}"

def read_file(args: str) -> str:
    """Reads a file from the workspace. Expects JSON args."""
    try:
        data = _parse_tool_args(args)
        filename = data.get("path", "")
        
        if not filename:
            return "Error: 'path' must be provided."
            
        safe_path = _get_safe_path(filename)
        if not os.path.exists(safe_path):
            return f"Error: File '{filename}' does not exist."
            
        with open(safe_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        start_line = data.get("start_line")
        end_line = data.get("end_line")
        total_lines = len(lines)

        if start_line is not None or end_line is not None:
            s = max(0, (start_line or 1) - 1)
            e = min(total_lines, end_line or total_lines)
            lines = lines[s:e]
            header = f"[Showing lines {s+1}-{e} of {total_lines}]\n"
        else:
            header = ""

        content = "".join(lines)
        max_len = 10000
        if len(content) > max_len:
            content = content[:max_len] + f"\n... (truncated — {total_lines} total lines, use start_line/end_line to paginate)"
        return header + content
    except json.JSONDecodeError:
        return "Error: Arguments must be valid JSON: {\"path\": \"...\"}"
    except Exception as e:
        return f"Error reading file: {e}"

def list_files(args: str = "") -> str:
    """Lists all files in the workspace directory. Expects empty JSON args."""
    try:
        files = os.listdir(WORKSPACE_DIR)
        if not files:
            return "The workspace is empty."
        return "Files in workspace:\n" + "\n".join(f"- {f}" for f in files)
    except Exception as e:
        return f"Error listing files: {e}"

FILE_TOOL_REGISTRY = {
    "write_file": write_file,
    "read_file": read_file,
    "list_files": list_files,
}

FILE_TOOL_DESCRIPTIONS = '''
8. {"tool": "write_file", "args": "{\\"path\\": \\"filename.txt\\", \\"content\\": \\"file text\\"}"}
   - Writes content to a file in the workspace. MUST pass JSON arguments.
9. {"tool": "read_file", "args": "{\\"path\\": \\"filename.txt\\", \\"start_line\\": 1, \\"end_line\\": 50}"}
   - Reads a file from the workspace. Optionally specify start_line and end_line for large files. MUST pass JSON arguments.
10. {"tool": "list_files", "args": "{}"}
   - Lists all files in the workspace directory. MUST pass empty JSON arguments.
'''
