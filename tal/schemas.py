import json
from dataclasses import asdict, dataclass, field
from typing import Any


class SchemaViolationError(Exception):
    """Raised when tool arguments violate the closed schema."""
    def __init__(self, tool_name: str, errors: list[dict[str, str]]):
        self.tool_name = tool_name
        self.errors = errors
        error_details = "; ".join(f"{e.get('field', 'param')}: {e.get('reason', 'invalid')}" for e in errors)
        super().__init__(f"Schema violation for tool '{tool_name}': {error_details}")


@dataclass
class ToolParamSchema:
    """Base class for closed tool parameter schemas."""
    _FIELDS: dict[str, tuple[Any, bool]] = field(default_factory=dict, init=False, repr=False)
    _ALLOW_EMPTY_PAYLOAD: bool = field(default=False, init=False, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any], tool_name: str = "") -> "ToolParamSchema":
        errors: list[dict[str, str]] = []
        if not isinstance(data, dict):
            raise SchemaViolationError(tool_name, [{"field": "root", "reason": "Expected JSON object dictionary"}])

        # Filter out leaked top-level agent/framework meta-fields that SLMs often accidentally nest inside args
        META_FIELDS = {"thought", "final_answer", "action", "tool", "name", "stage"}
        filtered_data = {k: v for k, v in data.items() if k not in META_FIELDS or k in cls._FIELDS}

        allowed_fields = set(cls._FIELDS.keys())
        extra_fields = set(filtered_data.keys()) - allowed_fields
        if extra_fields:
            for extra in sorted(extra_fields):
                errors.append({"field": extra, "reason": "Unexpected field forbidden by closed schema"})

        cleaned_kwargs = {}
        for field_name, (expected_type, required) in cls._FIELDS.items():
            if field_name in filtered_data:
                val = filtered_data[field_name]
                if expected_type is not None:
                    # Handle tuple of types or single type
                    if isinstance(expected_type, tuple):
                        type_match = isinstance(val, expected_type)
                    else:
                        type_match = isinstance(val, expected_type)
                    if not type_match and val is not None:
                        errors.append({
                            "field": field_name,
                            "reason": f"Expected type {expected_type}, got {type(val).__name__}"
                        })
                cleaned_kwargs[field_name] = val
            elif required:
                errors.append({"field": field_name, "reason": "Required field missing"})

        if errors:
            raise SchemaViolationError(tool_name or cls.__name__, errors)

        return cls(**cleaned_kwargs)

    @classmethod
    def from_json(cls, raw: Any, tool_name: str = "") -> "ToolParamSchema":
        if isinstance(raw, cls):
            return raw
        if isinstance(raw, dict):
            return cls.from_dict(raw, tool_name=tool_name)
        if raw is None:
            if cls._ALLOW_EMPTY_PAYLOAD:
                return cls.from_dict({}, tool_name=tool_name)
            raise SchemaViolationError(tool_name, [{"field": "root", "reason": "Empty arguments not allowed"}])

        if isinstance(raw, str):
            s = raw.strip()
            if not s:
                if cls._ALLOW_EMPTY_PAYLOAD:
                    return cls.from_dict({}, tool_name=tool_name)
                # Check if all fields are optional
                all_optional = all(not req for _, req in cls._FIELDS.values())
                if all_optional:
                    return cls.from_dict({}, tool_name=tool_name)
                raise SchemaViolationError(tool_name, [{"field": "root", "reason": "Empty arguments not allowed"}])

            # Try parsing JSON
            parsed = None
            try:
                parsed = json.loads(s)
            except json.JSONDecodeError:
                # Attempt heuristic repair for SLM control characters, single quotes, trailing commas
                from .repair import repair_json_string
                try:
                    repaired_s = repair_json_string(s)
                    parsed = json.loads(repaired_s)
                except Exception:
                    parsed = None

            if parsed is None:
                # If raw string is passed to a single required string field schema (e.g. web_search "query"),
                # allow graceful coercion if appropriate, otherwise reject with syntax error.
                if len(cls._FIELDS) == 1:
                    only_field, (ftype, _) = next(iter(cls._FIELDS.items()))
                    if ftype is str:
                        return cls.from_dict({only_field: s}, tool_name=tool_name)
                raise SchemaViolationError(tool_name, [{"field": "root", "reason": f"Invalid JSON string: {raw}"}])

            if isinstance(parsed, dict):
                return cls.from_dict(parsed, tool_name=tool_name)
            elif len(cls._FIELDS) == 1 and isinstance(parsed, str):
                only_field, (ftype, _) = next(iter(cls._FIELDS.items()))
                if ftype is str:
                    return cls.from_dict({only_field: parsed}, tool_name=tool_name)
            raise SchemaViolationError(tool_name, [{"field": "root", "reason": f"Expected JSON dictionary payload, got {type(parsed).__name__}"}])

        raise SchemaViolationError(tool_name, [{"field": "root", "reason": f"Unsupported argument type {type(raw).__name__}"}])

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if not k.startswith("_")}


