import os
import re
from typing import Any

from .safe_eval import evaluate_expression
from .safe_paths import resolve_workspace_path


def _workspace_path(workspace_dir: str, path: str) -> str:
    return resolve_workspace_path(workspace_dir, path) if workspace_dir else path


class VerificationCriterion:
    """Abstract base class for deterministic acceptance verification."""
    def check(self, workspace_dir: str = "") -> tuple[bool, str]:
        raise NotImplementedError


class FileExistsCheck(VerificationCriterion):
    def __init__(self, path: str, min_size_bytes: int = 0):
        self.path = path
        self.min_size_bytes = min_size_bytes

    def check(self, workspace_dir: str = "") -> tuple[bool, str]:
        try:
            full_path = _workspace_path(workspace_dir, self.path)
        except ValueError as exc:
            return False, f"Invalid file path '{self.path}': {exc}"

        if not os.path.exists(full_path):
            return False, f"File '{self.path}' does not exist"
        
        size = os.path.getsize(full_path)
        if size < self.min_size_bytes:
            return False, f"File '{self.path}' size ({size} bytes) is less than required ({self.min_size_bytes} bytes)"
        return True, f"File '{self.path}' verified ({size} bytes)"


class ExitCodeCheck(VerificationCriterion):
    def __init__(self, command: str, expected_code: int = 0):
        self.command = command
        self.expected_code = expected_code

    def check(self, workspace_dir: str = "") -> tuple[bool, str]:
        # Verification must not be an alternate execution channel.  Commands
        # belong to the action gate, approval flow, and isolated executor.
        return False, (
            "Exit-code verification is disabled: acceptance criteria must be "
            "declarative (file, JSON, AST, regex, or non-empty-output checks)."
        )


class RegexMatchCheck(VerificationCriterion):
    def __init__(self, text: str, pattern: str):
        self.text = text
        self.pattern = pattern

    def check(self, workspace_dir: str = "") -> tuple[bool, str]:
        if re.search(self.pattern, self.text):
            return True, f"Pattern '{self.pattern}' matched output"
        return False, f"Pattern '{self.pattern}' did not match output"


class NonEmptyOutputCheck(VerificationCriterion):
    def __init__(self, output: str):
        self.output = output

    def check(self, workspace_dir: str = "") -> tuple[bool, str]:
        cleaned = self.output.strip()
        if cleaned and not cleaned.lower().startswith("error"):
            return True, "Output is non-empty and non-error"
        return False, "Output was empty or contained error"


class REPLVariableCheck(VerificationCriterion):
    """Verifies that a variable exists in the Python REPL environment and optionally satisfies an assertion."""
    def __init__(self, var_name: str, assertion_code: str | None = None):
        self.var_name = var_name
        self.assertion_code = assertion_code

    def check(self, workspace_dir: str = "", repl_globals: dict | None = None) -> tuple[bool, str]:
        try:
            from tools.external_tools import get_repl_globals
            # Work from a shallow snapshot.  Verification is read-only and must
            # never repair, alias, or otherwise mutate the execution namespace.
            scope = dict(repl_globals) if repl_globals is not None else dict(get_repl_globals())
            if self.var_name not in scope:
                return False, f"REPL variable '{self.var_name}' not found in environment."
            if self.assertion_code:
                try:
                    result = evaluate_expression(self.assertion_code, scope)
                    if not bool(result):
                        return False, f"REPL assertion failed: '{self.assertion_code}' evaluated to {result} (False)."
                    return True, f"REPL assertion passed: '{self.assertion_code}' -> True."
                except Exception as e:
                    return False, f"REPL assertion error evaluating '{self.assertion_code}': {e}"
            return True, f"REPL variable '{self.var_name}' verified in environment."
        except Exception as e:
            return False, f"Failed to check REPL environment: {e}"


