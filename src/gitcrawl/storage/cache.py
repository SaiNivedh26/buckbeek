"""Cache reads and writes, each by its own key. See schema.sql for why facts
and model outputs are cached separately."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from gitcrawl.collectors.base import Fact


def _now() -> str:
    return datetime.now(UTC).isoformat()


def save_fact(
    conn: sqlite3.Connection,
    *,
    repo: str,
    commit_sha: str,
    collector: str,
    params_hash: str,
    collector_version: str,
    snapshot_bucket: str,
    fact: Fact,
) -> None:
    """Never called for an error fact (see collectors/runner.py); refuses one anyway."""
    if not fact.ok:
        raise ValueError("refusing to cache a failed fact")
    conn.execute(
        """INSERT INTO facts (repo, commit_sha, collector, params_hash, collector_version,
                              snapshot_bucket, payload_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (repo, commit_sha, collector, params_hash, collector_version, snapshot_bucket)
           DO UPDATE SET payload_json = excluded.payload_json, created_at = excluded.created_at""",
        (
            repo,
            commit_sha,
            collector,
            params_hash,
            collector_version,
            snapshot_bucket,
            fact.model_dump_json(include={"data", "citations"}),
            _now(),
        ),
    )
    conn.commit()


def load_fact(
    conn: sqlite3.Connection,
    *,
    repo: str,
    commit_sha: str,
    collector: str,
    params_hash: str,
    collector_version: str,
    snapshot_bucket: str,
) -> Fact | None:
    row = conn.execute(
        """SELECT payload_json FROM facts
           WHERE repo = ? AND commit_sha = ? AND collector = ? AND params_hash = ?
             AND collector_version = ? AND snapshot_bucket = ?""",
        (repo, commit_sha, collector, params_hash, collector_version, snapshot_bucket),
    ).fetchone()
    if row is None:
        return None
    payload = json.loads(row["payload_json"])
    return Fact(check_id="", collector=collector, data=payload["data"], citations=payload["citations"])


def save_model_output(
    conn: sqlite3.Connection,
    *,
    kind: str,
    repo: str,
    commit_sha: str,
    owner_id: str,
    input_hash: str,
    model: str,
    payload: dict,
) -> None:
    conn.execute(
        """INSERT INTO model_outputs
               (kind, repo, commit_sha, owner_id, input_hash, model, payload_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (kind, repo, commit_sha, owner_id, input_hash, model)
           DO UPDATE SET payload_json = excluded.payload_json, created_at = excluded.created_at""",
        (kind, repo, commit_sha, owner_id, input_hash, model, json.dumps(payload), _now()),
    )
    conn.commit()


def load_model_output(
    conn: sqlite3.Connection,
    *,
    kind: str,
    repo: str,
    commit_sha: str,
    owner_id: str,
    input_hash: str,
    model: str,
) -> dict | None:
    row = conn.execute(
        """SELECT payload_json FROM model_outputs
           WHERE kind = ? AND repo = ? AND commit_sha = ? AND owner_id = ? AND input_hash = ? AND model = ?""",
        (kind, repo, commit_sha, owner_id, input_hash, model),
    ).fetchone()
    return None if row is None else json.loads(row["payload_json"])
