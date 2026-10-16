from dataclasses import dataclass
from typing import Any

from .capability import CapabilityEnvelope
from .context_packer import PHASE_TOOL_ALLOWLIST, ExecutionPhase
from .effect_classes import ApprovalPolicy, get_approval_policy, get_effect_class
from .proposal_types import ActionProposal
from .schemas import SchemaViolationError, validate_tool_args
from .safe_paths import resolve_workspace_path


@dataclass
class GateResult:
    allowed: bool
    stage_failed: str | None = None
    reason: str = ""
    requires_approval: bool = False
    sanitized_args: dict[str, Any] | None = None


class ActionGate:
    """
    Deterministic 5-stage validation pipeline:
    1. Schema Conformance (Closed schemas, typed arguments)
    2. Capability Clearance (Effective permission envelope)
    3. Effect Boundary Check (Phase-appropriate effect classification)
    4. Parameter Sanitization (Path sandbox traversal & shell/AST safety checks)
    5. Approval Determination (Human-in-the-Loop policy check)
    """

    def evaluate(
        self,
        proposal: ActionProposal,
        capabilities: CapabilityEnvelope,
        phase: ExecutionPhase | None = None,
        session_state: Any | None = None
    ) -> GateResult:
        tool_name = proposal.tool_name
        raw_args = proposal.tool_args

        # Stage 1: Model-specified arguments only; missing targets must fail
        # schema validation rather than silently selecting a user's newest file.
        try:
            validated_schema = validate_tool_args(tool_name, raw_args)
            sanitized_dict = validated_schema.to_dict() if hasattr(validated_schema, "to_dict") else validated_schema
        except SchemaViolationError as err:
            return GateResult(
                allowed=False, stage_failed="Stage 1: Schema Conformance", reason=str(err)
            )
        except Exception as err:
            return GateResult(
                allowed=False, stage_failed="Stage 1: Schema Conformance",
                reason=f"Failed to parse tool parameters: {err}"
            )

        # Stage 2: Capability Clearance
        if not capabilities.is_permitted(tool_name):
            denial_reasons = [d["reason"] for d in capabilities.denied if d.get("capability") == tool_name]
            reason_suffix = f" ({denial_reasons[0]})" if denial_reasons else ""
            return GateResult(
                allowed=False,
                stage_failed="Stage 2: Capability Clearance",
                reason=f"Tool '{tool_name}' is denied by the capability policy{reason_suffix}"
            )

        # Stage 3: Effect Boundary Check
        if phase is not None:
            allowed_phase_tools = PHASE_TOOL_ALLOWLIST.get(phase)
            if allowed_phase_tools is not None and tool_name not in allowed_phase_tools:
                return GateResult(
                    allowed=False,
                    stage_failed="Stage 3: Effect Boundary Check",
                    reason=f"Tool '{tool_name}' (Effect: {get_effect_class(tool_name).value}) is not permitted in phase {phase.value}"
                )

        # Stage 4: Parameter Sanitization
        if isinstance(sanitized_dict, dict):
            # Revalidate the actual workspace path before granting an effect.
            if "path" in sanitized_dict:
                try:
                    from tools.file_tools import WORKSPACE_DIR
                    resolve_workspace_path(WORKSPACE_DIR, str(sanitized_dict["path"]))
                except ValueError as exc:
                    return GateResult(
                        allowed=False,
                        stage_failed="Stage 4: Parameter Sanitization",
                        reason=f"Path traversal detected: {exc}",
                    )

            # Shell command sanitization
            if tool_name == "run_command" and "command" in sanitized_dict:
                cmd_val = str(sanitized_dict["command"])
                disallowed_chars = {'&', '|', ';', '$', '`', '>', '<', '\n', '\r'}
                if any(c in cmd_val for c in disallowed_chars):
                    return GateResult(
                        allowed=False,
                        stage_failed="Stage 4: Parameter Sanitization",
                        reason="Disallowed shell metacharacters detected in command"
                    )

            # Python REPL AST safety check
            if tool_name == "python_repl" and "code" in sanitized_dict:
                from tools.external_tools import _check_code_safety
                safety_err = _check_code_safety(sanitized_dict["code"])
                if safety_err:
                    guidance = ""
                    if "'type'" in safety_err:
                        guidance = " Use isinstance(value, ExpectedType) or print explicit values instead."
                    elif "'globals'" in safety_err or "'locals'" in safety_err or "'vars'" in safety_err:
                        guidance = " Reference the expected variable directly; namespace introspection is not available."
                    elif "'dir'" in safety_err:
                        guidance = " Verify known fields or keys explicitly rather than enumerating attributes."
                    return GateResult(
                        allowed=False,
                        stage_failed="Stage 4: Parameter Sanitization",
                        reason=safety_err + guidance
                    )

        # Stage 5: Approval Determination
        policy = get_approval_policy(tool_name)
        requires_approval = (policy == ApprovalPolicy.CONFIRM)

        return GateResult(
            allowed=True,
            stage_failed=None,
            reason="Action cleared by validation pipeline",
            requires_approval=requires_approval,
            sanitized_args=sanitized_dict
        )
