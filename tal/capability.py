from dataclasses import dataclass, field
from typing import Any


@dataclass
class CapabilityEnvelope:
    """Enforces the capability boundary (requested vs. effective vs. denied)."""
    requested: set[str] = field(default_factory=set)
    effective: set[str] = field(default_factory=set)
    denied: list[dict[str, str]] = field(default_factory=list)  # [{"capability": "...", "reason": "..."}]

    def is_permitted(self, tool_name: str) -> bool:
        return tool_name in self.effective

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested": sorted(list(self.requested)),
            "effective": sorted(list(self.effective)),
            "denied": self.denied,
        }

    def to_context_string(self) -> str:
        effective_str = ", ".join(sorted(self.effective)) if self.effective else "None"
        res = f"Effective Capabilities: [{effective_str}]"
        if self.denied:
            denied_parts = [f"{d.get('capability', 'unknown')} ({d.get('reason', 'policy')})" for d in self.denied]
            res += f"\nDenied Capabilities: {', '.join(denied_parts)}"
        return res


def compute_envelope(
    requested_tools: Any | None = None,
    available_tools: dict[str, Any] | None = None,
    policy_denials: dict[str, str] | None = None
) -> CapabilityEnvelope:
    """
    Computes effective capabilities by intersecting requested tools with available tools
    and applying policy denials.
    """
    all_avail = set(available_tools.keys()) if available_tools else set()
    
    if requested_tools is None:
        req_set = set(all_avail)
    elif isinstance(requested_tools, (list, tuple, set)):
        req_set = set(requested_tools)
    else:
        req_set = {str(requested_tools)}

    policy_denials = policy_denials or {}
    effective = set()
    denied = []

    for tool in req_set:
        if tool in policy_denials:
            denied.append({"capability": tool, "reason": policy_denials[tool]})
        elif tool in all_avail:
            effective.add(tool)
        else:
            denied.append({"capability": tool, "reason": "Tool not available in environment"})

    return CapabilityEnvelope(
        requested=req_set,
        effective=effective,
        denied=denied
    )
