import json
import os
import tempfile

import pytest

from tal.event_store import EventLog
from tal.trace_dataset import TraceDataset, sanitize_trace_value


def test_trace_dataset_accepts_verified_production_trace_and_redacts_secret():
    log = EventLog()
    log.append("tool_executed", {"tool": "read_file", "args": "token=very-secret", "result": "ok"})
    dataset = TraceDataset("slm_verified_v1")

    example = dataset.add_event_log(log, verified_success=True, metadata={"api_key": "abc123"})

    serialized = example.to_dict()
    assert "very-secret" not in json.dumps(serialized)
    assert "abc123" not in json.dumps(serialized)
    assert serialized["verified_success"] is True


def test_trace_dataset_quarantines_unverified_and_benchmark_data():
    log = EventLog()
    dataset = TraceDataset("slm_verified_v1")
    with pytest.raises(ValueError, match="verified-success"):
        dataset.add_event_log(log, verified_success=False)
    with pytest.raises(ValueError, match="quarantined"):
        dataset.add_event_log(log, verified_success=True, source_kind="benchmark")


def test_trace_dataset_deduplicates_and_saves_jsonl():
    log = EventLog()
    log.append("task_completed", {"answer": "done"})
    dataset = TraceDataset("slm_verified_v1")
    first = dataset.add_event_log(log, verified_success=True)
    second = dataset.add_event_log(log, verified_success=True)
    assert first.trace_id == second.trace_id
    assert len(dataset.examples) == 1
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "traces.jsonl")
        dataset.save_jsonl(path)
        with open(path, encoding="utf-8") as handle:
            assert json.loads(handle.readline())["trace_id"] == first.trace_id


def test_sanitize_trace_value_limits_text():
    assert "[REDACTED]" in sanitize_trace_value("password: hidden")
    assert len(sanitize_trace_value("x" * 9_000)) == 8_000
