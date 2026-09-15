"""SQLite connection and schema management. Plain sqlite3, no ORM."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

DEFAULT_DB_PATH = Path.home() / ".cache" / "gitcrawl" / "gitcrawl.db"

SCHEMA_VERSION = 2

# v1 (fixed five-pillar pipeline) tables. They only ever held cached results
# for a pipeline that no longer exists, so migrating means dropping them.
_V1_TABLES = ("verdicts", "findings", "budget", "runs", "calibration")


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open (creating if needed) the GitCrawl database, migrating an older
    schema first. `:memory:` is accepted for tests."""
    path = db_path if db_path is not None else DEFAULT_DB_PATH
    if path != ":memory:":
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < SCHEMA_VERSION:
        for table in _V1_TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.executescript(_SCHEMA_PATH.read_text())
    conn.commit()
    return conn
