"""Verified, sanitized execution traces for offline SLM improvement."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .event_store import EventLog


_SECRET_PATTERN = re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+")
_MAX_TEXT_LENGTH = 8_000


def sanitize_trace_value(value: Any) -> Any:
    """Recursively redact likely credentials and cap unbounded text fields."""
    if isinstance(value, str):
        return _SECRET_PATTERN.sub(r"\1=[REDACTED]", value)[:_MAX_TEXT_LENGTH]
    if isinstance(value, list):
        return [sanitize_trace_value(item) for item in value]
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if re.search(r"(?i)(api[_-]?key|token|password|secret)", key_text):
                sanitized[key_text] = "[REDACTED]"
            else:
                sanitized[key_text] = sanitize_trace_value(item)
        return sanitized
    return value


@dataclass(frozen=True)
class TraceExample:
    trace_id: str
    source_kind: str
    verified_success: bool
    events: tuple[dict[str, Any], ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["events"] = list(self.events)
        return data


class TraceDataset:
    """Accepts only verified non-benchmark traces for later offline review."""

    def __init__(self, dataset_id: str, examples: list[TraceExample] | None = None):
        if not dataset_id.strip():
            raise ValueError("dataset_id is required")
        self.dataset_id = dataset_id
        self.examples = list(examples or [])

    def add_event_log(
        self,
        event_log: EventLog,
        *,
        verified_success: bool,
        source_kind: str = "production",
        metadata: dict[str, Any] | None = None,
    ) -> TraceExample:
        if not verified_success:
            raise ValueError("Only verified-success traces may enter a training dataset")
        if source_kind.lower() == "benchmark":
            raise ValueError("Benchmark traces are quarantined from training datasets")
        events = tuple(sanitize_trace_value(event.to_dict()) for event in event_log.events)
        canonical = json.dumps(events, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        example = TraceExample(
            trace_id=hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20],
            source_kind=source_kind,
            verified_success=True,
            events=events,
            metadata=sanitize_trace_value(metadata or {}),
        )
        if all(existing.trace_id != example.trace_id for existing in self.examples):
            self.examples.append(example)
        return example

    def to_jsonl(self) -> str:
        return "\n".join(json.dumps(example.to_dict(), sort_keys=True, ensure_ascii=False) for example in self.examples)

    def save_jsonl(self, path: str) -> None:
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        temporary = f"{path}.tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(self.to_jsonl())
            if self.examples:
                handle.write("\n")
        os.replace(temporary, path)
