# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

GitCrawl scores a GitHub repository against `docs/clause.md`'s rubric (Code Health 25%,
Test Coverage 20%, CI/CD 20%, Issue Management 20%, Community 15%) using agentic
investigation rather than static heuristics alone. The full design rationale — why each
architectural decision was made, not just what it is — lives in `docs/design.md`; read it
before making structural changes, especially §1 (governing principles) and §5 (the budget
design), since most non-obvious code here exists to serve one of those principles.

## Commands

```bash
uv sync                          # install/update dependencies
uv run gitcrawl survey <path|url>    # zero-token file inventory, no model calls
uv run gitcrawl evaluate <path|url>  # full pipeline; --pillar <name> for one pillar only; --json <path> to dump the Report
uv run pytest tests/ -q          # full suite (offline, no live API calls — ~41 tests, ~2s)
uv run pytest tests/test_foo.py::test_name -v   # single test
uv run ruff check src/ tests/    # lint (tests/fixtures/ is excluded — it's sample data, not our code)
uv run ruff check --fix src/ tests/
```

No live API key is required to develop or run the test suite — everything under `tests/`
is offline (mocked agents, or pure functions). A key is only needed for `gitcrawl evaluate`
against a real repo, or for the ad hoc smoke-test scripts described below.

## Architecture

A run is eight steps; six are ordinary Python, two involve a model call. See
`docs/design.md` §0 for the full vocabulary (pillar, survey, investigator, scorer, clamp,
abstain, budget) — those exact terms are used throughout the codebase and its comments.

```
source.py       resolve path/URL -> RepoHandle (pinned to a commit SHA)
survey.py       zero-token file walk -> Survey (presence flags, early clamps, ranked shortlist)
budget.py       Survey -> BudgetLedger (per-pillar tool-call allocation)
orchestrator.py wires everything below together; the only module that knows the full order
  agents/investigators.py   5 pillar-specific Agno agents, WITH tools, explore -> Findings
  agents/scorers.py         5 pillar-specific Agno agents, NO tools, judge -> PillarVerdict
  scoring/clamps.py         deterministic score ceilings from Survey facts
  scoring/aggregate.py      clause.md §2.2 weighting + abstention renormalization
storage/        SQLite cache, keyed separately for findings vs. verdicts (see below)
report.py       terminal/markdown/JSON rendering
```

**Investigators and scorers are deliberately separate agents**, not one agent that explores
and scores in the same call. This is the load-bearing design decision: an investigator's
`Findings` (observations + citations, no score) are cached independently from a scorer's
`PillarVerdict`, so changing the rubric re-runs scoring without re-reading the repo, and two
scoring runs can be diffed over identical evidence. Do not collapse these into one agent call
without re-reading `docs/design.md` §3.

**Model-owned vs. code-owned fields are split across separate schemas.** Investigator/scorer
agents are given `InvestigatorOutput`/`ScorerOutput` as their `output_schema` — never
`Findings`/`PillarVerdict` directly. `pillar` and `tool_calls_used` are always attached by
the orchestrator afterward (`Findings.from_investigator_output`,
`PillarVerdict.from_scorer_output`), never trusted from the model. This was a real bug found
via live testing: letting a model fill `pillar` produced inconsistent casing that silently
zeroed a pillar's weight in `aggregate()`, and letting a weaker model fill
`tool_calls_used: int` produced a list of strings that failed schema validation outright. If
you add a new model-facing field, ask whether the model has any business producing it, or
whether it's really plumbing that belongs in the code-owned wrapper type instead.

**`agents/model_factory.py` is the only place that knows about specific model provider
SDKs.** `investigators.py`/`scorers.py` call `build_model(cfg.models.provider, model_id)` and
never import a provider's Agno class directly. Adding a provider means adding one branch here
plus one entry in `_ENV_VARS_BY_PROVIDER` (a tuple, not a single string — Google's SDK
genuinely accepts both `GOOGLE_API_KEY` and `GEMINI_API_KEY`; match the SDK's actual accepted
names here, not just the one you expect, or a valid key sitting under the "wrong" name fails
silently — see the comment in that file for how that bug actually manifested live: silent
per-pillar abstention with zero visible error).

**Every exception in the investigate/score path is logged, never swallowed silently.**
`orchestrator.py`'s `except Exception` blocks around agent calls call `logger.exception(...)`
before degrading to an abstaining `Findings`/`PillarVerdict` — a failed investigation must
degrade gracefully, but never invisibly. If you add a new failure path here, keep that
pairing.

