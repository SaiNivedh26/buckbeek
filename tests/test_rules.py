import pytest

from gitcrawl.collectors.base import Fact
from gitcrawl.plan import rules
from gitcrawl.plan.rules import RuleError


def _fact(check_id: str, **data) -> Fact:
    return Fact(check_id=check_id, collector="x", data=data)


FACTS = {
    "tests": _fact("tests", file_count=0, frameworks=[]),
    "ci": _fact("ci", has_ci=True, run_success_rate=0.15),
    "broken": Fact(check_id="broken", collector="x", error="collector crashed"),
}


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("tests.file_count == 0", True),
        ("tests.file_count > 0", False),
        ("ci.has_ci == true and ci.run_success_rate < 0.2", True),
        ("not ci.has_ci or tests.file_count >= 1", False),
        ("0 <= ci.run_success_rate < 1", True),
        ("ci.run_success_rate != null", True),
    ],
)
def test_evaluate(expr, expected):
    assert rules.evaluate(expr, FACTS) is expected


def test_errored_or_missing_fact_is_undetermined_not_false():
    assert rules.evaluate("broken.count == 0", FACTS) is None
    assert rules.evaluate("missing.count == 0", FACTS) is None


def test_undetermined_operand_is_ignored_when_result_does_not_depend_on_it():
    assert rules.evaluate("tests.file_count == 0 or broken.count == 0", FACTS) is True
    assert rules.evaluate("tests.file_count == 1 and broken.count == 0", FACTS) is False
    assert rules.evaluate("tests.file_count == 1 or broken.count == 0", FACTS) is None


def test_type_mismatch_is_undetermined():
    assert rules.evaluate("tests.frameworks > 3", FACTS) is None


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('rm -rf /')",
        "tests.file_count.real",
        "tests.frameworks[0] == 'pytest'",
        "tests.file_count + 1 > 2",
        "len(tests.frameworks) == 0",
        "(lambda: 1)()",
    ],
)
def test_unsafe_constructs_are_rejected(expr):
    with pytest.raises(RuleError):
        rules.parse(expr)


def test_validate_checks_references_against_output_fields():
    fields = {"tests": {"file_count", "frameworks"}}
    assert rules.validate("tests.file_count == 0", fields) == []
    assert "unknown check 'ci'" in rules.validate("ci.has_ci", fields)[0]
    assert "has no field 'count'" in rules.validate("tests.count == 0", fields)[0]
    assert "bare name" in rules.validate("file_count == 0", fields)[0]
    assert rules.validate("tests.file_count ==", fields)[0].startswith("not a valid rule expression")


def test_references():
    assert rules.references("tests.file_count == 0 and ci.has_ci") == [("tests", "file_count"), ("ci", "has_ci")]
