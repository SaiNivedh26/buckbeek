from gitcrawl.models import Finding, Findings, PillarVerdict
from gitcrawl.storage import cache, db


def _findings() -> Findings:
    return Findings(
        pillar="test_coverage",
        findings=[
            Finding(observation="12 test files, all covering parser.py", citations=["tests/test_parser.py"])
        ],
        evidence_coverage=0.85,
        files_examined=["tests/test_parser.py"],
        stopped_reason="confident",
        tool_calls_used=8,
    )


def test_findings_round_trip():
    conn = db.connect(":memory:")
    run_id = cache.create_run(
        conn,
        repo=".",
        commit_sha="abc123",
        rubric_version="1.0",
        config_hash="cfg1",
        investigator_model="mistral-large-latest",
        scorer_model="mistral-large-latest",
    )
    original = _findings()
    fid = cache.save_findings(
        conn, run_id=run_id, commit_sha="abc123", tool_version="1", filter_version="1", findings=original
    )

    loaded = cache.load_findings(
        conn, commit_sha="abc123", pillar="test_coverage", tool_version="1", filter_version="1"
    )
    assert loaded is not None
    loaded_id, loaded_findings = loaded
    assert loaded_id == fid
    assert loaded_findings == original


def test_verdict_round_trip():
    conn = db.connect(":memory:")
    run_id = cache.create_run(
        conn, repo=".", commit_sha="abc123", rubric_version="1.0", config_hash="cfg1",
        investigator_model="m", scorer_model="m",
    )
    fid = cache.save_findings(
        conn, run_id=run_id, commit_sha="abc123", tool_version="1", filter_version="1", findings=_findings()
    )
    verdict = PillarVerdict(pillar="test_coverage", score=4.0, confidence=0.8, justification="low coverage")
    cache.save_verdict(conn, findings_id=fid, rubric_version="1.0", scorer_model="m", verdict=verdict)

    loaded = cache.load_verdict(conn, findings_id=fid, rubric_version="1.0", scorer_model="m")
    assert loaded == verdict


def test_rubric_change_invalidates_verdict_but_reuses_findings():
    """The property the two-table schema exists for (docs/design.md §7.2,
    §15 item 9): changing rubric_version must not touch findings at all."""
    conn = db.connect(":memory:")
    run_id = cache.create_run(
        conn, repo=".", commit_sha="abc123", rubric_version="1.0", config_hash="cfg1",
        investigator_model="m", scorer_model="m",
    )
    fid = cache.save_findings(
        conn, run_id=run_id, commit_sha="abc123", tool_version="1", filter_version="1", findings=_findings()
    )
    cache.save_verdict(
        conn, findings_id=fid, rubric_version="1.0", scorer_model="m",
        verdict=PillarVerdict(pillar="test_coverage", score=4.0, confidence=0.8, justification="v1"),
    )

    # Rubric bumped to 1.1 — no verdict cached under the new version yet.
    assert cache.load_verdict(conn, findings_id=fid, rubric_version="1.1", scorer_model="m") is None
    # But the findings themselves are untouched and still load under the
    # exact same key — a re-score needs zero tool calls to get here.
    same = cache.load_findings(
        conn, commit_sha="abc123", pillar="test_coverage", tool_version="1", filter_version="1"
    )
    assert same is not None
    assert same[0] == fid

    # Scoring under the new rubric writes a second verdict row without
    # disturbing the 1.0 verdict.
    cache.save_verdict(
        conn, findings_id=fid, rubric_version="1.1", scorer_model="m",
        verdict=PillarVerdict(pillar="test_coverage", score=5.0, confidence=0.9, justification="v1.1"),
    )
    v10 = cache.load_verdict(conn, findings_id=fid, rubric_version="1.0", scorer_model="m")
    v11 = cache.load_verdict(conn, findings_id=fid, rubric_version="1.1", scorer_model="m")
    assert v10.score == 4.0
    assert v11.score == 5.0


def test_filter_version_change_misses_findings_cache():
    conn = db.connect(":memory:")
    run_id = cache.create_run(
        conn, repo=".", commit_sha="abc123", rubric_version="1.0", config_hash="cfg1",
        investigator_model="m", scorer_model="m",
    )
    cache.save_findings(
        conn, run_id=run_id, commit_sha="abc123", tool_version="1", filter_version="1", findings=_findings()
    )
    # Exclusion rules changed (filter_version bumped) -> must re-investigate.
    assert cache.load_findings(
        conn, commit_sha="abc123", pillar="test_coverage", tool_version="1", filter_version="2"
    ) is None
