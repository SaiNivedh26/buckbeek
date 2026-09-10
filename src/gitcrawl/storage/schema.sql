-- GitCrawl storage schema. See docs/design.md §7.2.
--
-- findings and verdicts are separate tables on purpose: they have
-- different cache keys and different invalidation triggers. A rubric
-- change invalidates every verdict but every finding is still valid,
-- because the investigator's job (look around) didn't change — only the
-- scorer's job (judge against a rubric band) did. Collapsing these into
-- one JSON blob per run loses that property.

CREATE TABLE IF NOT EXISTS runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    repo                TEXT NOT NULL,
    commit_sha          TEXT NOT NULL,
    rubric_version      TEXT NOT NULL,
    config_hash         TEXT NOT NULL,
    investigator_model  TEXT NOT NULL,
    scorer_model        TEXT NOT NULL,
    started_at          TEXT NOT NULL,
    total_score         REAL,
    rubric_coverage     REAL
);

-- Cache key: (commit_sha, pillar, tool_version, filter_version).
-- Invalidated by: the repo changing, or the tool/filter layer changing.
-- NOT invalidated by a rubric or model change — that's the whole point.
CREATE TABLE IF NOT EXISTS findings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER REFERENCES runs(id),
    commit_sha      TEXT NOT NULL,
    pillar          TEXT NOT NULL,
    payload_json    TEXT NOT NULL,       -- the Findings model, serialized
    evidence_coverage REAL NOT NULL,
    stopped_reason  TEXT NOT NULL,
    tool_version    TEXT NOT NULL,
    filter_version  TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE (commit_sha, pillar, tool_version, filter_version)
);

-- Cache key: (findings_id, rubric_version, scorer_model).
-- Invalidated by: a rubric edit, or a scorer model swap. NOT by the repo
-- changing — that's the findings row's job.
CREATE TABLE IF NOT EXISTS verdicts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    findings_id     INTEGER NOT NULL REFERENCES findings(id),
    pillar          TEXT NOT NULL,
    score           REAL,
    confidence      REAL NOT NULL,
    abstained       INTEGER NOT NULL,     -- 0/1
    justification   TEXT NOT NULL,
    rubric_version  TEXT NOT NULL,
    scorer_model    TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE (findings_id, rubric_version, scorer_model)
);

CREATE TABLE IF NOT EXISTS budget (
    run_id          INTEGER NOT NULL REFERENCES runs(id),
    pillar          TEXT NOT NULL,
    allocated       INTEGER NOT NULL,
    spent           INTEGER NOT NULL,
    excluded_files  INTEGER NOT NULL,
    examined_files  INTEGER NOT NULL,
    PRIMARY KEY (run_id, pillar)
);

-- Phase 4: hand-scored repos used to check GitCrawl's ordering matches a
-- human's. Populated manually, read by the calibration smoke test.
CREATE TABLE IF NOT EXISTS calibration (
    repo        TEXT NOT NULL,
    hand_score  REAL NOT NULL,
    pillar      TEXT NOT NULL,
    notes       TEXT,
    PRIMARY KEY (repo, pillar)
);

CREATE INDEX IF NOT EXISTS idx_findings_commit ON findings(commit_sha);
CREATE INDEX IF NOT EXISTS idx_verdicts_findings ON verdicts(findings_id);
CREATE INDEX IF NOT EXISTS idx_runs_repo ON runs(repo);
