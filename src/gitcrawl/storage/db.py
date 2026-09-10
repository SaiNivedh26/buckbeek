"""SQLite connection and schema management. Plain sqlite3, no ORM — see
docs/design.md §7.2. Real columns for anything queryable (scores,
coverage, timestamps); Findings/PillarVerdict serialize into a JSON column.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

DEFAULT_DB_PATH = Path.home() / ".cache" / "gitcrawl" / "gitcrawl.db"


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open (creating if needed) the GitCrawl database and ensure the
    schema is applied. `:memory:` is accepted for tests."""
    path = db_path if db_path is not None else DEFAULT_DB_PATH
    if path != ":memory:":
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA_PATH.read_text())
    conn.commit()
    return conn