@dataclass
class CalcParams(ToolParamSchema):
    expression: str
    _FIELDS = {"expression": (str, True)}


@dataclass
class CountWordsParams(ToolParamSchema):
    text: str
    _FIELDS = {"text": (str, True)}


@dataclass
class ConvertUnitsParams(ToolParamSchema):
    query: str
    _FIELDS = {"query": (str, True)}


@dataclass
class RememberParams(ToolParamSchema):
    key: str
    value: str
    _FIELDS = {"key": (str, True), "value": (str, True)}


@dataclass
class RecallParams(ToolParamSchema):
    key: str | None = ""
    _FIELDS = {"key": ((str, type(None)), False)}
    _ALLOW_EMPTY_PAYLOAD = True


@dataclass
class WriteFileParams(ToolParamSchema):
    path: str
    content: str
    _FIELDS = {"path": (str, True), "content": (str, True)}


@dataclass
class ReadFileParams(ToolParamSchema):
    path: str
    start_line: int | None = None
    end_line: int | None = None
    _FIELDS = {
        "path": (str, True),
        "start_line": ((int, type(None)), False),
        "end_line": ((int, type(None)), False),
    }


@dataclass
class ListFilesParams(ToolParamSchema):
    path: str | None = None
    _FIELDS = {"path": ((str, type(None)), False)}
    _ALLOW_EMPTY_PAYLOAD = True


@dataclass
class ReadUrlParams(ToolParamSchema):
    url: str
    _FIELDS = {"url": (str, True)}


@dataclass
class RunCommandParams(ToolParamSchema):
    command: str
    _FIELDS = {"command": (str, True)}


@dataclass
class PythonReplParams(ToolParamSchema):
    code: str
    _FIELDS = {"code": (str, True)}


@dataclass
class WebSearchParams(ToolParamSchema):
    query: str
    _FIELDS = {"query": (str, True)}


@dataclass
class TimeParams(ToolParamSchema):
    _FIELDS = {}
    _ALLOW_EMPTY_PAYLOAD = True


@dataclass
class HelpParams(ToolParamSchema):
    _FIELDS = {}
    _ALLOW_EMPTY_PAYLOAD = True


TOOL_SCHEMA_MAP: dict[str, type[ToolParamSchema]] = {
    "calc": CalcParams,
    "time": TimeParams,
    "count words": CountWordsParams,
    "convert units": ConvertUnitsParams,
    "remember": RememberParams,
    "recall": RecallParams,
    "help": HelpParams,
    "write_file": WriteFileParams,
    "read_file": ReadFileParams,
    "list_files": ListFilesParams,
    "read_url": ReadUrlParams,
    "run_command": RunCommandParams,
    "python_repl": PythonReplParams,
    "web_search": WebSearchParams,
}


def get_schema_for_tool(tool_name: str) -> type[ToolParamSchema] | None:
    return TOOL_SCHEMA_MAP.get(tool_name)


def validate_tool_args(tool_name: str, args_input: Any) -> ToolParamSchema:
    schema_cls = get_schema_for_tool(tool_name)
    if not schema_cls:
        if isinstance(args_input, dict):
            return args_input
        if isinstance(args_input, str):
            try:
                return json.loads(args_input)
            except Exception:
                return {"raw": args_input}
        return args_input
    return schema_cls.from_json(args_input, tool_name=tool_name)


@dataclass
class OutputSpec:
    target_file: str
    spec_type: str = "repl_template"  # "repl_template" | "repl_variable" | "repl_expr" | "text"
    source_variable: str | None = None
    eval_expr: str | None = None
    template: dict[str, Any] | None = None
    indent: int = 2

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OutputSpec":
        target_file = str(data.get("target_file") or data.get("path") or data.get("file") or "output.json")
        spec_type = str(data.get("spec_type") or data.get("type") or "repl_template")
        source_variable = data.get("source_variable") or data.get("variable") or data.get("var")
        eval_expr = data.get("eval_expr") or data.get("expr") or data.get("expression")
        template = data.get("template")
        indent = int(data.get("indent", 2))
        return cls(
            target_file=target_file,
            spec_type=spec_type,
            source_variable=source_variable,
            eval_expr=eval_expr,
            template=template,
            indent=indent
        )


