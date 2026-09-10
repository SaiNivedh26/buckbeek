from gitcrawl.models import PillarVerdict
from gitcrawl.scoring.aggregate import aggregate

# clause.md §2.1 weights, verbatim.
CLAUSE_WEIGHTS = {
    "code_health": 0.25,
    "test_coverage": 0.20,
    "ci_cd": 0.20,
    "issue_management": 0.20,
    "community": 0.15,
}


def _verdict(pillar: str, score: float | None, abstained: bool = False) -> PillarVerdict:
    return PillarVerdict(pillar=pillar, score=score, confidence=0.8, abstained=abstained, justification="")


def test_reproduces_clause_md_worked_example():
    """clause.md §2.2's worked example: CH=8, Test=7, CI=9, Issues=6,
    Community=5 -> 7.15 / 10, 100% coverage (nothing abstained)."""
    verdicts = [
        _verdict("code_health", 8),
        _verdict("test_coverage", 7),
        _verdict("ci_cd", 9),
        _verdict("issue_management", 6),
        _verdict("community", 5),
    ]
    total, coverage = aggregate(verdicts, CLAUSE_WEIGHTS)
    assert total == 7.15
    assert coverage == 1.0


def test_renormalizes_with_two_abstentions():
    """Only 3 of 5 pillars scored (65% of the weight). The result should be
    what those 3 pillars alone would average to, not dragged toward 0 by
    the missing two."""
    verdicts = [
        _verdict("code_health", 8),
        _verdict("test_coverage", 7),
        _verdict("ci_cd", 9),
        _verdict("issue_management", None, abstained=True),
        _verdict("community", None, abstained=True),
    ]
    total, coverage = aggregate(verdicts, CLAUSE_WEIGHTS)
    assert coverage == 0.65
    # raw = 0.25*8 + 0.20*7 + 0.20*9 = 5.20; 5.20 / 0.65 = 8.0
    assert total == 8.0


def test_renormalizes_with_one_abstention():
    verdicts = [
        _verdict("code_health", 6),
        _verdict("test_coverage", 4),
        _verdict("ci_cd", 6),
        _verdict("issue_management", 5),
        _verdict("community", None, abstained=True),
    ]
    total, coverage = aggregate(verdicts, CLAUSE_WEIGHTS)
    assert coverage == 0.85
    raw = 0.25 * 6 + 0.20 * 4 + 0.20 * 6 + 0.20 * 5
    assert total == round(raw / 0.85, 2)


def test_all_abstained_gives_no_score():
    verdicts = [_verdict(p, None, abstained=True) for p in CLAUSE_WEIGHTS]
    total, coverage = aggregate(verdicts, CLAUSE_WEIGHTS)
    assert total is None
    assert coverage == 0.0
