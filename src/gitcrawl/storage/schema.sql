-- GitCrawl cache schema (version 2). See storage/db.py for the migration
-- from the v1 fixed-pillar tables.
--
-- Two caches with different invalidation, on purpose:
--   facts          deterministic collector results
--   model_outputs  judgement-agent answers and pillar-scorer scores
-- A rubric or plan change re-runs only the model outputs whose inputs changed;
-- the facts they read are still valid. Failed results are never stored.

-- One collector result. File collectors use snapshot_bucket = '' (keyed by
-- commit alone); GitHub collectors use a time bucket, because issues, PRs and
-- CI runs change without the commit changing.
CREATE TABLE IF NOT EXISTS facts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    repo                TEXT NOT NULL,
    commit_sha          TEXT NOT NULL,
    collector           TEXT NOT NULL,
    params_hash         TEXT NOT NULL,
    collector_version   TEXT NOT NULL,
    snapshot_bucket     TEXT NOT NULL,
    payload_json        TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    UNIQUE (repo, commit_sha, collector, params_hash, collector_version, snapshot_bucket)
);

-- input_hash covers the full prompt (facts and answers included) plus the
-- agent spec, so any change in evidence, plan or prompt text is a cache miss.
CREATE TABLE IF NOT EXISTS model_outputs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL,          -- 'judgement' | 'score'
    repo            TEXT NOT NULL,
    commit_sha      TEXT NOT NULL,
    owner_id        TEXT NOT NULL,          -- agent id or pillar id
    input_hash      TEXT NOT NULL,
    model           TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE (kind, repo, commit_sha, owner_id, input_hash, model)
);
