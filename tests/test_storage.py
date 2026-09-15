import sqlite3

import pytest

from gitcrawl.collectors.base import Fact
from gitcrawl.storage import cache, db

FACT_KEY = {
    "repo": "acme/widget",
    "commit_sha": "abc",
    "collector": "ci.config",
    "params_hash": "p1",
    "collector_version": "1",
    "snapshot_bucket": "",
}
OUTPUT_KEY = {
    "kind": "score",
    "repo": "acme/widget",
    "commit_sha": "abc",
    "owner_id": "ci_cd",
    "input_hash": "h1",
    "model": "m",
}


def test_fact_round_trip_and_key_sensitivity():
    conn = db.connect(":memory:")
    fact = Fact(
        check_id="ci", collector="ci.config", data={"has_ci": True}, citations=[".github/workflows/ci.yml"]
    )
    cache.save_fact(conn, **FACT_KEY, fact=fact)

    loaded = cache.load_fact(conn, **FACT_KEY)
    assert loaded.data == {"has_ci": True} and loaded.citations == [".github/workflows/ci.yml"]
    assert cache.load_fact(conn, **{**FACT_KEY, "collector_version": "2"}) is None
    assert cache.load_fact(conn, **{**FACT_KEY, "snapshot_bucket": "123"}) is None


def test_failed_fact_is_refused():
    conn = db.connect(":memory:")
    with pytest.raises(ValueError, match="failed fact"):
        cache.save_fact(conn, **FACT_KEY, fact=Fact(check_id="ci", collector="ci.config", error="boom"))


def test_model_output_round_trip_and_upsert():
    conn = db.connect(":memory:")
    cache.save_model_output(conn, **OUTPUT_KEY, payload={"score": 4, "reasoning": "v1"})
    cache.save_model_output(conn, **OUTPUT_KEY, payload={"score": 5, "reasoning": "v2"})
    assert cache.load_model_output(conn, **OUTPUT_KEY) == {"score": 5, "reasoning": "v2"}
    assert cache.load_model_output(conn, **{**OUTPUT_KEY, "input_hash": "other"}) is None


def test_v1_database_is_migrated(tmp_path):
    path = tmp_path / "gitcrawl.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE findings (id INTEGER PRIMARY KEY, payload_json TEXT)")
    old.execute("INSERT INTO findings (payload_json) VALUES ('{}')")
    old.commit()
    old.close()

    conn = db.connect(path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "findings" not in tables
    assert {"facts", "model_outputs"} <= tables
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
