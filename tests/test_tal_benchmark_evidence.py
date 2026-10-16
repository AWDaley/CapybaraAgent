"""No text-only 'success' may satisfy a state or saga oracle."""

import hashlib
import json
from pathlib import Path

from tal.benchmark import AcceptanceOracle, BenchmarkSuite
from tal.benchmark_evidence import collect_benchmark_evidence, verify_distributed_saga
from tal_test_report import RunMetrics
from tools.external_tools import get_repl_globals, reset_repl_globals


def test_v2_suite_has_four_machine_checkable_cases():
    with open("benchmarks/slm_v2.json", encoding="utf-8") as handle:
        suite = BenchmarkSuite.from_dict(json.load(handle))
    assert suite.version == "v2"
    assert len(suite.cases) == 4
    assert all(case.oracle is not None for case in suite.cases)
    assert any(case.oracle.artifact_verifier == "distributed_saga_v1" for case in suite.cases)


def test_real_observed_repl_value_required_even_when_answer_is_plausible(tmp_path):
    reset_repl_globals()
    try:
        values = [n * n for n in range(1, 11)]
        get_repl_globals()["benchmark_numbers"] = values
        observed, files = collect_benchmark_evidence(str(tmp_path), ("benchmark_numbers",), ())
        oracle = AcceptanceOracle.from_dict({
            "final_contains_all": ["10", "100"],
            "state_equals": {"benchmark_numbers": values},
        })
        assert files == {}
        assert oracle.evaluate(RunMetrics(
            success=True, final_answer="10 values; final is 100", observed_state=observed,
        ))
        assert not oracle.evaluate(RunMetrics(
            success=True, final_answer="10 values; final is 100",
        ))
        observed["benchmark_numbers"][-1] = 999
        assert not oracle.evaluate(RunMetrics(
            success=True, final_answer="10 values; final is 100", observed_state=observed,
        ))
    finally:
        reset_repl_globals()


def test_data_transformation_requires_exact_contents():
    oracle = AcceptanceOracle.from_dict({
        "state_equals": {"benchmark_summary": {"total": 20, "average": 5.0}},
    })
    assert oracle.evaluate(RunMetrics(
        success=True, observed_state={"benchmark_summary": {"total": 20, "average": 5.0}},
    ))
    assert not oracle.evaluate(RunMetrics(
        success=True, observed_state={"benchmark_summary": {"total": 20, "average": 5.5}},
    ))


