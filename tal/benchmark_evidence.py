"""Independent, bounded observations for synthetic SLM benchmark trials.

No model-provided assertions are evaluated, and no arbitrary Python objects are
serialized. Evidence is sampled from the actual isolated trial workspace.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable

from tal.safe_paths import resolve_workspace_path

_MISSING = object()
_MAX_FILE = 256 * 1024
_MAX_STATE_BYTES = 64 * 1024
_HEX = re.compile(r"^[0-9a-f]{64}$")
_SAGA_ARTIFACTS = (
    "saga_execution_audit.json",
    "saga_release_manifest.json",
    "saga_execution_report.md",
)
_SERVICE_IDS = {
    "API_GATEWAY", "ORDER_SVC", "INVENTORY_SVC", "PAYMENT_SVC",
    "SHIPPING_SVC", "NOTIFY_SVC", "ORDER_DB", "INVENTORY_DB",
    "PAYMENT_LEDGER", "EVENT_BUS", "SAGA_ORCHESTRATOR", "AUDIT_STORE",
}
_ORDER_IDS = ("ORD-2001", "ORD-2002", "ORD-2003", "ORD-2004", "ORD-2005")
_EXPECTED_AMOUNTS = (125.50, 80.00, 240.75, 19.99, 510.25)
_SUCCESS_EVENTS = (
    "ORDER_ACCEPTED", "INVENTORY_RESERVED", "PAYMENT_CAPTURED",
    "SHIPMENT_CREATED", "CUSTOMER_NOTIFIED",
)
_FAILED_EVENTS = (
    "ORDER_ACCEPTED", "INVENTORY_RESERVED", "PAYMENT_FAILED",
    "INVENTORY_RELEASED", "ORDER_CANCELLED", "CUSTOMER_NOTIFIED",
)


def _plain_snapshot(value: Any, depth: int = 0) -> Any:
    """Copy only exact builtin JSON-compatible values (no custom repr/hooks)."""
    if depth > 8:
        return _MISSING
    if value is None or type(value) in (str, bool, int, float):
        return value
    if type(value) is list and len(value) <= 1024:
        items = [_plain_snapshot(item, depth + 1) for item in value]
        return _MISSING if any(item is _MISSING for item in items) else items
    if type(value) is dict and len(value) <= 1024:
        if any(type(key) is not str for key in value):
            return _MISSING
        items = {key: _plain_snapshot(entry, depth + 1) for key, entry in value.items()}
        return _MISSING if any(item is _MISSING for item in items.values()) else items
    return _MISSING


def collect_benchmark_evidence(
    workspace_dir: str, state_keys: tuple[str, ...],
    artifact_paths: tuple[str, ...],
    state_provider: Callable[[], dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Capture selected evidence BEFORE sandbox cleanup, with strict size limits."""
    if state_provider is None:
        from tools.external_tools import get_repl_globals
        state_provider = get_repl_globals

    observed_state: dict[str, Any] = {}
    globals_dict = state_provider()
    for key in state_keys[:16]:
        if not isinstance(key, str) or not key.isidentifier() or key not in globals_dict:
            continue
        copied = _plain_snapshot(globals_dict[key])
        if copied is _MISSING:
            continue
        try:
            payload = json.dumps(copied, allow_nan=False, ensure_ascii=False)
            if len(payload.encode("utf-8")) <= _MAX_STATE_BYTES:
                observed_state[key] = json.loads(payload)
        except (TypeError, ValueError, OverflowError):
            continue

    observed_artifacts: dict[str, dict[str, Any]] = {}
    for relative in artifact_paths[:16]:
        try:
            path = Path(resolve_workspace_path(workspace_dir, relative))
            if not path.is_file() or path.stat().st_size > _MAX_FILE:
                continue
            raw = path.read_bytes()
            if len(raw) > _MAX_FILE:
                continue
            observed_artifacts[relative] = {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
                "content": raw.decode("utf-8"),
            }
        except (OSError, ValueError, UnicodeDecodeError):
            continue
    return observed_state, observed_artifacts


