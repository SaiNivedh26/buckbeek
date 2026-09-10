# GitCrawl

Agentic GitHub repository quality evaluator.

GitCrawl scores a repository against a five-pillar rubric — Code Health, Test
Coverage, CI/CD, Issue Management, Community — by actually investigating it, not
by pattern-matching filenames. Agents explore the repo with read-only tools,
report findings with file-path citations, and a separate scoring tier places each
pillar in a rubric band. The final score is arithmetic, never a model's summary
judgment.

The rubric lives in [`docs/clause.md`](docs/clause.md); the design rationale is in
[`docs/design.md`](docs/design.md).

## Install

```bash
uv sync
```

Then add an API key. Copy `.env.example` to `.env` and fill in the key for
whichever provider you're using:

```bash
cp .env.example .env
```

The default configuration uses Google's Gemini (`GOOGLE_API_KEY`, or
`GEMINI_API_KEY` — both are accepted). Mistral and Groq are also supported; change
`[models].provider` in `src/gitcrawl/config.toml` and set the matching key.

## Usage

### Survey — free, instant, no model calls

```bash
uv run gitcrawl survey https://github.com/psf/requests
```

Walks the file tree once and reports what's there: file counts, what was excluded
as vendored or generated, and presence flags for tests, CI, README, LICENSE. It
also fires **early clamps** — if there are no test files, Test Coverage is capped
at 2 before a single token is spent.

This costs nothing and needs no API key. On a large batch of repos it's a cheap
first pass: screen with `survey`, then spend model budget only on the survivors.

### Evaluate — the full pipeline

```bash
uv run gitcrawl evaluate https://github.com/psf/requests
uv run gitcrawl evaluate .                          # a local checkout
uv run gitcrawl evaluate . --pillar test_coverage   # one pillar only
uv run gitcrawl evaluate . --json report.json       # machine-readable output
```

Example output:

```
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Pillar           ┃ Weight ┃ Score ┃ Weighted ┃ Notes                         ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Code Health      │    25% │     9 │     2.25 │ Clean modular architecture,   │
│                  │        │       │          │ Zod schemas, low coupling     │
│ Test Coverage    │    20% │     0 │     0.00 │ No test files, no test script │
│ CI/CD            │    20% │     3 │     0.60 │ One workflow; no PR trigger,  │
│                  │        │       │          │ no tests, no lint             │
│ Issue Management │    20% │     — │        — │ not assessed                  │
│ Community        │    15% │     3 │     0.45 │ README only; no CONTRIBUTING  │
└──────────────────┴────────┴───────┴──────────┴───────────────────────────────┘

Repository Quality Score: 4.12 / 10  (80% rubric coverage)

Scope decisions
  Examined 22 of 107 files (36 excluded as vendored/generated)
  Budget: 49 / 120 tool calls used
```

The scope log is deliberate: if you think it missed something, you can see exactly
what it skipped and why. Budget is allocated per pillar by weight and headroom —
in the run above, Code Health got 48 calls while Test Coverage got 3, because the
survey had already clamped it and there was nothing left to establish.

### As a library

Everything the CLI does is importable:

```python
from gitcrawl import evaluate, survey, investigate, score

s        = survey(".")                              # no model calls
findings = await investigate(".", pillar="code_health")
verdict  = await score(findings)                    # re-score without re-reading
report   = await evaluate(".")
```

## How it works

A run is eight steps. Six are ordinary Python; two involve a model.

```
1. Resolve repo, pin to a commit SHA                     code
2. Survey: count files, set flags, allocate budget       code
3. Five investigators explore in parallel → Findings     agents
4. Cache findings to SQLite                              code
5. Five scorers: findings + rubric → scores              agents
6. Apply clamps                                          code
7. Weight, renormalize for abstentions, total            code
8. Render report                                         code
```

Three properties are worth knowing about:

**Investigation and scoring are separate.** An investigator produces observations
with citations and no score; a scorer turns those into a number. Findings are
cached independently of verdicts, so changing the rubric re-scores without
re-reading the repo, and two scoring runs can be diffed over identical evidence.

**Each pillar is investigated blind to the others.** The Test Coverage
investigator never sees the README. Models are swayed by polish, and per-pillar
isolation is what stops a good README from lifting every score.

**Missing evidence abstains rather than guessing.** Issue Management needs GitHub
API data (issues, PRs, review latency) that this phase has no tools for, so it
reports "not assessed" and the weights renormalize across what *was* assessed. The
report always states its own coverage — `80% rubric coverage` above — rather than
implying completeness.

Clamps back this up from the other direction: a countable fact overrides the model.
Zero test files caps Test Coverage at 2 no matter how confident the README is.

## Configuration

`src/gitcrawl/config.toml` holds pillar weights (matching `clause.md`), clamp
thresholds, tool-call budget, concurrency and retry settings, and model ids.
Any value can be overridden by environment variable with a `GITCRAWL_` prefix.

Rate limits are the main thing you'll tune. Free tiers are tight — the defaults
are conservative (one agent call at a time, retries with backoff). On a paid tier,
raise `max_concurrent_agent_calls` in `[concurrency]`.

## Development

```bash
uv run pytest tests/ -q          # 44 tests, fully offline — no API key needed
uv run ruff check src/ tests/
```

The test suite mocks agent calls, so it runs in about two seconds and costs
nothing. `tests/fixtures/` holds small synthetic repos used as investigation
targets — including one whose README contains a hidden instruction to score it
10/10, which regression-tests prompt-injection resistance.

See [`CLAUDE.md`](CLAUDE.md) for the non-obvious constraints before changing
anything structural.

## Status and limits

Phase 1: file-based evaluation. What that means in practice:

- **Issue Management always abstains** — it needs the GitHub API (phase 3).
- **Community is partial** — README, LICENSE and CHANGELOG are visible; stars,
  forks, contributor counts and release cadence are not.
- **CI/CD reads config, not history** — it can see whether a workflow lints and
  tests, but not its actual pass rate.
- **Scores are not yet calibrated.** Rubric bands are inherently fuzzy and models
  drift generous. Calibration against hand-scored reference repos is the intended
  next step; until then, treat the cited evidence as the trustworthy part and the
  exact number as an estimate.
- **A model that can connect isn't necessarily a model that works.** Tool use
  combined with structured output is the flakiest combination across providers —
  smoke-test a new provider or model before relying on it.
