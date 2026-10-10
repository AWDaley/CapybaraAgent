"""Deterministic mobile TAL lifecycle simulator used for conformance fixtures.

It intentionally models only the Android-first local assistant domain. The model and tools are
scripted so lifecycle, authorization, replay, and idempotency behavior can be tested without a
device, network, or real inference runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable


TERMINAL_PHASES = frozenset({"completed", "escalated", "cancelled", "failed"})
STATE_MUTATING_EVENTS = frozenset(
    {
        "manifest.created",
        "manifest.validated",
        "capability.computed",
        "model.proposal_received",
        "proposal.rejected",
        "tool.intent_recorded",
        "tool.succeeded",
        "tool.failed",
        "tool.reconciled",
        "observation.recorded",
        "approval.requested",
        "approval.granted",
        "approval.denied",
        "lifecycle.process_restored",
        "lifecycle.permission_revoked",
        "completion.proposed",
        "completion.verified",
        "run.completed",
        "run.escalated",
        "run.cancelled",
    }
)
LOCAL_ONLY_DENIED_TOOLS = frozenset({"cloud_model.request", "message.send", "calendar.event.create"})


class MobileRuntimeError(RuntimeError):
    """Stable runtime failure carrying the mobile error catalog code."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class MobileEvent:
    event_id: str
    run_id: str
    sequence: int
    state_version: int
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MobileRuntimeState:
    run_id: str
    manifest_hash: str
    ledger_sequence: int = 0
    state_version: int = 0
    phase: str = "created"
    pending_approval_id: str | None = None
    pending_effect_key: str | None = None
    observations: tuple[str, ...] = ()
    terminal_outcome: str | None = None

    def canonical_projection(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "manifest_hash": self.manifest_hash,
            "ledger_sequence": self.ledger_sequence,
            "state_version": self.state_version,
            "phase": self.phase,
            "pending_approval_id": self.pending_approval_id,
            "pending_effect_key": self.pending_effect_key,
            "observations": list(self.observations),
            "terminal_outcome": self.terminal_outcome,
        }


