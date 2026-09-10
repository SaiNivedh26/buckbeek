from pathlib import Path

from gitcrawl.config import load_config
from gitcrawl.models import PillarVerdict
from gitcrawl.scoring.clamps import apply_clamps
from gitcrawl.source import resolve
from gitcrawl.survey import run_survey

FIXTURES = Path(__file__).parent / "fixtures"


def test_no_tests_fixture_cannot_exceed_clamp_regardless_of_scorer_output():
    cfg = load_config()
    handle = resolve(str(FIXTURES / "no_tests"))
    survey = run_survey(handle)
    assert survey.has_tests is False

    # Scorer got talked into a generous 9 despite zero test files.
    verdicts = [PillarVerdict(pillar="test_coverage", score=9.0, confidence=0.9, justification="looked fine")]
    clamped, applied = apply_clamps(verdicts, survey, cfg)

    assert clamped[0].score == cfg.clamps.no_tests_max
    assert any("test_coverage" in line for line in applied)


def test_clamp_never_raises_a_score():
    cfg = load_config()
    handle = resolve(str(FIXTURES / "no_tests"))
    survey = run_survey(handle)

    verdicts = [PillarVerdict(pillar="test_coverage", score=1.0, confidence=0.5, justification="")]
    clamped, applied = apply_clamps(verdicts, survey, cfg)

    assert clamped[0].score == 1.0  # already below the cap; untouched
    assert applied == []


def test_clamp_skips_abstained_pillars():
    cfg = load_config()
    handle = resolve(str(FIXTURES / "no_tests"))
    survey = run_survey(handle)

    verdicts = [PillarVerdict(pillar="test_coverage", score=None, abstained=True, justification="")]
    clamped, applied = apply_clamps(verdicts, survey, cfg)

    assert clamped[0].abstained is True
    assert clamped[0].score is None
    assert applied == []


def test_vendored_heavy_clamps_both_tests_and_ci():
    cfg = load_config()
    handle = resolve(str(FIXTURES / "vendored_heavy"))
    survey = run_survey(handle)

    verdicts = [
        PillarVerdict(pillar="test_coverage", score=8.0, confidence=0.9, justification=""),
        PillarVerdict(pillar="ci_cd", score=7.0, confidence=0.9, justification=""),
    ]
    clamped, applied = apply_clamps(verdicts, survey, cfg)

    by_pillar = {v.pillar: v.score for v in clamped}
    assert by_pillar["test_coverage"] == cfg.clamps.no_tests_max
    assert by_pillar["ci_cd"] == cfg.clamps.no_ci_max
    assert len(applied) == 2
