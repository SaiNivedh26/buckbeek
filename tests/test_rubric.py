from gitcrawl.agents.rubric import load_rubric, rubric_version


def test_all_five_pillars_present():
    rubric = load_rubric()
    assert set(rubric) == {
        "code_health",
        "test_coverage",
        "ci_cd",
        "issue_management",
        "community",
    }


def test_sections_are_isolated_from_each_other():
    """The Test Coverage scorer must never see Code Health's text or vice
    versa — that's the whole point of handing over one section, not the
    document."""
    rubric = load_rubric()
    assert "### 3.2" not in rubric["code_health"]
    assert "### 3.1" not in rubric["test_coverage"]
    assert "Test Coverage" not in rubric["code_health"]


def test_section_carries_scoring_bands():
    rubric = load_rubric()
    assert "0–2" in rubric["test_coverage"] or "0-2" in rubric["test_coverage"]
    assert "9–10" in rubric["test_coverage"] or "9-10" in rubric["test_coverage"]


def test_rubric_version_matches_clause_md_section_6():
    assert rubric_version() == "1.0"
