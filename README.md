# GitCrawl

Evaluate a GitHub repository against **your own rubric**.

You write the rubric as a `clause.md`: pillars, weights, criteria, score bands and hard
rules. GitCrawl turns it into an **Evaluation Plan** that you review and approve. Then it
evaluates any GitHub repository with that plan:

- **Tested collectors** gather facts deterministically, from repository files and the GitHub API.
- **Agents** answer only the questions that genuinely need judgement.
- **Code** decides caps, abstentions and the final arithmetic.

A default rubric and plan are bundled, so it works out of the box.

## Install

```bash
uv sync
cp .env.example .env
```

Add two keys to `.env`:

| Key | Needed for | Where |
|---|---|---|
| `GOOGLE_API_KEY` (or `GEMINI_API_KEY`) | `plan`, `evaluate` | Google AI Studio, free tier |
| `GITHUB_TOKEN` | GitHub data (issues, PRs, contributors, releases, CI runs) | GitHub → Settings → Developer settings → Fine-grained tokens, read-only public repositories |

Mistral and Groq are also supported: change `[models].provider` in `src/gitcrawl/config.toml`.

## Usage

```bash
# Facts only: collectors, no model calls, no cost
uv run gitcrawl facts imbaraniii/relink

# Evaluate with the bundled rubric and plan
uv run gitcrawl evaluate https://github.com/imbaraniii/relink

# Your own rubric
uv run gitcrawl plan my_clause.md -o my_plan.yaml     # one model call: draft plan
uv run gitcrawl plan approve my_plan.yaml             # after reviewing it
uv run gitcrawl evaluate owner/repo --plan my_plan.yaml
```

`evaluate` prints a score table, then a few lines per pillar explaining how the score was reached:
- the reasoning;
- any hard rule that capped the score;
- criteria that weren't measurable;
- whether the repository tried to influence its own evaluation.

`--json report.json` also writes the full report, including every fact and judgement.

See [`docs/clause.md`](docs/clause.md) for how to write a rubric.

## How it works

```
PLAN (once per clause.md)                          EVALUATE (per repository)
clause.md → parse (code) → planner (model)         preflight: plan approved and valid? (code)
  → validate (code) → plan.yaml                    → collectors: facts (code, cached)
  → you review → plan approve                      → hard rules: cap / not assessed (code)
                                                   → judgement agents (models + tools)
                                                   → pillar scorers (models, isolated)
                                                   → caps, abstention, weighted total (code)
```

**Each criterion in your rubric becomes one of three things:**
- **Measured:** backed by a collector, for example `ci.config`, `tests.mapping` or `github.issues`.
- **Judgement:** a focused question for an agent, for example "are the tests meaningful?".
- **Not measurable:** excluded from the score with a stated reason, never guessed.

**Agents are grouped by the evidence they need, not by pillar.** One agent reads test code for
every test-related question, so files aren't re-read across pillars. Scorers stay one per pillar,
so a strong pillar can't lift a weak one.

**Deterministic where it must be.** The planner can only choose collectors and fill in their
parameters. It never writes code. Hard rules are small expressions that code parses and evaluates.
Only the band and score within a pillar come from a model, and code still enforces the caps
afterwards.

**Checked evidence.** An agent's citations are compared with the files and threads it actually
opened, and unverified citations are reported.

**Collectors** (see `gitcrawl facts`):

| Area | Collectors |
|---|---|
| Files | `repo.inventory`, `file.exists`, `file.count`, `file.contains`, `manifest.field` |
| CI | `ci.config` (follows reusable workflows, composite actions, package scripts, Makefile targets) |
| Tests | `tests.inventory`, `tests.mapping` (static test→source mapping), `tests.coverage` |
| Code | `code.structure`, `code.imports` |
| GitHub API | `github.repo`, `github.issues`, `github.pull_requests`, `github.contributors`, `github.releases`, `github.workflow_runs` |

Design rationale: [`docs/design.md`](docs/design.md).

## Configuration

`src/gitcrawl/config.toml` holds:
- model ids;
- requests-per-minute pacing per provider;
- agent tool budgets per evidence domain;
- GitHub API windows;
- cache TTLs.

Any value can be overridden with a `GITCRAWL_` environment variable, for example
`GITCRAWL_MODELS__SCORER`. The rubric itself is never configured here: it comes from `clause.md`.

Results are cached in `~/.cache/gitcrawl/gitcrawl.db`.
- **Repeat runs:** served from cache.
- **Facts from files:** keyed by commit.
- **GitHub facts:** refreshed daily.
- **Model outputs:** keyed by their exact inputs.
- **Failures:** never cached.

## Development

```bash
uv run pytest tests/ -q        # fully offline: agents and GitHub are mocked
uv run ruff check src/ tests/
```

`tests/fixtures/` holds small synthetic repositories. `ci_rich/` has real CI (a reusable workflow,
a coverage gate, a Makefile lint target) and a deliberately untested module. `injection/` has a
README that asks evaluators for 10/10.

See [`CLAUDE.md`](CLAUDE.md) before changing anything structural.

## Limits

- **GitHub repositories only.**
- **Scores are not calibrated yet.** Treat the cited facts as the trustworthy part and the exact
  number as an estimate.
- **Test mapping is static.** It shows which modules any test imports or is named after, not
  runtime coverage. Runtime coverage is only reported when a coverage report is committed.
- **Adoption signals are not measurable.** Dependents and blog mentions aren't available, so the
  default rubric reports them as excluded.
