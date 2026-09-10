"""Findings/verdicts lookup by their own cache keys. See docs/design.md §7.2
and the schema.sql header comment — this module is what makes "re-score
without re-reading the repo" and "re-explore without re-scoring" both true.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from gitcrawl.models import Findings, PillarVerdict


def _now() -> str:
    return datetime.now(UTC).isoformat()


def create_run(
    conn: sqlite3.Connection,
    *,
    repo: str,
    commit_sha: str,
    rubric_version: str,
    config_hash: str,
    investigator_model: str,
    scorer_model: str,
) -> int:
    cur = conn.execute(
        """INSERT INTO runs
           (repo, commit_sha, rubric_version, config_hash,
            investigator_model, scorer_model, started_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (repo, commit_sha, rubric_version, config_hash, investigator_model, scorer_model, _now()),
    )
    conn.commit()
    return cur.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, total_score: float | None, rubric_coverage: float) -> None:
    conn.execute(
        "UPDATE runs SET total_score = ?, rubric_coverage = ? WHERE id = ?",
        (total_score, rubric_coverage, run_id),
    )
    conn.commit()


def save_findings(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    commit_sha: str,
    tool_version: str,
    filter_version: str,
    findings: Findings,
) -> int:
    """Upsert by (commit_sha, pillar, tool_version, filter_version)."""
    cur = conn.execute(
        """INSERT INTO findings
               (run_id, commit_sha, pillar, payload_json, evidence_coverage,
                stopped_reason, tool_version, filter_version, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (commit_sha, pillar, tool_version, filter_version)
           DO UPDATE SET run_id = excluded.run_id,
                         payload_json = excluded.payload_json,
                         evidence_coverage = excluded.evidence_coverage,
                         stopped_reason = excluded.stopped_reason,
                         created_at = excluded.created_at
           RETURNING id""",
        (
            run_id,
            commit_sha,
            findings.pillar,
            findings.model_dump_json(),
            findings.evidence_coverage,
            findings.stopped_reason,
            tool_version,
            filter_version,
            _now(),
        ),
    )
    row = cur.fetchone()
    conn.commit()
    return row["id"]


def load_findings(
    conn: sqlite3.Connection,
    *,
    commit_sha: str,
    pillar: str,
    tool_version: str,
    filter_version: str,
) -> tuple[int, Findings] | None:
    row = conn.execute(
        """SELECT id, payload_json FROM findings
           WHERE commit_sha = ? AND pillar = ? AND tool_version = ? AND filter_version = ?""",
        (commit_sha, pillar, tool_version, filter_version),
    ).fetchone()
    if row is None:
        return None
    return row["id"], Findings.model_validate_json(row["payload_json"])


def save_verdict(
    conn: sqlite3.Connection,
    *,
    findings_id: int,
    rubric_version: str,
    scorer_model: str,
    verdict: PillarVerdict,
) -> int:
    """Upsert by (findings_id, rubric_version, scorer_model)."""
    cur = conn.execute(
        """INSERT INTO verdicts
               (findings_id, pillar, score, confidence, abstained,
                justification, rubric_version, scorer_model, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (findings_id, rubric_version, scorer_model)
           DO UPDATE SET score = excluded.score,
                         confidence = excluded.confidence,
                         abstained = excluded.abstained,
                         justification = excluded.justification,
                         created_at = excluded.created_at
           RETURNING id""",
        (
            findings_id,
            verdict.pillar,
            verdict.score,
            verdict.confidence,
            int(verdict.abstained),
            verdict.justification,
            rubric_version,
            scorer_model,
            _now(),
        ),
    )
    row = cur.fetchone()
    conn.commit()
    return row["id"]


def load_verdict(
    conn: sqlite3.Connection,
    *,
    findings_id: int,
    rubric_version: str,
    scorer_model: str,
) -> PillarVerdict | None:
    row = conn.execute(
        """SELECT pillar, score, confidence, abstained, justification FROM verdicts
           WHERE findings_id = ? AND rubric_version = ? AND scorer_model = ?""",
        (findings_id, rubric_version, scorer_model),
    ).fetchone()
    if row is None:
        return None
    return PillarVerdict(
        pillar=row["pillar"],
        score=row["score"],
        confidence=row["confidence"],
        abstained=bool(row["abstained"]),
        justification=row["justification"],
    )


def save_budget(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    pillar: str,
    allocated: int,
    spent: int,
    excluded_files: int,
    examined_files: int,
) -> None:
    conn.execute(
        """INSERT INTO budget (run_id, pillar, allocated, spent, excluded_files, examined_files)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT (run_id, pillar) DO UPDATE SET
               allocated = excluded.allocated, spent = excluded.spent,
               excluded_files = excluded.excluded_files, examined_files = excluded.examined_files""",
        (run_id, pillar, allocated, spent, excluded_files, examined_files),
    )
    conn.commit()
