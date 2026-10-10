import json
import os
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TaskEvent:
    event_id: str
    event_type: str
    timestamp: float
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TaskEvent":
        return cls(
            event_id=d["event_id"],
            event_type=d["event_type"],
            timestamp=d.get("timestamp", time.time()),
            data=d.get("data", {})
        )


@dataclass
class TaskState:
    """State derived deterministically by reducing over an EventLog."""
    goal: str = ""
    current_step: int = 0
    facts: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    status: str = "active"  # active | waiting_for_user | completed | escalated | blocked
    final_answer: str | None = None
    verification_passed: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def state_reducer(state: TaskState, event: TaskEvent) -> TaskState:
    """
    Pure state reducer: State_n = Reducer(State_{n-1}, Event_n)
    """
    etype = event.event_type
    edata = event.data

    if etype == "user_input":
        state.goal = edata.get("content", state.goal)
        state.status = "active"

    elif etype == "proposal":
        ptype = edata.get("type", "")
        if ptype == "action":
            pass
        elif ptype == "complete":
            state.final_answer = edata.get("final_answer", "")
        elif ptype == "escalate":
            state.status = "escalated"
            state.errors.append(edata.get("reason", "Escalation requested"))

    elif etype == "tool_executed":
        state.tool_results.append({
            "tool": edata.get("tool", ""),
            "args": edata.get("args", ""),
            "result": edata.get("result", ""),
            "timestamp": event.timestamp
        })
        state.current_step += 1

    elif etype == "action_blocked":
        state.errors.append(edata.get("reason", "Action blocked"))

    elif etype == "fact_recorded":
        state.facts.append(edata)

    elif etype == "verification_run":
        state.verification_passed = edata.get("passed", False)
        if not state.verification_passed:
            state.errors.append(f"Verification failed: {edata.get('failures', [])}")

    elif etype == "task_completed":
        state.status = "completed"
        state.final_answer = edata.get("answer", state.final_answer)

    elif etype == "task_escalated":
        state.status = "escalated"
        state.errors.append(edata.get("reason", "Task escalated"))

    elif etype == "task_waiting_for_user":
        state.status = "waiting_for_user"

    return state


class EventLog:
    """Append-only, sequentially indexed event log."""
    def __init__(self):
        self.events: list[TaskEvent] = []

    def append(self, event_type: str, data: dict[str, Any], timestamp: float | None = None) -> TaskEvent:
        """Append a local event, optionally preserving an upstream event timestamp."""
        event_num = len(self.events) + 1
        event = TaskEvent(
            event_id=f"evt_{event_num:04d}",
            event_type=event_type,
            timestamp=time.time() if timestamp is None else float(timestamp),
            data=data
        )
        self.events.append(event)
        return event

    def replay(self, reducer: Callable[[TaskState, TaskEvent], TaskState] | None = None) -> TaskState:
        """Reconstructs state deterministically from genesis to current event."""
        red = reducer or state_reducer
        state = TaskState()
        for evt in self.events:
            state = red(state, evt)
        return state

    def to_jsonl(self) -> str:
        return "\n".join(json.dumps(evt.to_dict()) for evt in self.events)

    def save_jsonl(self, path: str) -> None:
        """Atomically persist the append-only audit log to an explicit path."""
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        temp_path = f"{path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            handle.write(self.to_jsonl())
            handle.write("\n")
        os.replace(temp_path, path)

    @classmethod
    def load_jsonl(cls, path: str) -> "EventLog":
        with open(path, "r", encoding="utf-8") as handle:
            return cls.from_jsonl(handle.read())

    @classmethod
    def from_jsonl(cls, jsonl_str: str) -> "EventLog":
        log = cls()
        for line_number, line in enumerate(jsonl_str.strip().split("\n"), 1):
            if line.strip():
                try:
                    d = json.loads(line.strip())
                    log.events.append(TaskEvent.from_dict(d))
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(f"Invalid event log entry at line {line_number}") from exc
        return log
