import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BudgetLimits:
    max_steps: int = 10
    max_time_seconds: float = 300.0
    max_tool_errors: int = 3
    max_repair_attempts: int = 2


@dataclass
class SLMBudgetLimits(BudgetLimits):
    """Extended budget limits suited for local SLMs with higher inference latency."""
    max_steps: int = 15
    max_time_seconds: float = 3600.0
    max_tool_errors: int = 4
    max_repair_attempts: int = 3


class DeadlineExceeded(TimeoutError):
    """Raised when a shared execution deadline has elapsed."""


@dataclass(frozen=True)
class ExecutionDeadline:
    """A monotonic, shared deadline for one pipeline execution.

    Unlike per-agent budgets this deadline is never reset by a retry or a
    specialist handoff.  Every blocking operation must use its remaining time
    as an upper bound.
    """

    started_at: float
    timeout_seconds: float

    @classmethod
    def start(cls, timeout_seconds: float) -> "ExecutionDeadline":
        return cls(started_at=time.monotonic(), timeout_seconds=max(0.0, float(timeout_seconds)))

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, time.monotonic() - self.started_at)

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.timeout_seconds - self.elapsed_seconds)

    @property
    def expired(self) -> bool:
        return self.remaining_seconds <= 0.0

    def require_remaining(self, operation: str = "operation") -> float:
        remaining = self.remaining_seconds
        if remaining <= 0.0:
            raise DeadlineExceeded(f"Pipeline deadline exhausted before {operation}.")
        return remaining

    def cap_timeout(self, requested_seconds: float, operation: str = "operation") -> float:
        return min(float(requested_seconds), self.require_remaining(operation))


@dataclass
class BudgetTracker:
    limits: BudgetLimits = field(default_factory=BudgetLimits)
    steps_used: int = 0
    time_started: float = field(default_factory=time.time)
    consecutive_errors: int = 0
    total_errors: int = 0
    repair_attempts: int = 0

    def start(self):
        self.time_started = time.time()

    def reset(self):
        """Start an independent task with no inherited budget consumption."""
        self.steps_used = 0
        self.consecutive_errors = 0
        self.total_errors = 0
        self.repair_attempts = 0
        self.time_started = time.time()

    def record_step(self):
        self.steps_used += 1

    def record_success(self):
        self.consecutive_errors = 0

    def record_error(self):
        self.consecutive_errors += 1
        self.total_errors += 1

    def record_repair(self):
        self.repair_attempts += 1

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.time_started

    def check(self) -> str | None:
        """Returns escalation reason if any budget limit is exceeded, else None."""
        if self.steps_used >= self.limits.max_steps:
            return f"Step budget exhausted ({self.steps_used}/{self.limits.max_steps} steps used)"

        if self.elapsed_seconds > self.limits.max_time_seconds:
            return f"Time budget exhausted ({self.elapsed_seconds:.1f}s / {self.limits.max_time_seconds}s limit)"

        if self.consecutive_errors >= self.limits.max_tool_errors:
            return f"Consecutive error budget exhausted ({self.consecutive_errors}/{self.limits.max_tool_errors} consecutive failures)"

        if self.repair_attempts >= self.limits.max_repair_attempts:
            return f"Output repair attempt budget exhausted ({self.repair_attempts}/{self.limits.max_repair_attempts} attempts)"

        return None

    def get_status(self) -> dict[str, Any]:
        return {
            "steps_used": self.steps_used,
            "max_steps": self.limits.max_steps,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "max_time_seconds": self.limits.max_time_seconds,
            "consecutive_errors": self.consecutive_errors,
            "max_tool_errors": self.limits.max_tool_errors,
            "total_errors": self.total_errors,
            "repair_attempts": self.repair_attempts,
        }
