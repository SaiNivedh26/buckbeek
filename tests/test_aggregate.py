from gitcrawl.results import PillarResult
from gitcrawl.scoring.aggregate import aggregate

# The bundled rubric's weights.
WEIGHTS = {
    "code_health": 0.25,
    "test_coverage": 0.20,
    "ci_cd": 0.20,
    "issue_management": 0.20,
    "community": 0.15,
}


def _result(pillar: str, score: float | None, abstained: bool = False) -> PillarResult:
    return PillarResult(pillar=pillar, name=pillar, weight=WEIGHTS[pillar], score=score, abstained=abstained)


def test_reproduces_the_rubric_worked_example():
    """CH=8, Test=7, CI=9, Issues=6, Community=5 -> 7.15 / 10, 100% coverage."""
    results = [
        _result("code_health", 8),
        _result("test_coverage", 7),
        _result("ci_cd", 9),
        _result("issue_management", 6),
        _result("community", 5),
    ]
    total, coverage = aggregate(results, WEIGHTS)
    assert total == 7.15
    assert coverage == 1.0


def test_renormalizes_with_two_abstentions():
    """Only 3 of 5 pillars scored (65% of the weight): the result is what those
    3 alone average to, not dragged toward 0 by the missing two."""
    results = [
        _result("code_health", 8),
        _result("test_coverage", 7),
        _result("ci_cd", 9),
        _result("issue_management", None, abstained=True),
        _result("community", None, abstained=True),
    ]
    total, coverage = aggregate(results, WEIGHTS)
    assert coverage == 0.65
    assert total == 8.0  # (0.25*8 + 0.20*7 + 0.20*9) / 0.65


def test_renormalizes_with_one_abstention():
    results = [
        _result("code_health", 6),
        _result("test_coverage", 4),
        _result("ci_cd", 6),
        _result("issue_management", 5),
        _result("community", None, abstained=True),
    ]
    total, coverage = aggregate(results, WEIGHTS)
    assert coverage == 0.85
    assert total == round((0.25 * 6 + 0.20 * 4 + 0.20 * 6 + 0.20 * 5) / 0.85, 2)


def test_all_abstained_gives_no_score():
    total, coverage = aggregate([_result(p, None, abstained=True) for p in WEIGHTS], WEIGHTS)
    assert total is None
    assert coverage == 0.0


def test_unknown_pillar_id_contributes_no_weight():
    """aggregate() looks weights up by exact pillar id. Ids are code-owned
    (copied from the parsed rubric), never model output — a model once echoed
    "Test Coverage" for "test_coverage" and silently zeroed that pillar."""
    total, coverage = aggregate([PillarResult(pillar="Test Coverage", name="x", weight=0.2, score=8)], WEIGHTS)
    assert total is None and coverage == 0.0