def _transition(state: MobileRuntimeState, event_type: str, payload: dict[str, Any]) -> MobileRuntimeState:
    if state.phase in TERMINAL_PHASES and not (state.phase == "completed" and event_type == "run.completed"):
        raise MobileRuntimeError("INVALID_STATE_TRANSITION", "Terminal mobile run cannot become active")

    phase = state.phase
    pending_approval = state.pending_approval_id
    pending_effect = state.pending_effect_key
    observations = state.observations
    outcome = state.terminal_outcome

    if event_type == "manifest.created":
        if phase != "created":
            raise MobileRuntimeError("INVALID_STATE_TRANSITION", "Manifest may be created only once")
        phase = "validating"
    elif event_type == "manifest.validated":
        if phase != "validating":
            raise MobileRuntimeError("INVALID_STATE_TRANSITION", "Manifest validation requires validating phase")
        phase = "ready"
    elif event_type == "capability.computed":
        if phase != "ready":
            raise MobileRuntimeError("INVALID_STATE_TRANSITION", "Capabilities require ready phase")
    elif event_type == "model.proposal_received":
        if phase != "ready":
            raise MobileRuntimeError("INVALID_STATE_TRANSITION", "Proposal requires ready phase")
        phase = "reasoning"
    elif event_type == "proposal.rejected":
        if phase not in {"ready", "reasoning"}:
            raise MobileRuntimeError("INVALID_STATE_TRANSITION", "Rejection requires an active proposal phase")
        phase = "ready"
    elif event_type == "tool.intent_recorded":
        if phase not in {"ready", "reasoning"}:
            raise MobileRuntimeError("INVALID_STATE_TRANSITION", "Tool intent requires ready or reasoning phase")
        effect_key = payload.get("idempotency_key")
        if not isinstance(effect_key, str) or not effect_key:
            raise MobileRuntimeError("IDEMPOTENCY_CONFLICT", "Tool intent needs a semantic idempotency key")
        pending_effect = effect_key
        phase = "waiting_for_tool"
    elif event_type in {"tool.succeeded", "tool.failed", "tool.reconciled"}:
        if phase != "waiting_for_tool" or not pending_effect:
            raise MobileRuntimeError("INVALID_STATE_TRANSITION", "Tool result requires a pending effect")
        if payload.get("idempotency_key") != pending_effect:
            raise MobileRuntimeError("IDEMPOTENCY_CONFLICT", "Tool result does not match pending effect")
        pending_effect = None
        phase = "ready"
    elif event_type == "observation.recorded":
        observation_id = payload.get("observation_id")
        if not isinstance(observation_id, str) or not observation_id:
            raise MobileRuntimeError("TOOL_OUTPUT_INVALID", "Observation must have an ID")
        if observation_id not in observations:
            observations = observations + (observation_id,)
        phase = "ready"
    elif event_type == "approval.requested":
        if phase not in {"ready", "reasoning"}:
            raise MobileRuntimeError("INVALID_STATE_TRANSITION", "Approval requires active run")
        approval_id = payload.get("approval_id")
        if not isinstance(approval_id, str) or not approval_id:
            raise MobileRuntimeError("APPROVAL_REQUIRED", "Approval request needs an ID")
        pending_approval = approval_id
        phase = "waiting_for_approval"
    elif event_type in {"approval.granted", "approval.denied"}:
        if phase != "waiting_for_approval" or not pending_approval:
            raise MobileRuntimeError("APPROVAL_STALE", "No approval is pending")
        if payload.get("approval_id") != pending_approval:
            raise MobileRuntimeError("APPROVAL_STALE", "Approval does not match pending request")
        pending_approval = None
        phase = "ready" if event_type == "approval.granted" else "waiting_for_information"
    elif event_type == "lifecycle.process_restored":
        if pending_effect:
            phase = "waiting_for_tool"
        elif pending_approval:
            phase = "waiting_for_approval"
    elif event_type == "lifecycle.permission_revoked":
        if phase in {"waiting_for_tool", "waiting_for_approval", "reasoning", "ready"}:
            phase = "waiting_for_information"
    elif event_type == "completion.proposed":
        if phase != "ready":
            raise MobileRuntimeError("INVALID_STATE_TRANSITION", "Completion proposal requires ready phase")
        phase = "verifying"
    elif event_type == "completion.verified":
        if phase != "verifying":
            raise MobileRuntimeError("INVALID_STATE_TRANSITION", "Completion verification requires verifying phase")
        phase = "completed"
        outcome = payload.get("outcome")
        if not isinstance(outcome, str) or not outcome:
            raise MobileRuntimeError("COMPLETION_EVIDENCE_INSUFFICIENT", "Completion needs a terminal outcome")
    elif event_type == "run.completed":
        if phase != "completed":
            raise MobileRuntimeError("INVALID_STATE_TRANSITION", "Run completion requires verified completion")
    elif event_type == "run.escalated":
        phase = "escalated"
        outcome = "escalated"
    elif event_type == "run.cancelled":
        phase = "cancelled"
        outcome = "cancelled"
    else:
        raise MobileRuntimeError("UNKNOWN_FIELD", f"Unsupported mobile event: {event_type}")

    return replace(
        state,
        phase=phase,
        pending_approval_id=pending_approval,
        pending_effect_key=pending_effect,
        observations=observations,
        terminal_outcome=outcome,
    )


def reduce_mobile_event(state: MobileRuntimeState, event: MobileEvent) -> MobileRuntimeState:
    if event.run_id != state.run_id:
        raise MobileRuntimeError("UNRESOLVED_REFERENCE", "Event belongs to another run")
    if event.sequence != state.ledger_sequence + 1:
        raise MobileRuntimeError("STALE_STATE_VERSION", "Event sequence is not contiguous")
    transitioned = _transition(state, event.event_type, event.payload)
    expected_state_version = state.state_version + (1 if event.event_type in STATE_MUTATING_EVENTS else 0)
    if event.state_version != expected_state_version:
        raise MobileRuntimeError("STALE_STATE_VERSION", "Event state version is invalid")
    return replace(
        transitioned,
        ledger_sequence=event.sequence,
        state_version=event.state_version,
    )


