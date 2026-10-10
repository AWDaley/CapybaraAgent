import time

from tal.budget import BudgetLimits, BudgetTracker


def test_budget_step_exhaustion():
    limits = BudgetLimits(max_steps=3)
    tracker = BudgetTracker(limits=limits)
    tracker.start()

    assert tracker.check() is None
    tracker.record_step()
    tracker.record_step()
    assert tracker.check() is None
    tracker.record_step()
    assert "Step budget exhausted" in tracker.check()


def test_budget_consecutive_error_exhaustion():
    limits = BudgetLimits(max_tool_errors=2)
    tracker = BudgetTracker(limits=limits)
    tracker.start()

    tracker.record_error()
    assert tracker.check() is None

    # Success resets consecutive count
    tracker.record_success()
    assert tracker.consecutive_errors == 0
    assert tracker.check() is None

    tracker.record_error()
    tracker.record_error()
    assert "Consecutive error budget exhausted" in tracker.check()


def test_budget_time_exhaustion():
    limits = BudgetLimits(max_time_seconds=0.05)
    tracker = BudgetTracker(limits=limits)
    tracker.start()

    time.sleep(0.06)
    assert "Time budget exhausted" in tracker.check()


def test_budget_status_dict():
    tracker = BudgetTracker(limits=BudgetLimits(max_steps=5))
    tracker.record_step()
    tracker.record_error()
    status = tracker.get_status()
    assert status["steps_used"] == 1
    assert status["max_steps"] == 5
    assert status["consecutive_errors"] == 1
    assert status["total_errors"] == 1


def test_budget_repair_exhaustion():
    limits = BudgetLimits(max_repair_attempts=2)
    tracker = BudgetTracker(limits=limits)
    tracker.start()

    tracker.record_repair()
    assert tracker.check() is None  # 1 attempt, limit is 2

    tracker.record_repair()
    result = tracker.check()
    assert result is not None  # 2 attempts == limit, should trigger
    assert "Output repair attempt budget exhausted" in result


def test_slm_budget_limits_defaults():
    from agent import BasicAgent
    from tal.budget import SLMBudgetLimits

    slm_limits = SLMBudgetLimits()
    assert slm_limits.max_time_seconds == 3600.0
    assert slm_limits.max_steps == 15
    assert slm_limits.max_tool_errors == 4

    # BasicAgent auto-adopts SLMBudgetLimits when use_slm_profile is True
    agent = BasicAgent(use_slm_profile=True)
    assert agent.budget_limits.max_time_seconds == 3600.0
    assert agent.budget_limits.max_steps == 15

