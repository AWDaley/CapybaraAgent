from tal.bounded_search import BoundedSearch, SearchEvaluation
from tal.budget import ExecutionDeadline


def test_bounded_search_selects_highest_passing_candidate_with_fixed_limit():
    checked = []

    def evaluate(candidate):
        checked.append(candidate)
        return SearchEvaluation(str(candidate), float(candidate), candidate >= 2)

    result = BoundedSearch[int](max_candidates=3).select([1, 2, 4, 99], evaluate)
    assert checked == [1, 2, 4]
    assert result.selected == 4
    assert result.exhausted is True


def test_bounded_search_honors_expired_deadline():
    result = BoundedSearch[str]().select(
        ["first"],
        lambda item: SearchEvaluation(item, 1.0, True),
        deadline=ExecutionDeadline.start(0),
    )
    assert result.selected is None
    assert result.evaluations == []
    assert result.exhausted is True