class MobileEventStore:
    """In-memory transactional ledger used by the mobile conformance suite."""

    def __init__(self, run_id: str, manifest_hash: str):
        self._state = MobileRuntimeState(run_id=run_id, manifest_hash=manifest_hash)
        self._events: list[MobileEvent] = []
        self._effect_payloads: dict[str, str] = {}

    @property
    def state(self) -> MobileRuntimeState:
        return self._state

    @property
    def events(self) -> tuple[MobileEvent, ...]:
        return tuple(self._events)

    def append(
        self,
        event_type: str,
        payload: dict[str, Any],
        expected_state_version: int,
        expected_ledger_sequence: int,
    ) -> MobileEvent:
        if expected_state_version != self._state.state_version or expected_ledger_sequence != self._state.ledger_sequence:
            raise MobileRuntimeError("STALE_STATE_VERSION", "Append uses an obsolete state or ledger version")
        if event_type == "tool.intent_recorded":
            self._record_effect_intent(payload)
        sequence = self._state.ledger_sequence + 1
        state_version = self._state.state_version + (1 if event_type in STATE_MUTATING_EVENTS else 0)
        event = MobileEvent(
            event_id=f"event:{sequence:06d}",
            run_id=self._state.run_id,
            sequence=sequence,
            state_version=state_version,
            event_type=event_type,
            payload=dict(payload),
        )
        self._state = reduce_mobile_event(self._state, event)
        self._events.append(event)
        return event

    def replay(self) -> MobileRuntimeState:
        state = MobileRuntimeState(run_id=self._state.run_id, manifest_hash=self._state.manifest_hash)
        for event in self._events:
            state = reduce_mobile_event(state, event)
        return state

    def _record_effect_intent(self, payload: dict[str, Any]) -> None:
        key = payload.get("idempotency_key")
        fingerprint = payload.get("semantic_fingerprint")
        if not isinstance(key, str) or not key or not isinstance(fingerprint, str) or not fingerprint:
            raise MobileRuntimeError("IDEMPOTENCY_CONFLICT", "Effect intent needs canonical key and fingerprint")
        prior = self._effect_payloads.get(key)
        if prior is not None and prior != fingerprint:
            raise MobileRuntimeError("IDEMPOTENCY_CONFLICT", "Effect key was reused with different semantics")
        if prior is not None:
            raise MobileRuntimeError("IDEMPOTENCY_CONFLICT", "Effect intent was already recorded")
        self._effect_payloads[key] = fingerprint


@dataclass
class ScriptedMobileModel:
    proposals: list[dict[str, Any]]

    def propose(self, _context: dict[str, Any]) -> dict[str, Any]:
        if not self.proposals:
            raise MobileRuntimeError("MODEL_UNAVAILABLE", "Scripted model has no proposal remaining")
        return self.proposals.pop(0)


class FakeMobileToolRegistry:
    """Local-only fake tool boundary for simulator certification scenarios."""

    def execute(self, tool_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_id in LOCAL_ONLY_DENIED_TOOLS:
            raise MobileRuntimeError("NETWORK_MODE_PROHIBITS", f"{tool_id} is unavailable in local_only mode")
        if tool_id not in {
            "document.selected.read",
            "image.selected.inspect",
            "vault.search",
            "draft.create",
            "note.create",
            "task.create_local",
        }:
            raise MobileRuntimeError("TOOL_NOT_REGISTERED", f"Unknown mobile tool {tool_id}")
        return {"tool_id": tool_id, "arguments": dict(arguments), "success": True}


def replay_events(
    run_id: str,
    manifest_hash: str,
    events: Iterable[MobileEvent],
) -> MobileRuntimeState:
    state = MobileRuntimeState(run_id=run_id, manifest_hash=manifest_hash)
    for event in events:
        state = reduce_mobile_event(state, event)
    return state
