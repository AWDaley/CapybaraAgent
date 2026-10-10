import pytest

from tal.domain_packs.mobile_private_assistant import MobilePrivateAssistantDomainPack
from tal.mobile_profile import MOBILE_FIXTURE_DIR, load_strict_json
from tal.mobile_simulator import (
    FakeMobileToolRegistry,
    MobileEvent,
    MobileEventStore,
    MobileRuntimeError,
    replay_events,
)


def _append(store: MobileEventStore, event_type: str, payload: dict[str, object]) -> None:
    store.append(
        event_type,
        payload,
        expected_state_version=store.state.state_version,
        expected_ledger_sequence=store.state.ledger_sequence,
    )


def test_document_answer_replay_fixture_is_deterministic() -> None:
    fixture = load_strict_json(MOBILE_FIXTURE_DIR / "document-answer-replay.json")
    store = MobileEventStore(fixture["run_id"], fixture["manifest_hash"])
    for instruction in fixture["events"]:
        _append(store, instruction["event_type"], instruction["payload"])

    replayed = store.replay()
    expected = fixture["expected_state"]
    assert replayed.ledger_sequence == expected["ledger_sequence"]
    assert replayed.state_version == expected["state_version"]
    assert replayed.phase == expected["phase"]
    assert list(replayed.observations) == expected["observations"]
    assert replayed.terminal_outcome == expected["terminal_outcome"]
    assert replayed.canonical_projection() == store.state.canonical_projection()


def test_stale_append_and_reused_effect_key_fail_closed() -> None:
    store = MobileEventStore("run:idempotency-1", "sha256:" + "1" * 64)
    _append(store, "manifest.created", {})
    with pytest.raises(MobileRuntimeError, match="obsolete state"):
        store.append("manifest.validated", {}, expected_state_version=0, expected_ledger_sequence=1)

    _append(store, "manifest.validated", {})
    _append(store, "tool.intent_recorded", {"idempotency_key": "effect:once", "semantic_fingerprint": "sha256:first"})
    _append(store, "tool.succeeded", {"idempotency_key": "effect:once"})
    with pytest.raises(MobileRuntimeError) as error:
        _append(store, "tool.intent_recorded", {"idempotency_key": "effect:once", "semantic_fingerprint": "sha256:first"})
    assert error.value.code == "IDEMPOTENCY_CONFLICT"


def test_process_restore_preserves_uncertain_effect_for_reconciliation() -> None:
    store = MobileEventStore("run:restore-1", "sha256:" + "2" * 64)
    _append(store, "manifest.created", {})
    _append(store, "manifest.validated", {})
    _append(store, "tool.intent_recorded", {"idempotency_key": "effect:pending", "semantic_fingerprint": "sha256:pending"})
    _append(store, "lifecycle.process_restored", {})

    assert store.state.phase == "waiting_for_tool"
    assert store.state.pending_effect_key == "effect:pending"
    assert store.replay().canonical_projection() == store.state.canonical_projection()


def test_local_only_fake_registry_rejects_network_path() -> None:
    with pytest.raises(MobileRuntimeError) as error:
        FakeMobileToolRegistry().execute("cloud_model.request", {})
    assert error.value.code == "NETWORK_MODE_PROHIBITS"


def test_stale_approval_and_permission_revocation_are_safe_runtime_states() -> None:
    store = MobileEventStore("run:approval-1", "sha256:" + "3" * 64)
    _append(store, "manifest.created", {})
    _append(store, "manifest.validated", {})
    _append(store, "approval.requested", {"approval_id": "approval:one"})
    with pytest.raises(MobileRuntimeError) as error:
        _append(store, "approval.granted", {"approval_id": "approval:stale"})
    assert error.value.code == "APPROVAL_STALE"
    _append(store, "lifecycle.permission_revoked", {})
    assert store.state.phase == "waiting_for_information"
    assert store.state.pending_approval_id == "approval:one"


def test_corrupted_replay_sequence_is_rejected() -> None:
    corrupted = MobileEvent(
        event_id="event:000002",
        run_id="run:corrupt-1",
        sequence=2,
        state_version=1,
        event_type="manifest.created",
    )
    with pytest.raises(MobileRuntimeError) as error:
        replay_events("run:corrupt-1", "sha256:" + "4" * 64, [corrupted])
    assert error.value.code == "STALE_STATE_VERSION"


def test_completion_terminal_event_matches_kotlin_reducer() -> None:
    store = MobileEventStore("run:completed-event", "sha256:" + "5" * 64)
    _append(store, "manifest.created", {})
    _append(store, "manifest.validated", {})
    _append(store, "completion.proposed", {})
    _append(store, "completion.verified", {"outcome": "answer_delivered"})
    _append(store, "run.completed", {})
    assert store.state.phase == "completed"
    assert store.state.terminal_outcome == "answer_delivered"


def test_private_assistant_domain_pack_exposes_only_local_mvp_tools() -> None:
    assert MobilePrivateAssistantDomainPack.controlled_vocabulary["network_mode"] == "local_only"
    assert set(MobilePrivateAssistantDomainPack.tools) == {
        "document.selected.read",
        "image.selected.inspect",
        "vault.search",
        "draft.create",
        "note.create",
        "task.create_local",
    }