def _saga_fixture():
    names = [
        "API_GATEWAY", "ORDER_SVC", "INVENTORY_SVC", "PAYMENT_SVC", "SHIPPING_SVC",
        "NOTIFY_SVC", "ORDER_DB", "INVENTORY_DB", "PAYMENT_LEDGER", "EVENT_BUS",
        "SAGA_ORCHESTRATOR", "AUDIT_STORE",
    ]
    order_ids = ["ORD-2001", "ORD-2002", "ORD-2003", "ORD-2004", "ORD-2005"]
    amounts = [125.50, 80.00, 240.75, 19.99, 510.25]
    events = []
    previous_hash = "0" * 64
    for order_id in order_ids:
        types = (
            ["ORDER_ACCEPTED", "INVENTORY_RESERVED", "PAYMENT_FAILED", "INVENTORY_RELEASED",
             "ORDER_CANCELLED", "CUSTOMER_NOTIFIED"]
            if order_id == "ORD-2003"
            else ["ORDER_ACCEPTED", "INVENTORY_RESERVED", "PAYMENT_CAPTURED",
                  "SHIPMENT_CREATED", "CUSTOMER_NOTIFIED"]
        )
        for sequence, event_type in enumerate(types, 1):
            status = ("FAILED" if event_type == "PAYMENT_FAILED"
                      else "COMPENSATED" if event_type in {"INVENTORY_RELEASED", "ORDER_CANCELLED"}
                      else "COMMITTED")
            event_id = ("EVT-2003-PAYMENT-FAIL" if event_type == "PAYMENT_FAILED"
                        else f"EVT-{order_id}-{event_type}-{sequence}")
            event = dict(event_id=event_id, order_id=order_id,
                         event_type=event_type, status=status, sequence=sequence)
            digest = hashlib.sha256((
                previous_hash + json.dumps(event, sort_keys=True, separators=(",", ":"))
            ).encode()).hexdigest()
            event.update(previous_hash=previous_hash, event_hash=digest)
            events.append(event)
            previous_hash = digest
    audit = {
        "services": [{"id": name} for name in names],
        "service_graph": {name: [] for name in names},
        "orders": [{"order_id": key, "amount": value} for key, value in zip(order_ids, amounts)],
        "ledger_events": events,
        "ledger_root_hash": previous_hash,
        "workflow_metrics": dict(total_orders=5, successful_orders=4, cancelled_orders=1,
                                 event_count=26, duplicate_events_ignored=0),
        "integrity_audit": dict(hash_chain_valid=True, sequence_valid=True,
                                business_invariants_valid=True, valid=True,
                                root_hash=previous_hash, event_count=26),
        "recovery_audit": dict(failure_injected=True, duplicate_suppressed=True,
                               recovery_valid=True, duplicate_event_id="EVT-2003-PAYMENT-FAIL",
                               replay_event_count=1, compensation_count=2,
                               recovered_state="CANCELLED"),
    }
    manifest = {
        "release_ready": True,
        "blocking_issues": [],
        "checks": {key: True for key in ("event_count_matches", "order_counts_reconcile",
                                         "root_hash_matches_audit", "integrity_valid",
                                         "recovery_valid", "service_count_matches")},
        "artifact_contract": {
            "json": "saga_execution_audit.json",
            "manifest": "saga_release_manifest.json",
            "report": "saga_execution_report.md",
        },
    }
    report = "\n".join(
        [f"Incident #INC-1107, 26 events, audit root {previous_hash}, "
         "duplicate EVT-2003-PAYMENT-FAIL and INVENTORY_RELEASE, ORDER_CANCELLED."]
        + names + order_ids + list(manifest["artifact_contract"].values())
        + ["All business invariants and crypto checks were independently recomputed."] * 30
    )
    return audit, manifest, report


def test_saga_oracle_validates_actual_artifact_hash_chain(tmp_path):
    audit, manifest, report = _saga_fixture()
    (tmp_path / "saga_execution_audit.json").write_text(json.dumps(audit), encoding="utf-8")
    (tmp_path / "saga_release_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "saga_execution_report.md").write_text(report, encoding="utf-8")
    paths = ("saga_execution_audit.json", "saga_release_manifest.json", "saga_execution_report.md")
    _, observed = collect_benchmark_evidence(str(tmp_path), (), paths)
    assert verify_distributed_saga(observed)
    oracle = AcceptanceOracle.from_dict({"artifact_verifier": "distributed_saga_v1"})
    assert oracle.evaluate(RunMetrics(success=True, observed_artifacts=observed))
    assert not oracle.evaluate(RunMetrics(success=True, final_answer="Verified saga!"))
    audit["ledger_events"][12]["event_type"] = "PAYMENT_CAPTURED"  # overwrite failed payment
    (tmp_path / paths[0]).write_text(json.dumps(audit), encoding="utf-8")
    _, tampered = collect_benchmark_evidence(str(tmp_path), (), paths)
    assert not oracle.evaluate(RunMetrics(success=True, observed_artifacts=tampered))
    assert not verify_distributed_saga({**observed, paths[0]: {
        **observed[paths[0]], "content": observed[paths[0]]["content"] + "malicious",
    }})


def test_snapshot_rejects_oversized_and_non_json_values(tmp_path):
    reset_repl_globals()
    try:
        state = get_repl_globals()
        state["big_result"] = "x" * (128 * 1024)
        state["non_json"] = object()
        copied, _ = collect_benchmark_evidence(str(tmp_path), ("big_result", "non_json"), ())
        assert copied == {}
        (tmp_path / "large.json").write_bytes(b"x" * (300 * 1024))
        _, artifacts = collect_benchmark_evidence(str(tmp_path), (), ("large.json",))
        assert artifacts == {}
    finally:
        reset_repl_globals()
