import json
import logging
import os
from dataclasses import asdict, is_dataclass
from typing import Any

from .safe_eval import evaluate_expression
from .safe_paths import resolve_workspace_path
from .schemas import OutputSpec

logger = logging.getLogger("capybara.materializer")


class OutputMaterializer:
    """Deterministically extracts state from runtime environments (such as REPL)
    and serializes structured output deliverables into workspace files.
    """

    @classmethod
    def coerce_serializable(cls, obj: Any) -> Any:
        """Recursively converts non-standard Python objects into JSON-serializable primitives."""
        if obj is None or isinstance(obj, (bool, int, float, str)):
            return obj
        if isinstance(obj, (list, tuple, set)):
            return [cls.coerce_serializable(x) for x in obj]
        if isinstance(obj, dict):
            return {str(k): cls.coerce_serializable(v) for k, v in obj.items()}
        if is_dataclass(obj):
            return cls.coerce_serializable(asdict(obj))
        if hasattr(obj, "to_dict") and callable(obj.to_dict):
            return cls.coerce_serializable(obj.to_dict())
        if hasattr(obj, "nodes") and hasattr(obj, "edges"):
            # Handle NetworkX Graph objects
            try:
                nodes_list = []
                for n, d in obj.nodes(data=True):
                    node_entry = {"id": str(n)}
                    if d:
                        node_entry.update(cls.coerce_serializable(d))
                    nodes_list.append(node_entry)
                edges_list = []
                for u, v, d in obj.edges(data=True):
                    edge_entry = {"source": str(u), "target": str(v)}
                    if d:
                        edge_entry.update(cls.coerce_serializable(d))
                    edges_list.append(edge_entry)
                return {"nodes": nodes_list, "edges": edges_list}
            except Exception:
                pass
        if hasattr(obj, "__dict__"):
            return cls.coerce_serializable(obj.__dict__)
        return str(obj)

    @classmethod
    def resolve_template(cls, template: Any, repl_globals: dict) -> Any:
        """Recursively resolves $eval:<expression> and inline $eval{...} string markers within template structures."""
        if isinstance(template, str):
            s = template.strip()
            if s.startswith("$eval:") and "\n" not in s:
                expr = s[6:].strip()
                try:
                    result = evaluate_expression(expr, repl_globals)
                    return cls.coerce_serializable(result)
                except Exception as e:
                    logger.warning(f"Failed to evaluate template expression '{expr}': {e}")
                    return f"Error evaluating expression '{expr}': {e}"

            # Inline pattern substitution for multiline text / markdown / strings
            import re
            def _eval_sub(match):
                expr = match.group(1).strip()
                try:
                    res = evaluate_expression(expr, repl_globals)
                    coerced = cls.coerce_serializable(res)
                    if isinstance(coerced, (list, dict)):
                        return json.dumps(coerced)
                    return str(coerced)
                except Exception as e:
                    logger.warning(f"Failed to evaluate inline expression '{expr}': {e}")
                    return f"<eval_error: {e}>"

            interpolated = re.sub(r'\$eval\{([^}]+)\}', _eval_sub, template)
            interpolated = re.sub(r'\$\{eval:([^}]+)\}', _eval_sub, interpolated)
            return interpolated

        if isinstance(template, dict):
            return {k: cls.resolve_template(v, repl_globals) for k, v in template.items()}
        if isinstance(template, list):
            return [cls.resolve_template(x, repl_globals) for x in template]
        return cls.coerce_serializable(template)

    @classmethod
    def materialize_to_file(
        cls,
        spec: OutputSpec,
        workspace_dir: str,
        repl_globals: dict | None = None
    ) -> tuple[bool, str, Any]:
        """Evaluates data from REPL or template and serializes directly to target_file."""
        if not spec or not spec.target_file:
            return False, "No output spec or target file provided", None

        if repl_globals is None:
            from tools.external_tools import get_repl_globals
            repl_globals = get_repl_globals()

        os.makedirs(workspace_dir, exist_ok=True)
        try:
            target_path = resolve_workspace_path(workspace_dir, spec.target_file)
        except ValueError as exc:
            return False, f"Invalid output target '{spec.target_file}': {exc}", None

        data_to_write = None

        try:
            if spec.spec_type in ("repl_template", "template", "markdown_template", "text_template", "md_template"):
                if spec.template is not None:
                    data_to_write = cls.resolve_template(spec.template, repl_globals)
                else:
                    return False, f"OutputSpec '{spec.target_file}' specified template mode but template is None", None

            elif spec.spec_type in ("repl_variable", "variable"):
                var_name = spec.source_variable
                if not var_name or var_name not in repl_globals:
                    return False, f"REPL source variable '{var_name}' not found in environment", None
                data_to_write = cls.coerce_serializable(repl_globals[var_name])

            elif spec.spec_type in ("repl_expr", "expr", "expression"):
                expr = spec.eval_expr or spec.source_variable
                if not expr:
                    return False, f"OutputSpec '{spec.target_file}' specified expr mode but eval_expr is empty", None
                evaluated = evaluate_expression(expr, repl_globals)
                data_to_write = cls.coerce_serializable(evaluated)

            elif spec.spec_type in ("text", "raw"):
                data_to_write = spec.template if spec.template is not None else ""

            else:
                return False, f"Unknown OutputSpec type '{spec.spec_type}'", None

            # Write file to disk
            if spec.target_file.endswith(".json") and not isinstance(data_to_write, str):
                with open(target_path, "w", encoding="utf-8") as f:
                    json.dump(data_to_write, f, indent=spec.indent)
            else:
                with open(target_path, "w", encoding="utf-8") as f:
                    if isinstance(data_to_write, (dict, list)):
                        json.dump(data_to_write, f, indent=spec.indent)
                    else:
                        f.write(str(data_to_write))

            size_bytes = os.path.getsize(target_path)
            msg = f"Deterministically materialized deliverable '{spec.target_file}' ({size_bytes} bytes)."
            logger.info(msg)
            return True, msg, data_to_write

        except Exception as e:
            err_msg = f"Failed to materialize deliverable '{spec.target_file}': {e}"
            logger.error(err_msg)
            return False, err_msg, None
