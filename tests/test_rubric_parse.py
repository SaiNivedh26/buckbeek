import pytest

from gitcrawl.rubric import RubricError, load_default_rubric, parse_rubric

_VALID = """\
# Tiny rubric
Version: 0.1

## Pillar: Security
Weight: 60%
Focus: Supply-chain hygiene.

### Criteria
- A security policy exists.
- Dependencies are updated automatically.

### Bands
- 0-4: Nothing in place.
- 5-7: Some policy.
- 8-10: Strong.

### Hard rules
- If there is no security policy, score is at most 4.

## Pillar: Docs & Guides
Weight: 40%

### Criteria
- The README explains installation and usage.

### Bands
- 0-5: Poor.
- 6-10: Good.
"""


def test_valid_template_parses_exact_fields():
    rubric = parse_rubric(_VALID)
    assert rubric.title == "Tiny rubric"
    assert rubric.version == "0.1"
    assert [p.id for p in rubric.pillars] == ["security", "docs_guides"]

    sec = rubric.pillar("security")
    assert sec.weight == pytest.approx(0.60)
    assert sec.focus == "Supply-chain hygiene."
    assert sec.criteria == ["A security policy exists.", "Dependencies are updated automatically."]
    assert [(b.low, b.high) for b in sec.bands] == [(0, 4), (5, 7), (8, 10)]
    assert sec.hard_rules == ["If there is no security policy, score is at most 4."]
    assert rubric.pillar("docs_guides").hard_rules == []


def test_content_hash_changes_with_content():
    a = parse_rubric(_VALID)
    b = parse_rubric(_VALID.replace("Strong.", "Very strong."))
    assert a.content_hash != b.content_hash
    assert a.content_hash == parse_rubric(_VALID).content_hash


def test_weights_not_summing_to_100_is_rejected():
    with pytest.raises(RubricError, match="add up to 100%"):
        parse_rubric(_VALID.replace("Weight: 40%", "Weight: 30%"))


def test_band_gap_is_rejected():
    with pytest.raises(RubricError, match="gap or overlap"):
        parse_rubric(_VALID.replace("- 5-7: Some policy.", "- 6-7: Some policy."))


def test_bands_not_reaching_10_are_rejected():
    with pytest.raises(RubricError, match="must end at 10"):
        parse_rubric(_VALID.replace("- 6-10: Good.", "- 6-9: Good."))


def test_missing_weight_and_criteria_are_all_reported_at_once():
    broken = _VALID.replace("Weight: 60%\n", "").replace("- The README explains installation and usage.\n", "")
    with pytest.raises(RubricError) as exc:
        parse_rubric(broken)
    joined = "\n".join(exc.value.errors)
    assert "'Security': missing 'Weight: N%'" in joined
    assert "'Docs & Guides': '### Criteria' needs at least one" in joined


def test_duplicate_pillar_names_are_rejected():
    dup = _VALID.replace("## Pillar: Docs & Guides", "## Pillar: Security")
    with pytest.raises(RubricError, match="duplicate pillar id"):
        parse_rubric(dup)


def test_unknown_subsection_is_rejected():
    with pytest.raises(RubricError, match="unknown subsection"):
        parse_rubric(_VALID.replace("### Hard rules", "### Extras"))


def test_bundled_default_rubric_is_valid():
    rubric = load_default_rubric()
    assert [p.id for p in rubric.pillars] == [
        "code_health",
        "test_coverage",
        "ci_cd",
        "issue_management",
        "community",
    ]
    assert sum(p.weight for p in rubric.pillars) == pytest.approx(1.0)
    assert rubric.pillar("test_coverage").hard_rules
