# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

GitCrawl evaluates a **GitHub repository** against a **user-supplied rubric** (`clause.md`, fixed
template). A planner model compiles the rubric into an **Evaluation Plan** (YAML) that a person
reviews and approves. Evaluation then executes the plan:

deterministic collectors → hard rules (code) → judgement agents → isolated per-pillar scorers →
caps, abstention and weighted total (code).

Design rationale is in `docs/design.md`; read it before structural changes. Rubric authoring is
in `docs/clause.md`. Current state and open issues are in `HANDOFF.md`.

## Commands

```bash
uv sync
uv run gitcrawl facts <owner/repo> [--plan plan.yaml]      # collectors only, zero model calls
uv run gitcrawl plan [clause.md] -o plan.yaml             # one model call: draft plan
uv run gitcrawl plan approve plan.yaml                    # re-validates, stamps approval
uv run gitcrawl evaluate <owner/repo> [--plan plan.yaml] [--clause clause.md] [--json out.json]
uv run pytest tests/ -q                                   # fully offline
uv run pytest tests/test_engine.py::test_name -v
uv run ruff check src/ tests/                             # tests/fixtures/ is excluded
uv run python scripts/build_default_plan.py src/gitcrawl/defaults/plan.yaml   # regenerate bundled plan
```

**Keys** (in `.env`):
- **Model provider key:** needed for `plan` and `evaluate`.
- **`GITHUB_TOKEN`** (or `GH_TOKEN`): needed for any plan that uses GitHub collectors or tools,
  and the bundled default plan does. `facts` runs without one and marks GitHub facts unavailable.
- **Tests:** need neither key.

**Cache:** `~/.cache/gitcrawl/gitcrawl.db`.
- Tables: `facts` and `model_outputs`.
- Schema v2: `storage/db.py` drops the v1 tables on first connect.
- Failures are never cached.

## Architecture

```
source.py            GitHub URL/owner-repo → RepoHandle (blobless clone, pinned SHA). local_handle() for tests.
rubric/              clause.md template parser. Code owns names, weights, bands, criteria text.
defaults/            bundled clause.md, clause.template.md, plan.yaml (pre-approved)
collectors/          deterministic facts
  base.py            @collector registry, Fact, run_check (errors → Fact.error, logged)
  files.py           RepoFiles: memoized walk + reads, exclusions, path confinement
  runner.py          collect(): dedupe by (collector, params), cache, never cache failures
  inventory, generic, ci, tests, code, github_api, sources (shared language/import helpers)
github/              httpx client (GraphQL + REST, memoized, typed errors, rate limits), queries
plan/                models, rules (safe expression DSL), validate, agents (grouping), planner, io
agents/              judge (judgement agents), pillar_scorer, runner (429 retry), limiter, evidence, model_factory
tools/               repo_tools, github_tools (async), filters, wrapping
engine.py            the ONLY module that knows the full evaluation order; collect_facts()
results.py           EvaluationReport / PillarResult / Scope
scoring/aggregate.py weight × score, renormalized over non-abstained pillars
report.py, cli.py    rendering and a thin CLI
```

### Non-obvious rules — each exists because of a real failure or a design constraint

**"Deterministic agents" are collectors plus the rules DSL, never model-written code.**
- The planner can only pick registered collectors and fill in params, which are validated
  against each collector's params model.
- Hard rules are parsed with `ast` against a node whitelist in `plan/rules.py`. Never `eval`
  them, and don't widen the whitelist to calls, subscripts or arithmetic.
- A rule whose facts are missing is *undetermined* (reported). It neither fires nor passes.

**Code-owned vs model-owned fields.** v1 lesson: a model echoing "Test Coverage" for
`test_coverage` silently zeroed a pillar's weight.
- **Planner (`PlannerOutput`):** proposes mappings only.
- **Code (`merge_planner_output`):** assigns criterion and rule ids, and copies names, weights,
  bands and text from the parsed rubric.
- **Code (`compute_agents`):** computes agents.
- **Judges and scorers:** only answer and score. Their outputs are mapped onto plan ids by code.
- If you add a model-facing field, ask whether it's really plumbing.

**`validate_plan` runs at plan time, at approval, and again in `engine.preflight`.**
- A hand-edited plan, or one written against an older collector catalog, is caught before
  anything runs.
- The approval hash (`EvaluationPlan.content_hash`) excludes `approved`, `approved_hash`,
  `created_at` and `rubric_path`. Any other edit un-approves the plan.

**Changing a collector's output fields.**
- Bump its `version=`, which invalidates its cached facts.
- Check the bundled plan: `tests/test_default_plan.py` fails if it no longer validates.
  Regenerate it with `scripts/build_default_plan.py`.