def _read_observed(artifacts: dict[str, dict[str, Any]], name: str) -> str:
    """Check stored bytes and digest before interpreting a claimed artifact."""
    item = artifacts[name]
    content = item["content"]
    if type(content) is not str:
        raise ValueError("Artifact must contain UTF-8 text")
    raw = content.encode("utf-8")
    if not 0 < len(raw) <= _MAX_FILE:
        raise ValueError("Artifact size outside policy")
    if item.get("size") != len(raw) or item.get("sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("Artifact metadata disagrees with observed contents")
    return content


def verify_distributed_saga(artifacts: dict[str, dict[str, Any]]) -> bool:
    """Recalculate the canonical ledger and business invariants from actual files."""
    try:
        audit = json.loads(_read_observed(artifacts, _SAGA_ARTIFACTS[0]))
        manifest = json.loads(_read_observed(artifacts, _SAGA_ARTIFACTS[1]))
        report = _read_observed(artifacts, _SAGA_ARTIFACTS[2])
        if len(report.encode("utf-8")) < 1200:
            return False

        services = audit["services"]
        graph = audit["service_graph"]
        if not isinstance(services, list) or len(services) != 12:
            return False
        if {entry["id"] for entry in services} != _SERVICE_IDS:
            return False
        if set(graph) != _SERVICE_IDS or graph["AUDIT_STORE"] != []:
            return False
        if any(
            not isinstance(targets, list) or
            any(target not in _SERVICE_IDS for target in targets)
            for targets in graph.values()
        ):
            return False

        orders = audit["orders"]
        if len(orders) != 5 or tuple(order["order_id"] for order in orders) != _ORDER_IDS:
            return False
        if any(abs(float(order["amount"]) - expected) > 0.001
               for order, expected in zip(orders, _EXPECTED_AMOUNTS)):
            return False

        events = audit["ledger_events"]
        if not isinstance(events, list) or len(events) != 26:
            return False
        ids: set[str] = set()
        per_order = {order_id: [] for order_id in _ORDER_IDS}
        prior = "0" * 64
        for event in events:
            if not isinstance(event, dict) or event["order_id"] not in per_order:
                return False
            event_id = event["event_id"]
            if not isinstance(event_id, str) or event_id in ids:
                return False
            ids.add(event_id)
            per_order[event["order_id"]].append(event)
            if event["sequence"] != len(per_order[event["order_id"]]):
                return False
            if event["previous_hash"] != prior:
                return False
            # The producer hashes: previous_hash + canonical event excluding
            # both stored link fields (see test_distributed_saga_pipeline.py).
            payload = {k: v for k, v in event.items() if k not in ("previous_hash", "event_hash")}
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            computed = hashlib.sha256((prior + canonical).encode("utf-8")).hexdigest()
            if not _HEX.fullmatch(str(event["event_hash"])) or event["event_hash"] != computed:
                return False
            prior = computed

        for order_id, group in per_order.items():
            types = tuple(event["event_type"] for event in group)
            expected = _FAILED_EVENTS if order_id == "ORD-2003" else _SUCCESS_EVENTS
            if types != expected:
                return False
            for event in group:
                expected_status = (
                    "FAILED" if event["event_type"] == "PAYMENT_FAILED" else
                    "COMPENSATED" if event["event_type"] in ("INVENTORY_RELEASED", "ORDER_CANCELLED") else
                    "COMMITTED"
                )
                if event["status"] != expected_status:
                    return False
        if per_order["ORD-2003"][2]["event_id"] != "EVT-2003-PAYMENT-FAIL":
            return False
        if audit["ledger_root_hash"] != prior:
            return False
        metrics = audit["workflow_metrics"]
        if any(metrics.get(key) != val for key, val in {
            "total_orders": 5, "successful_orders": 4, "cancelled_orders": 1,
            "event_count": 26, "duplicate_events_ignored": 0,
        }.items()):
            return False
        integrity = audit["integrity_audit"]
        if any(integrity.get(key) is not True for key in
               ("hash_chain_valid", "sequence_valid", "business_invariants_valid", "valid")):
            return False
        if integrity.get("root_hash") != prior or integrity.get("event_count") != 26:
            return False
        recovery = audit["recovery_audit"]
        if any(recovery.get(key) is not True for key in
               ("failure_injected", "duplicate_suppressed", "recovery_valid")):
            return False
        if any(recovery.get(key) != val for key, val in {
            "duplicate_event_id": "EVT-2003-PAYMENT-FAIL",
            "replay_event_count": 1, "compensation_count": 2,
            "recovered_state": "CANCELLED",
        }.items()):
            return False
        if manifest.get("release_ready") is not True or manifest.get("blocking_issues") != []:
            return False
        checks = manifest.get("checks", {})
        if not isinstance(checks, dict) or len(checks) < 5 or not all(v is True for v in checks.values()):
            return False
        if manifest.get("artifact_contract") != {
            "json": _SAGA_ARTIFACTS[0],
            "manifest": _SAGA_ARTIFACTS[1],
            "report": _SAGA_ARTIFACTS[2],
        }:
            return False
        required_text = [
            "#INC-1107", "26", prior, "EVT-2003-PAYMENT-FAIL",
            "INVENTORY_RELEASE", "ORDER_CANCELLED", *_SERVICE_IDS, *_ORDER_IDS,
            *_SAGA_ARTIFACTS,
        ]
        return all(item in report for item in required_text)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        return False