class REPLGraphCheck(VerificationCriterion):
    """Verifies an exact adjacency mapping in the stateful Python REPL."""

    def __init__(self, var_name: str, expected_graph: dict[str, list[str]]):
        self.var_name = var_name
        self.expected_graph = expected_graph

    def check(self, workspace_dir: str = "", repl_globals: dict | None = None) -> tuple[bool, str]:
        try:
            from tools.external_tools import get_repl_globals

            scope = dict(repl_globals) if repl_globals is not None else dict(get_repl_globals())
            if self.var_name not in scope:
                return False, f"REPL variable '{self.var_name}' not found in environment."

            actual = scope[self.var_name]
            if not isinstance(actual, dict):
                return False, (
                    f"REPL graph '{self.var_name}' must be a dict; "
                    f"got {type(actual).__name__}."
                )

            expected_keys = set(self.expected_graph)
            actual_keys = set(actual)
            missing = sorted(expected_keys - actual_keys)
            extra = sorted(actual_keys - expected_keys)
            mismatches = []
            for key in sorted(expected_keys & actual_keys):
                expected_targets = self.expected_graph[key]
                actual_targets = actual[key]
                if actual_targets != expected_targets:
                    mismatches.append(
                        f"{key}: expected {expected_targets!r}, got {actual_targets!r}"
                    )

            if missing or extra or mismatches:
                details = []
                if missing:
                    details.append(f"missing keys={missing!r}")
                if extra:
                    details.append(f"extra keys={extra!r}")
                if mismatches:
                    details.append("incorrect edges=" + "; ".join(mismatches))
                return False, f"REPL graph '{self.var_name}' failed exact check: " + ", ".join(details)

            return True, (
                f"REPL graph '{self.var_name}' verified with "
                f"{len(expected_keys)} exact keys and directed edges."
            )
        except Exception as e:
            return False, f"Failed to check REPL graph: {e}"