@dataclass
class PipelineStep:
    step_id: str
    objective: str
    specialist: str = "general"
    tool_allowlist: list[str] | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    inputs_from_step: str | None = None
    inputs_from_steps: list[str] = field(default_factory=list)
    verification_criteria: list[dict[str, Any]] = field(default_factory=list)
    output_spec: OutputSpec | None = None
    max_retries: int = 2
    max_steps: int | None = None
    state_exports: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any], default_id: str = "step_1") -> "PipelineStep":
        step_id = str(data.get("step_id") or data.get("id") or default_id)
        objective = str(data.get("objective") or data.get("prompt") or data.get("goal") or data.get("task") or "")
        specialist = str(data.get("specialist") or data.get("agent") or "general")
        tool_allowlist = data.get("tool_allowlist") or data.get("tools")
        if isinstance(tool_allowlist, str):
            tool_allowlist = [t.strip() for t in tool_allowlist.split(",") if t.strip()]
        inputs = data.get("inputs") or {}
        inputs_from_step = data.get("inputs_from_step")
        inputs_from_steps = data.get("inputs_from_steps") or []
        if isinstance(inputs_from_steps, str):
            inputs_from_steps = [inputs_from_steps]
        if inputs_from_step and inputs_from_step not in inputs_from_steps:
            inputs_from_steps = [str(inputs_from_step), *inputs_from_steps]
        if not isinstance(inputs_from_steps, list) or not all(isinstance(step, str) and step.strip() for step in inputs_from_steps):
            raise ValueError("Pipeline step inputs_from_steps must contain non-empty step IDs")
        
        raw_crit = data.get("verification_criteria") or data.get("verification") or []
        if isinstance(raw_crit, dict):
            raw_crit = [raw_crit]
        elif not isinstance(raw_crit, list):
            raw_crit = []

        raw_spec = data.get("output_spec") or data.get("output_contract") or data.get("output")
        output_spec = OutputSpec.from_dict(raw_spec) if isinstance(raw_spec, dict) else None

        max_retries = int(data.get("max_retries", 2))
        max_steps = int(data["max_steps"]) if "max_steps" in data and data["max_steps"] is not None else None
        state_exports = data.get("state_exports") or []
        if isinstance(state_exports, str):
            state_exports = [name.strip() for name in state_exports.split(",") if name.strip()]
        if not isinstance(state_exports, list) or not all(isinstance(name, str) and name.isidentifier() for name in state_exports):
            raise ValueError("Pipeline step state_exports must contain valid Python identifiers")
        if not 0 <= max_retries <= 5:
            raise ValueError("Pipeline step max_retries must be between 0 and 5")
        if max_steps is not None and not 1 <= max_steps <= 25:
            raise ValueError("Pipeline step max_steps must be between 1 and 25")

        return cls(
            step_id=step_id,
            objective=objective,
            specialist=specialist,
            tool_allowlist=tool_allowlist,
            inputs=inputs,
            inputs_from_step=inputs_from_step,
            inputs_from_steps=inputs_from_steps,
            verification_criteria=raw_crit,
            output_spec=output_spec,
            max_retries=max_retries,
            max_steps=max_steps,
            state_exports=state_exports,
        )


@dataclass
class StructuredPipeline:
    pipeline_id: str
    title: str
    global_context: dict[str, Any] = field(default_factory=dict)
    steps: list[PipelineStep] = field(default_factory=list)
    max_steps: int = 50
    max_time_seconds: float = 900.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StructuredPipeline":
        p_id = str(data.get("pipeline_id") or data.get("task_id") or data.get("id") or "pipeline_1")
        title = str(data.get("title") or data.get("name") or "Structured Pipeline")
        global_context = data.get("global_context") or data.get("context") or {}
        max_steps = int(data.get("max_steps", 50))
        max_time_seconds = float(data.get("max_time_seconds", 900.0))
        if not 1 <= max_steps <= 200:
            raise ValueError("Pipeline max_steps must be between 1 and 200")
        if not 1 <= max_time_seconds <= 3600:
            raise ValueError("Pipeline max_time_seconds must be between 1 and 3600")
        
        raw_steps = data.get("pipeline") or data.get("steps") or []
        steps = [
            PipelineStep.from_dict(s, default_id=f"step_{i}")
            for i, s in enumerate(raw_steps, 1)
            if isinstance(s, dict)
        ]
        return cls(
            pipeline_id=p_id,
            title=title,
            global_context=global_context,
            steps=steps,
            max_steps=max_steps,
            max_time_seconds=max_time_seconds,
        )
