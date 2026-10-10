import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class EpistemicState(Enum):
    REPORTED = "reported"      # Unverified external/user claims
    OBSERVED = "observed"      # Direct tool observation (ground truth from sandbox/APIs)
    INFERRED = "inferred"      # Deduced by model reasoning
    ASSUMED = "assumed"        # Tentative working hypothesis under uncertainty
    CONFLICTED = "conflicted"  # Direct contradictory claims detected
    VERIFIED = "verified"      # Independently corroborated / acceptance-tested


@dataclass
class EpistemicFact:
    fact_id: str
    claim: str
    state: EpistemicState
    source: str
    confidence: float = 1.0
    turn_created: int = 0
    turn_verified: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EpistemicFact":
        state_val = data.get("state", "reported")
        if isinstance(state_val, str):
            try:
                state_enum = EpistemicState(state_val)
            except ValueError:
                state_enum = EpistemicState.REPORTED
        else:
            state_enum = state_val
        return cls(
            fact_id=data.get("fact_id", str(uuid.uuid4())[:8]),
            claim=data.get("claim", ""),
            state=state_enum,
            source=data.get("source", "unknown"),
            confidence=float(data.get("confidence", 1.0)),
            turn_created=int(data.get("turn_created", 0)),
            turn_verified=data.get("turn_verified"),
            metadata=data.get("metadata", {})
        )


class EpistemicStore:
    """Manages working memory facts with explicit epistemic provenance."""
    def __init__(self):
        self.facts: dict[str, EpistemicFact] = {}
        self.conflict_pairs: list[tuple[str, str, str]] = []  # (fact1_id, fact2_id, reason)

    def add_fact(self, claim: str, state: EpistemicState = EpistemicState.REPORTED,
                 source: str = "user", confidence: float = 1.0,
                 turn: int = 0, fact_id: str | None = None,
                 metadata: dict[str, Any] | None = None) -> str:
        """Adds a fact or updates state if existing claim found."""
        fid = fact_id or str(uuid.uuid4())[:8]
        fact = EpistemicFact(
            fact_id=fid,
            claim=claim.strip(),
            state=state,
            source=source,
            confidence=confidence,
            turn_created=turn,
            metadata=metadata or {}
        )
        self.facts[fid] = fact
        return fid

    def get_fact(self, fact_id: str) -> EpistemicFact | None:
        return self.facts.get(fact_id)

    def promote(self, fact_id: str, new_state: EpistemicState, source: str = "", turn: int | None = None) -> bool:
        """Promotes or transitions a fact's epistemic state."""
        fact = self.facts.get(fact_id)
        if not fact:
            return False
        fact.state = new_state
        if source:
            fact.source = f"{fact.source} -> {source}"
        if new_state == EpistemicState.VERIFIED and turn is not None:
            fact.turn_verified = turn
        return True

    def mark_conflicted(self, fact_id_1: str, fact_id_2: str, reason: str = "") -> None:
        """Marks two facts as conflicted."""
        f1 = self.facts.get(fact_id_1)
        f2 = self.facts.get(fact_id_2)
        if f1: f1.state = EpistemicState.CONFLICTED
        if f2: f2.state = EpistemicState.CONFLICTED
        self.conflict_pairs.append((fact_id_1, fact_id_2, reason))

    def get_facts_by_state(self, state: EpistemicState) -> list[EpistemicFact]:
        return [f for f in self.facts.values() if f.state == state]

    def get_all(self) -> list[EpistemicFact]:
        return list(self.facts.values())

    def get_verified(self) -> list[EpistemicFact]:
        return self.get_verified_facts()

    def get_verified_facts(self) -> list[EpistemicFact]:
        return [f for f in self.facts.values() if f.state == EpistemicState.VERIFIED]

    def detect_conflicts(self) -> list[tuple[EpistemicFact, EpistemicFact]]:
        conflicts = []
        for fid1, fid2, _ in self.conflict_pairs:
            if fid1 in self.facts and fid2 in self.facts:
                conflicts.append((self.facts[fid1], self.facts[fid2]))
        return conflicts

    def to_context_string(self, max_facts: int = 20, filter_states: set[EpistemicState] | None = None) -> str:
        """Builds a formatted summary string of facts for model prompting."""
        if not self.facts:
            return ""

        lines = ["Epistemic Facts (Grounding & Provenance):"]
        count = 0
        for fact in self.facts.values():
            if filter_states and fact.state not in filter_states:
                continue
            lines.append(f"- [{fact.state.value.upper()}] {fact.claim} (source: {fact.source})")
            count += 1
            if count >= max_facts:
                break

        if len(lines) == 1:
            return ""
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "facts": {k: v.to_dict() for k, v in self.facts.items()},
            "conflicts": self.conflict_pairs,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EpistemicStore":
        store = cls()
        facts_data = data.get("facts", {})
        for fid, fdict in facts_data.items():
            store.facts[fid] = EpistemicFact.from_dict(fdict)
        store.conflict_pairs = data.get("conflicts", [])
        return store