class JSONSchemaCheck(VerificationCriterion):
    """Verifies that a JSON file exists, parses correctly, contains required keys, and meets minimum item counts."""
    def __init__(
        self,
        path: str,
        required_keys: list[str] | None = None,
        min_items: dict[str, int] | None = None,
        min_size_bytes: int = 1
    ):
        self.path = path
        self.required_keys = required_keys or []
        self.min_items = min_items or {}
        self.min_size_bytes = min_size_bytes

    def check(self, workspace_dir: str = "") -> tuple[bool, str]:
        try:
            full_path = _workspace_path(workspace_dir, self.path)
        except ValueError as exc:
            return False, f"Invalid JSON path '{self.path}': {exc}"
        if not os.path.exists(full_path):
            return False, f"JSON file '{self.path}' does not exist."
        if os.path.getsize(full_path) < self.min_size_bytes:
            return False, f"JSON file '{self.path}' is empty or smaller than {self.min_size_bytes} bytes."
        try:
            import json
            with open(full_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return False, f"File '{self.path}' is not valid JSON: {e}"

        if not isinstance(data, dict):
            return False, f"JSON root in '{self.path}' must be an object/dict (got {type(data).__name__})."

        for k in self.required_keys:
            if k not in data:
                return False, f"JSON file '{self.path}' missing required key: '{k}'."

        for k, min_count in self.min_items.items():
            if k not in data:
                return False, f"JSON file '{self.path}' missing key for count check: '{k}'."
            val = data[k]
            if isinstance(val, (list, dict, set, str)):
                actual_count = len(val)
                if actual_count < min_count:
                    return False, f"JSON key '{k}' in '{self.path}' has count {actual_count} < expected minimum {min_count}."
        return True, f"JSON schema check passed for '{self.path}' (required keys and item counts satisfied)."


class CrossEntityConsistencyCheck(VerificationCriterion):
    """Verifies that entity names/IDs defined in a source JSON file are consistently referenced in a target Markdown/text file."""
    def __init__(
        self,
        source_json_path: str,
        target_file_path: str,
        entity_key: str = "nodes",
        entity_id_field: str = "id",
        min_match_ratio: float = 0.5
    ):
        self.source_json_path = source_json_path
        self.target_file_path = target_file_path
        self.entity_key = entity_key
        self.entity_id_field = entity_id_field
        self.min_match_ratio = min_match_ratio

    def check(self, workspace_dir: str = "") -> tuple[bool, str]:
        try:
            src_path = _workspace_path(workspace_dir, self.source_json_path)
            tgt_path = _workspace_path(workspace_dir, self.target_file_path)
        except ValueError as exc:
            return False, f"Invalid cross-reference path: {exc}"

        if not os.path.exists(src_path):
            return False, f"Source JSON '{self.source_json_path}' does not exist for cross-reference check."
        if not os.path.exists(tgt_path):
            return False, f"Target file '{self.target_file_path}' does not exist for cross-reference check."

        try:
            import json
            with open(src_path, "r", encoding="utf-8") as f:
                src_data = json.load(f)
            with open(tgt_path, "r", encoding="utf-8") as f:
                tgt_content = f.read()

            entities = []
            node_items = src_data.get(self.entity_key, [])
            if isinstance(node_items, list):
                for item in node_items:
                    if isinstance(item, dict) and self.entity_id_field in item:
                        entities.append(str(item[self.entity_id_field]))
                    elif isinstance(item, str):
                        entities.append(item)
            elif isinstance(node_items, dict):
                entities = list(node_items.keys())

            if not entities:
                return True, f"No entities found under '{self.entity_key}' in '{self.source_json_path}' to cross-check."

            matched = [e for e in entities if re.search(rf'\b{re.escape(e)}\b', tgt_content, re.IGNORECASE)]
            ratio = len(matched) / len(entities)

            if ratio < self.min_match_ratio:
                missing = [e for e in entities if e not in matched]
                return False, f"Cross-entity check failed: '{self.target_file_path}' contains only {len(matched)}/{len(entities)} entities from '{self.source_json_path}'. Missing: {missing[:5]}."

            return True, f"Cross-entity check passed: {len(matched)}/{len(entities)} entities verified between '{self.source_json_path}' and '{self.target_file_path}'."
        except Exception as e:
            return False, f"Cross-entity check failed with error: {e}"


class ASTSyntaxCheck(VerificationCriterion):
    """Verifies that a Python file in workspace parses to valid AST with zero syntax errors."""
    def __init__(self, path: str):
        self.path = path

    def check(self, workspace_dir: str = "") -> tuple[bool, str]:
        try:
            full_path = _workspace_path(workspace_dir, self.path)
        except ValueError as exc:
            return False, f"Invalid AST path '{self.path}': {exc}"
        if not os.path.exists(full_path):
            return False, f"File '{self.path}' does not exist."
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                code = f.read()
            import ast
            ast.parse(code)
            return True, f"AST syntax check passed for '{self.path}'."
        except SyntaxError as se:
            return False, f"AST SyntaxError in '{self.path}' at line {se.lineno}: {se.msg}"
        except Exception as e:
            return False, f"AST check failed for '{self.path}': {e}"


def create_criterion_from_dict(d: dict[str, Any]) -> VerificationCriterion:
    ctype = d.get("type", "").lower()
    if ctype == "file_exists":
        return FileExistsCheck(path=d.get("path", ""), min_size_bytes=int(d.get("min_size", 0)))
    elif ctype == "exit_code":
        return ExitCodeCheck(command=d.get("command", ""), expected_code=int(d.get("expected_code", 0)))
    elif ctype == "regex_match":
        return RegexMatchCheck(text=d.get("text", ""), pattern=d.get("pattern", ""))
    elif ctype == "non_empty":
        return NonEmptyOutputCheck(output=d.get("output", ""))
    elif ctype in ("repl_variable", "repl_state", "repl_variable_exists"):
        return REPLVariableCheck(var_name=d.get("variable", d.get("var_name", "")), assertion_code=d.get("assertion", d.get("assertion_code")))
    elif ctype in ("repl_graph", "repl_adjacency", "repl_adjacency_graph"):
        expected_graph = d.get("expected_graph") or d.get("expected_adjacency") or {}
        if not isinstance(expected_graph, dict) or not all(
            isinstance(key, str)
            and isinstance(value, list)
            and all(isinstance(target, str) for target in value)
            for key, value in expected_graph.items()
        ):
            raise ValueError("REPL graph expected_graph must map strings to lists of strings")
        return REPLGraphCheck(
            var_name=d.get("variable", d.get("var_name", "")),
            expected_graph=expected_graph,
        )
    elif ctype in ("json_schema", "file_json_schema", "json_check"):
        return JSONSchemaCheck(
            path=d.get("path", ""),
            required_keys=d.get("required_keys", []),
            min_items=d.get("min_items", {}),
            min_size_bytes=int(d.get("min_size", 1))
        )
    elif ctype in ("cross_entity", "cross_reference", "cross_entity_consistency"):
        return CrossEntityConsistencyCheck(
            source_json_path=d.get("source_json", d.get("source_json_path", "")),
            target_file_path=d.get("target_file", d.get("target_file_path", d.get("target_md_path", ""))),
            entity_key=d.get("entity_key", "nodes"),
            entity_id_field=d.get("entity_id_field", "id"),
            min_match_ratio=float(d.get("min_match_ratio", 0.5))
        )
    elif ctype in ("ast_syntax", "python_syntax"):
        return ASTSyntaxCheck(path=d.get("path", ""))
    raise ValueError(f"Unknown verification criterion type: '{ctype}'")


def run_verification(
    criteria: list[VerificationCriterion | dict[str, Any]],
    workspace_dir: str = "",
    repl_globals: dict | None = None,
) -> tuple[bool, list[str]]:
    """Runs all verification criteria. Returns (all_passed, messages)."""
    if not criteria:
        return True, ["No verification criteria specified"]

    all_passed = True
    messages = []

    for c in criteria:
        if isinstance(c, dict):
            criterion = create_criterion_from_dict(c)
        else:
            criterion = c
        if repl_globals is not None and isinstance(criterion, (REPLVariableCheck, REPLGraphCheck)):
            passed, msg = criterion.check(workspace_dir=workspace_dir, repl_globals=repl_globals)
        else:
            passed, msg = criterion.check(workspace_dir=workspace_dir)
        messages.append(msg)
        if not passed:
            all_passed = False

    return all_passed, messages


def infer_verification_from_goal(goal: str) -> list[VerificationCriterion]:
    """Infers verification criteria automatically from user goals / prompt texts.
    
    Detects target file outputs (e.g. 'save to primes_report.txt', 'script named stats.py')
    and creates deterministic FileExistsCheck criteria.
    """
    criteria: list[VerificationCriterion] = []
    if not goal:
        return criteria

    # Find filenames with common file extensions
    file_matches = re.findall(
        r'\b([a-zA-Z0-9_\-]+\.(?:txt|py|json|csv|md|html|log|yaml|yml))\b',
        goal,
        re.IGNORECASE
    )
    
    seen = set()
    for filename in file_matches:
        fn_lower = filename.lower()
        if fn_lower not in seen:
            seen.add(fn_lower)
            criteria.append(FileExistsCheck(path=filename, min_size_bytes=1))

    return criteria


def materialize_missing_deliverables(
    context_text: str,
    workspace_dir: str,
    missing_files: list[str]
) -> list[str]:
    """
    Extracts structured deliverables (JSON objects, Markdown reports, Python scripts)
    from markdown code fences or labeled sections in context_text and writes them
    to workspace_dir for any missing target files.
    Returns the list of successfully materialized filenames.
    """
    if not context_text or not workspace_dir or not missing_files:
        return []
    
    os.makedirs(workspace_dir, exist_ok=True)
    materialized = []

    for filename in missing_files:
        try:
            target_path = resolve_workspace_path(workspace_dir, filename)
        except ValueError:
            continue
        if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
            continue

        extracted_content = None

        # Strategy 1: Explicitly labeled file block
        # e.g., #### **File: `incident_graph_data.json`**\n```json\n{...}\n```
        escaped_fn = re.escape(filename)
        label_pattern = re.compile(
            rf'(?:###+\s*(?:\*\*)?File:\s*[`\'"]?{escaped_fn}[`\'"]?(?:\*\*)?|```(?:[a-zA-Z0-9_-]+:)?{escaped_fn}\b)[\s\S]*?```(?:[a-zA-Z0-9_-]+)?\s*([\s\S]+?)\s*```',
            re.IGNORECASE
        )
        match = label_pattern.search(context_text)
        if match:
            extracted_content = match.group(1).strip()

        # Strategy 2: If JSON file and not found by label, look for valid JSON code blocks
        if not extracted_content and filename.endswith(".json"):
            json_blocks = re.findall(r'```(?:json)?\s*(\{[\s\S]+?\}|\[[\s\S]+?\])\s*```', context_text)
            for block in json_blocks:
                try:
                    import json
                    json.loads(block)
                    extracted_content = block.strip()
                    break
                except Exception:
                    continue

        # Strategy 3: If Markdown report and not found by label, extract formatted markdown report sections
        if not extracted_content and filename.endswith(".md"):
            md_block = re.search(r'```(?:markdown|md)?\s*(#[\s\S]+?)\s*```', context_text)
            if md_block:
                extracted_content = md_block.group(1).strip()
            else:
                section_match = re.search(rf'(?:File:\s*[`\'"]?{escaped_fn}[`\'"]?[\s\S]*?\n)(#\s+[\s\S]+)', context_text, re.IGNORECASE)
                if section_match:
                    extracted_content = section_match.group(1).strip()

        # Strategy 4: If Python file, extract python code fence
        if not extracted_content and filename.endswith(".py"):
            py_block = re.search(r'```(?:python)?\s*([\s\S]+?)\s*```', context_text)
            if py_block:
                candidate = py_block.group(1).strip()
                if len(candidate) > 20:
                    extracted_content = candidate

        if extracted_content:
            try:
                if filename.lower().endswith(".py"):
                    import ast
                    ast.parse(extracted_content)
                with open(target_path, "w", encoding="utf-8") as f:
                    f.write(extracted_content)
                materialized.append(filename)
            except Exception:
                pass

    return materialized