**Rate-limit detection checks both raised exceptions and successful-looking responses.**
Agno does not always raise on a provider 429 — confirmed live, it sometimes returns a
*successful* `RunOutput` whose `.content` is a plain string carrying the provider's error
JSON. `orchestrator._call_agent_with_retry` checks both shapes. `_retry_delay` parses a
provider's own stated wait time from the error text when present (each provider phrases it
differently — Groq: "try again in Xs", Gemini: "retry in Xs" — extend the regex/parsing
rather than assuming one provider's wording is universal) and falls back to a flat schedule
otherwise. Also rebuilds a fresh Agent per retry attempt, never reuses one across retries —
reusing carries stale conversation state into the next attempt and produces a confused,
degenerate response even though no exception is raised.

**Path confinement must operate on a fully resolved root.** `tools/repo_tools.py` calls
`.resolve()` on every path it builds before checking it's under the repo root.
`source.py`'s `_cache_dir_for` resolves the clone directory for the same reason — on macOS,
`tempfile.gettempdir()` returns the unresolved `/var/folders/...` form while `.resolve()`
elsewhere follows the `/var` → `/private/var` symlink, and an unresolved root will raise
`ValueError: ... is not in the subpath of ...` on every single tool call for a URL-cloned
repo. If you introduce a new path source (another temp dir, a different clone strategy),
resolve it at the source rather than patching every downstream `.resolve()` call site.

**`list_directory(".")` walks the whole repo and ranks across it; a specific subdirectory
lists only that directory's immediate entries.** Do not make root-level listing shallow — a
weak model given only top-level files has no way to discover `src/`, `tests/`, etc. exist at
all, which silently produced a "this repo is empty" investigation on a real repo before that
was fixed.

**Budget is enforced at the tool layer, not the agent layer.** `budget.py` allocates a
per-pillar tool-call ceiling proportional to weight × headroom (a pillar the survey already
clamped gets only `confirmation_calls`); `tools/repo_tools.py` meters every call against it
and returns an explicit `BUDGET_EXHAUSTED` marker rather than erroring. A pillar's
`stopped_reason` in `Findings` distinguishes "stopped because confident" from "stopped
because budget ran out" — both are legitimate, but mean different things for report
transparency (`docs/design.md` §5.6's scope log).

**All repo content reaching a model is wrapped as untrusted data**
(`tools/wrapping.py`), and every agent brief explicitly instructs it to treat repository
content as evidence, never as instruction. This is a real, not theoretical, concern —
`tests/fixtures/injection/` contains a fixture with a hidden `SYSTEM OVERRIDE` instruction
in its README specifically to regression-test this.

## Working with the rubric

`clause.md` is duplicated: `docs/clause.md` is the human-facing reference copy, and
`src/gitcrawl/clause.md` is the one actually read at runtime (`agents/rubric.py` loads it via
`importlib.resources` so it ships inside the installed package, not relative to whatever
directory the CLI happens to run from). If you edit the rubric, edit both, or `rubric.py`'s
tests (`tests/test_rubric.py`) and the aggregate-formula tests
(`tests/test_aggregate.py`, `tests/test_report.py`) will start asserting against a stale copy.

The weighted-score formula is `weight * score`, not `weight * (score / 10)` as `clause.md`'s
prose literally states — the prose formula is inconsistent with `clause.md`'s own worked
example (§2.2: 0.25 × 8 = 2.00, not 0.20). `scoring/aggregate.py` and `report.py` both
implement the worked-example-consistent version deliberately; see the comment in
`scoring/aggregate.py` if this ever looks like a bug.

## Fixtures

`tests/fixtures/` holds small synthetic repos used as investigation targets, not real pytest
tests — `pytest`'s `norecursedirs` and ruff's `extend-exclude` both skip it deliberately.
Each fixture is a `resolve()`-able local directory (no `.git` needed; a non-git directory
still gets a stable synthetic commit SHA). `well_tested/` has asymmetric coverage
(`src/parser.py` tested, `src/payments.py` deliberately not) specifically so an investigator
has something real to notice rather than a trivial all-or-nothing signal.

## Live model testing (ad hoc, not part of the test suite)

When verifying a provider/model combination actually works end to end (tool use +
`output_schema` together, in one agent — the riskiest assumption per `docs/design.md` §12),
write a throwaway script, run it, then delete it — these are not committed. Multiple
providers have been tried during development (see `config.toml`'s `[models]` comment for the
current one and why); each surfaced a different real failure mode (a 403 from a model outside
the account's tier, an account-wide token quota, a per-minute request quota, a model that
flatly rejects combining tool calls with structured output, a model too weak to reliably use
tools at all). Don't assume a model id or a provider's error-handling behavior — check
against the live API before trusting it in `config.toml`.
