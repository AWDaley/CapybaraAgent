import json
import os
import tempfile
import textwrap

import tools.file_tools
from tal.pipeline_runner import StructuredPipelineRunner
from tal.schemas import StructuredPipeline


class ScriptedLLM:
    model = "scripted-test"
    provider = "test"

    def __init__(self, responses):
        self.responses = list(responses)

    def generate_with_retry(self, messages, json_mode=False, callback=None, deadline=None):
        response = self.responses.pop(0) if self.responses else json.dumps({
            "thought": "script exhausted",
            "action": None,
            "final_answer": "script exhausted",
        })
        if callback:
            callback(response)
        return response


def _action(tool, args):
    return json.dumps({
        "thought": f"use {tool}",
        "action": {"tool": tool, "args": args},
        "final_answer": None,
    })


def test_distributed_saga_pipeline_runs_all_steps_and_materializes_artifacts():
    from tools.external_tools import reset_repl_globals

    reset_repl_globals()
    pipeline_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "distributed_saga_recovery_pipeline.json"
    )
    with open(pipeline_path, "r", encoding="utf-8") as handle:
        pipeline = StructuredPipeline.from_dict(json.load(handle))

    service_nodes = [
        {"id": "API_GATEWAY", "zone": "EDGE", "criticality": "high"},
        {"id": "ORDER_SVC", "zone": "TRANSACTION", "criticality": "critical"},
        {"id": "INVENTORY_SVC", "zone": "TRANSACTION", "criticality": "critical"},
        {"id": "PAYMENT_SVC", "zone": "TRANSACTION", "criticality": "critical"},
        {"id": "SHIPPING_SVC", "zone": "TRANSACTION", "criticality": "high"},
        {"id": "NOTIFY_SVC", "zone": "TRANSACTION", "criticality": "medium"},
        {"id": "ORDER_DB", "zone": "DATA", "criticality": "critical"},
        {"id": "INVENTORY_DB", "zone": "DATA", "criticality": "critical"},
        {"id": "PAYMENT_LEDGER", "zone": "DATA", "criticality": "critical"},
        {"id": "EVENT_BUS", "zone": "PLATFORM", "criticality": "high"},
        {"id": "SAGA_ORCHESTRATOR", "zone": "PLATFORM", "criticality": "critical"},
        {"id": "AUDIT_STORE", "zone": "PLATFORM", "criticality": "high"},
    ]
    service_graph = {
        "API_GATEWAY": ["ORDER_SVC"],
        "ORDER_SVC": ["INVENTORY_SVC", "PAYMENT_SVC", "ORDER_DB", "SAGA_ORCHESTRATOR"],
        "INVENTORY_SVC": ["INVENTORY_DB", "EVENT_BUS"],
        "PAYMENT_SVC": ["PAYMENT_LEDGER", "EVENT_BUS"],
        "SHIPPING_SVC": ["EVENT_BUS"],
        "NOTIFY_SVC": ["EVENT_BUS"],
        "SAGA_ORCHESTRATOR": ["ORDER_SVC", "EVENT_BUS", "AUDIT_STORE"],
        "EVENT_BUS": ["SHIPPING_SVC", "NOTIFY_SVC", "AUDIT_STORE"],
        "ORDER_DB": ["AUDIT_STORE"],
        "INVENTORY_DB": ["AUDIT_STORE"],
        "PAYMENT_LEDGER": ["AUDIT_STORE"],
        "AUDIT_STORE": [],
    }
    step_1_code = f"service_nodes = {service_nodes!r}\nservice_graph = {service_graph!r}"

    step_2_code = textwrap.dedent("""
        import hashlib
        import json
        orders = [
            {'order_id': 'ORD-2001', 'customer': 'C-101', 'amount': 125.50},
            {'order_id': 'ORD-2002', 'customer': 'C-102', 'amount': 80.00},
            {'order_id': 'ORD-2003', 'customer': 'C-103', 'amount': 240.75},
            {'order_id': 'ORD-2004', 'customer': 'C-104', 'amount': 19.99},
            {'order_id': 'ORD-2005', 'customer': 'C-105', 'amount': 510.25},
        ]
        event_order = {
            'ORD-2001': ['ORDER_ACCEPTED', 'INVENTORY_RESERVED', 'PAYMENT_CAPTURED', 'SHIPMENT_CREATED', 'CUSTOMER_NOTIFIED'],
            'ORD-2002': ['ORDER_ACCEPTED', 'INVENTORY_RESERVED', 'PAYMENT_CAPTURED', 'SHIPMENT_CREATED', 'CUSTOMER_NOTIFIED'],
            'ORD-2003': ['ORDER_ACCEPTED', 'INVENTORY_RESERVED', 'PAYMENT_FAILED', 'INVENTORY_RELEASED', 'ORDER_CANCELLED', 'CUSTOMER_NOTIFIED'],
            'ORD-2004': ['ORDER_ACCEPTED', 'INVENTORY_RESERVED', 'PAYMENT_CAPTURED', 'SHIPMENT_CREATED', 'CUSTOMER_NOTIFIED'],
            'ORD-2005': ['ORDER_ACCEPTED', 'INVENTORY_RESERVED', 'PAYMENT_CAPTURED', 'SHIPMENT_CREATED', 'CUSTOMER_NOTIFIED'],
        }
        ledger_events = []
        for order in orders:
            for sequence, event_type in enumerate(event_order[order['order_id']], 1):
                status = 'COMMITTED'
                if event_type == 'PAYMENT_FAILED':
                    status = 'FAILED'
                elif event_type in ('INVENTORY_RELEASED', 'ORDER_CANCELLED'):
                    status = 'COMPENSATED'
                event_id = f"EVT-{order['order_id']}-{event_type}-{sequence}"
                if event_type == 'PAYMENT_FAILED':
                    event_id = 'EVT-2003-PAYMENT-FAIL'
                ledger_events.append({'event_id': event_id, 'order_id': order['order_id'], 'event_type': event_type, 'status': status, 'sequence': sequence})
        previous_hash = '0' * 64
        for event in ledger_events:
            canonical = json.dumps(event, sort_keys=True, separators=(',', ':'))
            event['previous_hash'] = previous_hash
            event['event_hash'] = hashlib.sha256((previous_hash + canonical).encode()).hexdigest()
            previous_hash = event['event_hash']
        ledger_root_hash = previous_hash
        workflow_metrics = {'total_orders': 5, 'successful_orders': 4, 'cancelled_orders': 1, 'event_count': 26, 'duplicate_events_ignored': 0}
    """).strip()

    step_3_code = textwrap.dedent("""
        import hashlib
        import json
        previous_hash = '0' * 64
        hash_chain_valid = True
        sequence_valid = True
        sequence_by_order = {}
        for event in ledger_events:
            expected_sequence = sequence_by_order.get(event['order_id'], 0) + 1
            sequence_by_order[event['order_id']] = expected_sequence
            sequence_valid = sequence_valid and event.get('sequence') == expected_sequence
            payload = {key: value for key, value in event.items() if key not in ('previous_hash', 'event_hash')}
            canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'))
            recomputed = hashlib.sha256((previous_hash + canonical).encode()).hexdigest()
            hash_chain_valid = hash_chain_valid and event.get('previous_hash') == previous_hash and event.get('event_hash') == recomputed
            previous_hash = event.get('event_hash', '')
        order_ids = [event['order_id'] for event in ledger_events]
        failed_types = [event['event_type'] for event in ledger_events if event['order_id'] == 'ORD-2003']
        business_invariants_valid = len(set(order_ids)) == 5 and len(ledger_events) == 26 and failed_types[2:5] == ['PAYMENT_FAILED', 'INVENTORY_RELEASED', 'ORDER_CANCELLED']
        integrity_audit = {'hash_chain_valid': hash_chain_valid, 'sequence_valid': sequence_valid, 'business_invariants_valid': business_invariants_valid, 'valid': hash_chain_valid and sequence_valid and business_invariants_valid, 'event_count': len(ledger_events), 'root_hash': previous_hash, 'checks': ['hash_chain', 'sequence', 'business_invariants']}
    """).strip()

    step_4_code = textwrap.dedent("""
        retry_event = {'event_id': 'EVT-2003-PAYMENT-FAIL', 'order_id': 'ORD-2003', 'event_type': 'PAYMENT_FAILED_REPLAY', 'status': 'IGNORED_DUPLICATE'}
        duplicate_suppressed = retry_event['event_id'] in {event['event_id'] for event in ledger_events}
        compensation_journal = [{'order_id': 'ORD-2003', 'action': 'INVENTORY_RELEASE', 'status': 'APPLIED'}, {'order_id': 'ORD-2003', 'action': 'ORDER_CANCELLED', 'status': 'APPLIED'}]
        recovery_events = list(ledger_events) + [retry_event]
        recovery_audit = {'failure_injected': True, 'duplicate_event_id': 'EVT-2003-PAYMENT-FAIL', 'duplicate_suppressed': duplicate_suppressed, 'replay_event_count': 1, 'compensation_count': len(compensation_journal), 'recovered_state': 'CANCELLED', 'recovery_valid': duplicate_suppressed and len(compensation_journal) == 2 and len(ledger_events) == 26 and 'ORDER_CANCELLED' in [event['event_type'] for event in ledger_events if event['order_id'] == 'ORD-2003']}
    """).strip()

    step_6_code = textwrap.dedent("""
        checks = {'event_count_matches': len(ledger_events) == workflow_metrics['event_count'], 'order_counts_reconcile': workflow_metrics['successful_orders'] + workflow_metrics['cancelled_orders'] == workflow_metrics['total_orders'], 'root_hash_matches_audit': ledger_root_hash == integrity_audit['root_hash'], 'integrity_valid': integrity_audit['valid'] is True, 'recovery_valid': recovery_audit['recovery_valid'] is True, 'service_count_matches': len(service_nodes) == 12, 'order_count_matches': len(orders) == 5}
        blocking_issues = [name for name, passed in checks.items() if not passed]
        release_manifest = {'release_ready': len(blocking_issues) == 0, 'blocking_issues': blocking_issues, 'checks': checks, 'artifact_contract': {'json': 'saga_execution_audit.json', 'manifest': 'saga_release_manifest.json', 'report': 'saga_execution_report.md'}}
    """).strip()

    report_content = "\n".join([
        "# Saga Execution Report",
        "Incident ID: #INC-1107",
        "Scenario: distributed order saga, hash-chain audit, and fault recovery.",
        "Services: " + ", ".join(service_graph),
        "Orders: ORD-2001 $125.50, ORD-2002 $80.00, ORD-2003 $240.75, ORD-2004 $19.99, ORD-2005 $510.25.",
        "Canonical event count: 26. Successful orders: 4. Cancelled orders: 1.",
        "Independent hash-chain and business-invariant checks passed.",
        "Duplicate event EVT-2003-PAYMENT-FAIL was suppressed idempotently.",
        "Compensation actions: INVENTORY_RELEASE and ORDER_CANCELLED.",
        "Release ready: True.",
        "Artifacts: saga_execution_audit.json, saga_release_manifest.json, saga_execution_report.md.",
        "ORD-2003 remains CANCELLED because payment failure triggered compensation; replaying the same event ID cannot charge or reserve inventory again.",
    ]) + "\n" + ("All reconciliation checks remained deterministic and preserved the canonical hash chain.\n" * 30)

    responses = [
        _action('python_repl', {'code': step_1_code}),
        _action('python_repl', {'code': step_2_code}),
        _action('python_repl', {'code': step_3_code}),
        _action('python_repl', {'code': step_4_code}),
        _action('python_repl', {'code': step_6_code}),
        _action('read_file', {'path': 'saga_execution_audit.json'}),
        _action('read_file', {'path': 'saga_release_manifest.json'}),
        _action('write_file', {'path': 'saga_execution_report.md', 'content': report_content}),
        json.dumps({'thought': 'step eight complete', 'action': None, 'final_answer': 'final report complete'}),
    ]

    orig_ws = tools.file_tools.WORKSPACE_DIR
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools.file_tools.WORKSPACE_DIR = tmpdir
            result = StructuredPipelineRunner(
                llm_client=ScriptedLLM(responses),
                workspace_dir=tmpdir,
                verbose=False,
            ).run(pipeline, approval_callback=lambda _tool, _args: True)

            assert result.success is True, (
                result.error or "pipeline failed"
            ) + "\n" + repr(result.step_telemetry) + "\n" + repr(result.tool_calls)
            assert result.steps_passed == len(pipeline.steps) == 8
            assert [telemetry.status for telemetry in result.step_telemetry] == ['passed'] * 8
            assert result.tool_call_count == len(result.tool_calls) == 8
            assert result.tool_error_count == 0

            with open(os.path.join(tmpdir, 'saga_execution_audit.json'), 'r', encoding='utf-8') as handle:
                audit = json.load(handle)
            with open(os.path.join(tmpdir, 'saga_release_manifest.json'), 'r', encoding='utf-8') as handle:
                manifest = json.load(handle)
            with open(os.path.join(tmpdir, 'saga_execution_report.md'), 'r', encoding='utf-8') as handle:
                report = handle.read()

            assert len(audit['services']) == 12
            assert audit['service_graph']['AUDIT_STORE'] == []
            assert len(audit['ledger_events']) == 26
            assert audit['integrity_audit']['valid'] is True
            assert audit['recovery_audit']['recovery_valid'] is True
            assert manifest['release_ready'] is True
            assert len(report) >= 1200
            assert all(service_id in report for service_id in service_graph)
    finally:
        tools.file_tools.WORKSPACE_DIR = orig_ws
