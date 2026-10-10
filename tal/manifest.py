import copy
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

from .budget import BudgetLimits
from .capability import CapabilityEnvelope, compute_envelope


def to_canonical_json(obj: Any) -> str:
    """
    Produces deterministic canonical JSON (RFC 8785 style):
    - Keys sorted recursively
    - Compact delimiters (no extra spaces)
    - Deterministic float/int formatting
    """
    def _normalize(item: Any) -> Any:
        if isinstance(item, dict):
            return {k: _normalize(item[k]) for k in sorted(item.keys())}
        elif isinstance(item, (list, tuple)):
            return [_normalize(x) for x in item]
        elif isinstance(item, set):
            return [_normalize(x) for x in sorted(list(item))]
        return item

    normalized = _normalize(obj)
    return json.dumps(normalized, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


@dataclass(frozen=True)
class TaskManifest:
    """Immutable, content-hashed contract for a task execution run.

    The hash excludes run metadata (identifier and timestamp), so the same
    declared task always produces the same policy contract.
    """
    manifest_id: str
    tal_version: str
    goal: str
    created_at: float
    capabilities: CapabilityEnvelope
    budget: BudgetLimits
    verification_criteria: list[dict[str, Any]]
    manifest_hash: str = ""

    def to_canonical_json(self) -> str:
        d = {
            "tal_version": self.tal_version,
            "goal": self.goal,
            "capabilities": self.capabilities.to_dict(),
            "budget": {
                "max_steps": self.budget.max_steps,
                "max_time_seconds": self.budget.max_time_seconds,
                "max_tool_errors": self.budget.max_tool_errors,
                "max_repair_attempts": self.budget.max_repair_attempts,
            },
            "verification_criteria": self.verification_criteria,
        }
        return to_canonical_json(d)

    def compute_hash(self) -> str:
        canonical = self.to_canonical_json()
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

    def verify_integrity(self) -> bool:
        """Return whether the embedded hash still matches the declared contract."""
        return bool(self.manifest_hash) and self.compute_hash() == self.manifest_hash

    @classmethod
    def compile(
        cls,
        goal: str,
        available_tools: dict[str, Any] | None = None,
        requested_tools: list[str] | None = None,
        budget_limits: BudgetLimits | None = None,
        verification_criteria: list[dict[str, Any]] | None = None,
        policy_denials: dict[str, str] | None = None
    ) -> "TaskManifest":
        """
        Deterministic form-to-manifest compiler:
        Transforms raw goal + policies into a frozen, hashed manifest contract.
        """
        manifest_id = ""
        now = round(time.time(), 3)
        caps = compute_envelope(
            requested_tools=requested_tools,
            available_tools=available_tools,
            policy_denials=policy_denials
        )
        # Take snapshots so mutable caller state cannot silently change the
        # contract after it has been signed.
        limits = copy.deepcopy(budget_limits) if budget_limits else BudgetLimits()
        criteria = copy.deepcopy(verification_criteria or [])
        caps = copy.deepcopy(caps)

        provisional = cls(
            manifest_id=manifest_id,
            tal_version="1.0",
            goal=goal.strip(),
            created_at=now,
            capabilities=caps,
            budget=limits,
            verification_criteria=criteria,
            manifest_hash=""
        )
        manifest_hash = provisional.compute_hash()
        return cls(
            manifest_id=f"man_{manifest_hash[:12]}",
            tal_version=provisional.tal_version,
            goal=provisional.goal,
            created_at=provisional.created_at,
            capabilities=provisional.capabilities,
            budget=provisional.budget,
            verification_criteria=provisional.verification_criteria,
            manifest_hash=manifest_hash,
        )