**Code decides, not prompts.**
- An abstain rule skips that pillar's judgement tasks and scorer.
- A cap is enforced after the scorer answers.
- A pillar with no usable evidence abstains without a scorer call.
- None of this is decided by a prompt.

**Failures are logged and never cached.**
- Every `except Exception` around agents and collectors calls `logger.exception` (or
  `logger.warning` for an expected `CollectorError`) before degrading.
- Error facts, judgement results with unanswered tasks, and failed scorers are not saved.
- Keep that pairing on any new failure path.

**Citations are verified.**
- `BudgetLedger.read_paths` records what each agent actually read: `read_file`, files matched by
  `search_repo`, `issues/N`, `pulls/N`, `releases/TAG`.
- `verify_answers` flags citations outside that log and the facts the agent was shown.

**Rate limits.**
- `agents/limiter.py` paces requests before each `arun`, and before each tool call via a tool
  hook, because Agno makes a model request after every tool call.
- `agents/runner.call_agent` retries 429s in both shapes: a raised exception, and a successful
  run whose `.content` is the provider's error JSON (confirmed live).
- It parses the provider's stated wait: Groq "try again in Xs", Gemini "retry in Xs".
- It builds a fresh Agent per attempt; reusing one produced degenerate output with no error.

**Async tools need async hooks.**
- `tools/github_tools.py` tools are coroutines. Agno awaits an async hook, but a sync hook around
  an async tool would return an un-awaited coroutine.
- Repo tools are sync with sync hooks.

**`agents/model_factory.py` is the only place that knows provider SDKs.**
- `_ENV_VARS_BY_PROVIDER` holds tuples. Google accepts both `GOOGLE_API_KEY` and `GEMINI_API_KEY`.
- Gating stricter than the SDK caused silent failures before.

**Never write tool names with call syntax in prompts or planner questions.**
- Write "use the read_file tool", not `read_file(...)`. A weak model called a tool literally named
  `list_directory(".")`.
- `validate_plan` rejects judgement questions containing call syntax.
- `tests/test_engine.py` and `tests/test_planner.py` guard the briefs.

**Path confinement uses fully resolved roots.**
- `source._cache_dir_for` resolves the clone dir: on macOS the `/var` → `/private/var` symlink
  otherwise breaks every confinement check.
- `RepoFiles.resolve` and `repo_tools._resolve_confined` resolve before checking.

**`list_directory(".")` walks the whole repo, ranked.**
- Don't make it shallow: a weak model once concluded a repo was empty.

**Untrusted content.**
- All repository- and GitHub-derived text reaching a model is wrapped by `tools/wrapping.py`.
  That includes facts rendered into prompts and issue or PR threads.
- Briefs say to treat it as data. `tests/fixtures/injection/` exists for this.

**Weighted formula is `weight × score`,** matching the rubric's worked example (0.25 × 8 = 2.00),
not the prose `weight × score/10`. See `scoring/aggregate.py`.

**Don't name non-test helpers `test_*`.**
- pytest collects imported functions whose names start with `test_`, as happened with
  `collectors/sources.py`.

### Known gaps (details in HANDOFF.md)
- **No live end-to-end run yet.** `plan` and `evaluate` have not run with real models and a
  GitHub token; only offline tests plus a tokenless `facts` run on relink.
- **Planner untested on a real model.** Gemini's reliability with nested `PlannerOutput` is unverified.
- **Async hook path unverified live.** For GitHub tools it was verified against Agno's source only.
- **Scores are uncalibrated.**
- **`tests.mapping` is static.** It skips Rust, Java and other unmapped languages, but reports them.
- **Contributors are capped at 100.** The collector reads only the endpoint's first page.

## Fixtures

`tests/fixtures/` holds synthetic repos, not pytest tests; pytest `norecursedirs` and ruff
`extend-exclude` skip them.
- **`ci_rich/`:** reusable workflow, composite action, `make lint`, a script-run `pip-audit`,
  `--cov-fail-under`, `lcov.info`; `src/payments.py` is deliberately untested.
- **`well_tested/`:** asymmetric test coverage.
- **`no_tests/`:** no tests and no CI.
- **`vendored_heavy/`:** exclusion rules.
- **`injection/`:** a hidden instruction in its README.

## Live model testing (ad hoc, not in the suite)

- **Throwaway scripts:** to verify a provider or model end to end (tool use plus `output_schema`
  in one agent, and the planner's nested schema), write a throwaway script, run it, then delete it.
- **Real failures seen:** 403 outside the account tier, account token quotas, per-minute quotas,
  tools combined with JSON mode rejected, and models too weak to use tools.
- **Don't assume:** never assume a model id or a provider's error behavior. Check the live API first.
