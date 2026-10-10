from tal.event_store import EventLog, state_reducer
import pytest
import tempfile
import os


def test_event_log_append_and_indexing():
    log = EventLog()
    e1 = log.append("user_input", {"content": "Hello"})
    e2 = log.append("proposal", {"type": "action", "data": "calc"})
    
    assert e1.event_id == "evt_0001"
    assert e2.event_id == "evt_0002"
    assert len(log.events) == 2


def test_event_log_can_preserve_upstream_timestamp():
    log = EventLog()
    event = log.append("specialist_tool_executed", {"tool": "calc"}, timestamp=1234.5)

    assert event.timestamp == 1234.5


def test_pure_state_reducer():
    log = EventLog()
    log.append("user_input", {"content": "Calculate 2+2"})
    log.append("tool_executed", {"tool": "calc", "args": '{"expression": "2+2"}', "result": "4"})
    log.append("task_completed", {"answer": "The answer is 4."})
    
    state = log.replay(state_reducer)
    assert state.goal == "Calculate 2+2"
    assert state.current_step == 1
    assert len(state.tool_results) == 1
    assert state.tool_results[0]["result"] == "4"
    assert state.status == "completed"
    assert state.final_answer == "The answer is 4."


def test_event_log_jsonl_roundtrip():
    log = EventLog()
    log.append("user_input", {"content": "List files"})
    log.append("tool_executed", {"tool": "list_files", "args": "{}", "result": "a.txt\nb.txt"})
    
    jsonl_str = log.to_jsonl()
    loaded_log = EventLog.from_jsonl(jsonl_str)
    
    assert len(loaded_log.events) == 2
    assert loaded_log.events[0].event_type == "user_input"
    assert loaded_log.events[1].data["tool"] == "list_files"
    
    # Replay produces same state
    state = loaded_log.replay()
    assert state.goal == "List files"
    assert state.current_step == 1


def test_event_log_persistence_is_atomic_and_rejects_corruption():
    log = EventLog()
    log.append("user_input", {"content": "audit this"})
    with tempfile.TemporaryDirectory() as directory:
        target = os.path.join(directory, "events.jsonl")
        log.save_jsonl(target)
        assert EventLog.load_jsonl(target).events[0].event_type == "user_input"

    with pytest.raises(ValueError, match="line 1"):
        EventLog.from_jsonl("not json")
