from pathlib import Path

from gitcrawl.source import resolve
from gitcrawl.survey import run_survey

FIXTURES = Path(__file__).parent / "fixtures"


def test_vendored_heavy_excludes_everything_junk():
    handle = resolve(str(FIXTURES / "vendored_heavy"))
    survey = run_survey(handle)

    # Nothing under node_modules, .venv, dist, or the lock file may appear
    # anywhere in the candidate shortlist.
    banned_substrings = ("node_modules", ".venv", "dist/", "package-lock.json")
    for path in survey.candidate_files:
        assert not any(b in path for b in banned_substrings), path

    assert "src/app.py" in survey.candidate_files
    # 2 files in node_modules/leftpad + 1 in .venv/lib + 1 in dist, plus the
    # root-level package-lock.json.
    assert survey.excluded_count == 5
    assert survey.total_files == 7  # app.py, README.md, package-lock.json + 4 pruned
    assert survey.has_readme is True
    assert survey.has_license is False
    assert survey.has_tests is False
    assert survey.has_ci is False

    # No tests + no CI -> both pillars clamp early.
    assert "test_coverage" in survey.early_clamps
    assert "ci_cd" in survey.early_clamps
    assert "community" not in survey.early_clamps  # README present


def test_no_tests_fixture_clamps_test_coverage_only():
    fixture = FIXTURES / "no_tests"
    handle = resolve(str(fixture))
    survey = run_survey(handle)

    assert survey.has_tests is False
    assert survey.has_readme is True
    assert survey.has_license is True
    assert "test_coverage" in survey.early_clamps
    assert "community" not in survey.early_clamps
