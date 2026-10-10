"""Deterministic, budgeted candidate selection for SLM planning and repair."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Generic, TypeVar

from .budget import ExecutionDeadline


Candidate = TypeVar("Candidate")


@dataclass(frozen=True)
class SearchEvaluation:
    candidate_id: str
    score: float
    passed: bool
    rationale: str = ""


@dataclass
class SearchResult(Generic[Candidate]):
    selected: Candidate | None
    evaluations: list[SearchEvaluation] = field(default_factory=list)
    exhausted: bool = False


class BoundedSearch(Generic[Candidate]):
    """Evaluate a fixed candidate set without unbounded retries or branching."""

    def __init__(self, max_candidates: int = 4):
        if not 1 <= max_candidates <= 16:
            raise ValueError("max_candidates must be between 1 and 16")
        self.max_candidates = max_candidates

    def select(
        self,
        candidates: list[Candidate],
        evaluate: Callable[[Candidate], SearchEvaluation],
        deadline: ExecutionDeadline | None = None,
    ) -> SearchResult[Candidate]:
        evaluations: list[SearchEvaluation] = []
        best: tuple[float, int, Candidate] | None = None
        exhausted = len(candidates) > self.max_candidates
        for index, candidate in enumerate(candidates[: self.max_candidates]):
            if deadline and deadline.expired:
                exhausted = True
                break
            evaluation = evaluate(candidate)
            evaluations.append(evaluation)
            if evaluation.passed and (best is None or evaluation.score > best[0]):
                best = (evaluation.score, index, candidate)
        return SearchResult(selected=best[2] if best else None, evaluations=evaluations, exhausted=exhausted)
