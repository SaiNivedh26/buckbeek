# Writing an evaluation clause (`clause.md`)

A `clause.md` is the rubric GitCrawl evaluates repositories against. You decide what matters:
the pillars, their weights, the criteria inside each pillar, what each score band means, and
any hard limits. GitCrawl turns it into an **Evaluation Plan** you review and approve, then
applies that same plan to every repository you evaluate.

This guide covers the exact format, how each part is used, what GitCrawl can and cannot
measure, and how to write a clause that produces consistent, defensible scores.

- Blank template: [`src/gitcrawl/defaults/clause.template.md`](../src/gitcrawl/defaults/clause.template.md)
- Bundled default clause: [`src/gitcrawl/defaults/clause.md`](../src/gitcrawl/defaults/clause.md)

---

## 1. How a clause is used

```
clause.md ──► parse (code) ──► planner (1 model call) ──► plan.yaml ──► you review ──► approve
                                                                                          │
                          report ◄── scores ◄── agents + scorers ◄── facts ◄── evaluate ◄─┘
```

| Part of the clause | Read by | Used for |
|---|---|---|
| Title, version, pillar names, weights, bands | **Code**, exactly as written | Report headings, the weighted total, what the scorer chooses between |
| Criteria | **The planner model** | Deciding how each one is evaluated: measured by facts, judged by an agent, or not measurable |
| Hard rules | **The planner model** writes an expression; **code** enforces it | Caps and "not assessed" decisions a model cannot override |
| Focus | The scorer | Context for the pillar |

The scorer never sees your whole clause. Each pillar is scored in isolation from its own
bands, its own criteria, and the evidence gathered for those criteria.

---

## 2. The template

```markdown
# <Rubric title>
Version: 1.0

## Pillar: <Pillar name>
Weight: 25%
Focus: <one line, optional>

### Criteria
- <one checkable or judgeable statement per line>

### Bands
- 0-2: <what a very poor repository looks like>
- 3-5: <below average>
- 6-8: <good>
- 9-10: <excellent>

### Hard rules
- If <condition>, score is at most <N>.
- If <condition>, the pillar is not assessed.
```

Repeat the `## Pillar:` block for every pillar. `### Hard rules` is optional.

---

## 3. Format rules

The parser is strict. It rejects a clause that breaks these rules and lists **every** problem
at once, so you can fix the file in one pass.

| Element | Rule | Example |
|---|---|---|
| Title | A line starting with `# ` (one `#`) | `# Library Readiness` |
| Version | `Version: <text>` on its own line | `Version: 1.2` |
| Pillar | `## Pillar: <name>`; names must be distinct | `## Pillar: CI/CD` |
| Weight | `Weight: N%` inside the pillar, **before** its first `###` subsection; decimals allowed | `Weight: 12.5%` |
| Weights total | All pillar weights must add up to exactly 100% | 25 + 20 + 20 + 20 + 15 |
| Focus | Optional `Focus: <text>`, one line, before the first `###` | `Focus: Release hygiene.` |
| Subsections | Only `### Criteria`, `### Bands`, `### Hard rules` (case doesn't matter) | `### Bands` |
| Criteria | At least one bullet per pillar; `- ` or `* ` bullets | `- A LICENSE file exists.` |
| Bands | Every bullet must be `low-high: description` with whole numbers 0–10 | `- 3-5: Some tests.` |
| Band coverage | Bands must start at 0, end at 10, and leave no gaps or overlaps | `0-2`, `3-5`, `6-8`, `9-10` |

### Pitfalls the parser won't warn you about

- **One bullet = one line.** A criterion that wraps onto a second line keeps only its first line;
  the continuation is silently dropped. Keep every criterion and band on a single line.
- **No bullets inside comments within a section.** `<!-- -->` comments are fine above the first
  pillar, but a `- ` line inside a comment under `### Criteria` is read as a criterion.
- **Pillar ids come from names.** `CI/CD` becomes `ci_cd`. Two names that reduce to the same id
  (`CI CD` and `CI/CD`) are rejected as duplicates.
- **Any edit changes the rubric's identity.** Even rewording one band means existing plans no
  longer match the clause. Re-run `gitcrawl plan` after editing.

---

## 4. Designing pillars

**Pick 3–7 pillars.** Fewer and the score says little; more and each pillar gets too little
weight to matter and too little evidence to judge.

**Make pillars independent.** Each piece of evidence should count in one pillar. "CI runs the
tests" can belong to Test Coverage *or* CI/CD, but in both it is counted twice.

**Weight by importance to your decision, not by how easy it is to measure.** Weights are
fractions of the final score: `weight × score` per pillar, summed.

**Write a focus line.** One sentence on what the pillar is about gives the scorer context when
the criteria alone are ambiguous.

---

## 5. Writing criteria

Criteria are the most important part of a clause. **The planner only gathers evidence for what
your criteria say.** Anything that appears only in your bands will be scored without evidence.

### The five rules of a good criterion

1. **One idea per criterion.** "Tests exist and are meaningful" is two criteria, measured
   completely differently (a file count vs. reading test code).
2. **Observable.** Say what should be true of the repository, not how good something "feels".
3. **Covers what the bands grade.** If any band mentions coupling, review speed or release
   cadence, a criterion must ask about it.
4. **Specific where it matters.** Replace "regular", "good", "frequent" with a threshold when you
   care about consistency: "a release in the last 6 months", "most PRs reviewed before merge".
5. **Says what, not where to look.** "Pipelines run on every pull request", not "check
   `.github/workflows/*.yml`". Choosing evidence is the planner's job.

### Good vs. weak criteria

| Weak | Why it's weak | Better |
|---|---|---|
| CI quality is high. | Not observable | CI runs lint, tests and a security scan on every pull request. |
| Tests exist and are good. | Two ideas, one vague | Automated tests exist. / Tests are meaningful rather than trivial smoke tests. |
| Key files show well-organized, readable code. | Bundles many files and qualities | The directory structure follows a recognizable architecture. / Code is readable, and non-obvious parts are documented. |
| Coverage reports show the level of coverage. | No expectation | Coverage is measured: a coverage report, badge, or enforced threshold exists. |
| Response times are good. | Undefined, mixes issues and PRs | Maintainers respond to new issues promptly. / Pull requests are reviewed before merging. |
| Check .github/workflows for triggers. | An instruction, not a criterion | Pipelines run on every push and pull request. |
| Static analysis shows few issues. | GitCrawl runs no linters (not measurable) | CI runs a linter on every pull request. |

### How the planner classifies each criterion

| Status | When | What happens |
|---|---|---|
| **measured** | A collector's facts answer it directly | Facts are shown to the scorer |
| **judgement** | It needs reading and judging | An agent answers a focused question, citing what it read; citations are verified |
| **not measurable** | No available data can answer it | Excluded from the score and listed in the report, never guessed |

A criterion marked **not measurable** is honest, not a failure. When you see one in the plan,
either accept it or reword the criterion into something GitCrawl can check.

---

## 6. What GitCrawl can measure

Write criteria in terms of these capabilities and most of your clause will be **measured** rather
than judged, which makes scores consistent from run to run.

### Repository files

| You can ask about | Example criterion | Facts behind it |
|---|---|---|
| Community and policy files | A README, LICENSE and CONTRIBUTING guide exist. | `repo.inventory`: `has_readme`, `has_license`, `has_contributing`, `has_changelog`, `has_code_of_conduct`, `has_security_policy`, `has_issue_templates`, `has_pr_template` |
| Any specific file | A `SECURITY.md` or `.github/dependabot.yml` exists. | `file.exists` (globs), `file.count` |
| Text inside files | The README documents installation. | `file.contains` (globs + regex) |
| A manifest value | `package.json` defines a test script. | `manifest.field` (any JSON / TOML / YAML key) |

### CI configuration

| You can ask about | Facts |
|---|---|
| CI exists; which systems | `ci.config`: `has_ci`, `systems`, `unparsed_systems` |
| Triggers | `triggers_push`, `triggers_pull_request`, `triggers_schedule` |
| Steps | `has_lint_step`, `has_test_step`, `has_security_step`, `has_build_step`, `has_deploy_step`, `has_coverage_step` |
| Gates | `coverage_threshold_enforced`, `tests_run_on_pull_request` |
| Dependency updates | `uses_dependabot` |

GitHub Actions is parsed fully, following reusable workflows, composite actions, `npm`/`yarn`/`bun`
scripts, Makefile targets and repo-local shell scripts. GitLab CI is parsed for job scripts.
CircleCI, Jenkins, Travis, Azure Pipelines and others are detected but not parsed.

### Tests and coverage

| You can ask about | Facts |
|---|---|
| Tests exist; how many; unit / integration / e2e split | `tests.inventory`: `test_file_count`, `test_to_source_ratio`, `unit_test_files`, `integration_test_files`, `e2e_test_files`, `frameworks`, `has_test_command` |
| Which modules tests reach | `tests.mapping`: `tested_share`, `tested_modules`, `untested_module_paths` |
| Coverage evidence | `tests.coverage`: `line_coverage_percent`, `threshold_configured`, `threshold_percent`, `coverage_collected_in_ci`, `coverage_badge` |

`tests.mapping` is static: a module counts as tested when a test imports it or is named after
it. It supports Python, JavaScript/TypeScript and Go; other languages are reported as unmapped.
Line coverage is only known when a coverage report is committed.

### Code structure

| You can ask about | Facts |
|---|---|
| Size and "god" files | `code.structure`: `source_files`, `max_file_lines`, `files_over_500_lines`, `files_over_1000_lines`, `largest_files` |
| Documentation density | `comment_line_share`, `python_docstring_share` |
| Coupling | `code.imports`: `most_imported`, `highest_fan_out`, `import_cycle_count` (Python and JS/TS) |

Architecture, duplication and readability are **judgement**: an agent reads representative
files, guided by these facts.

### GitHub API (needs `GITHUB_TOKEN`)

| You can ask about | Facts |
|---|---|
| Adoption and activity | `github.repo`: `stars`, `forks`, `watchers`, `days_since_last_push`, `commits_last_90_days`, `license`, `is_archived` |
| Issue health | `github.issues`: `close_rate`, `stale_open_share`, `median_days_to_close`, `median_hours_to_first_maintainer_response`, `maintainer_response_share`, `labelled_share`, `milestone_share` |
| Pull request workflow | `github.pull_requests`: `merge_rate`, `median_hours_to_first_review`, `reviewed_before_merge_share`, `merged_without_review_share`, `external_pr_response_share`, `median_days_to_merge` |
| Contributor base | `github.contributors`: `contributor_count`, `top_contributor_share`, `top3_share`, `contributors_with_10_plus_commits` |
| Releases | `github.releases`: `release_count`, `latest_release_days_ago`, `releases_last_365_days`, `median_days_between_releases`, `with_notes_share` |
| CI reliability | `github.workflow_runs`: `success_rate`, `first_attempt_success_rate`, `default_branch_success_rate`, `default_branch_failure_streak`, `last_run_days_ago` |

API metrics use bounded recent windows (the 50 most recent issues and PRs, the 25 oldest open
issues, the last 10 releases, the last 50 workflow runs), never the full history. Response times
count only replies from maintainers (owners, members, collaborators) to people who aren't.

### Needs judgement (an agent reads and answers)

- Architecture, separation of concerns, duplication, readability
- Whether tests are meaningful, well structured, cover edge cases
- Quality of README, contributing guide, changelog and release notes
- Tone and helpfulness of issue and pull request discussion

### Not measurable today

Criteria about these are excluded from the score and reported as not measured:

- External adoption: dependents, downloads, tutorials, talks, blog posts
- Static analysis results or linter warnings (GitCrawl doesn't run linters)
- Runtime test coverage when no coverage report is committed
- GitHub Projects boards, security advisories and Dependabot alerts
- Anything outside the repository and its public GitHub data (deployments, uptime, user reviews)

---

## 7. Writing bands

Bands tell the scorer what each range of scores looks like. The scorer picks a band, then a
score inside it.

1. **Mirror your criteria.** Every quality a band describes should be a criterion, and every
   criterion should show up somewhere in the bands.
2. **Use 3–5 bands.** `0-2`, `3-5`, `6-8`, `9-10` works for most pillars.
3. **Make each band distinguishable.** Two adjacent bands should differ on something observable,
   not only in adjectives ("good" vs. "very good").
4. **Describe absence at the bottom.** The lowest band should describe what's missing or broken.
5. **Keep the top band reachable.** If no real repository could reach 9–10, scores compress into
   the middle and stop discriminating.
6. **One line per band.** Separate multiple descriptors with periods or semicolons.

```markdown
### Bands
- 0-2: No tests, or only trivial smoke tests; core logic untested.
- 3-5: Some unit tests on a few modules; no coverage measurement.
- 6-8: Most core modules tested; coverage measured; tests meaningful and mostly reliable.
- 9-10: Nearly all modules tested; enforced coverage threshold; unit, integration and end-to-end tests.
```

---

## 8. Writing hard rules

Hard rules are limits enforced by **code**, whatever the scorer concludes. Use them for
absolutes, where the answer is a countable fact and no amount of good evidence elsewhere should
change it.

### Two forms

```markdown
- If <condition>, score is at most <N>.        # cap
- If <condition>, the pillar is not assessed.  # abstain: pillar excluded, weight renormalized
```

### Good hard rules

| Hard rule | Expression the planner writes |
|---|---|
| If the repository has no test files, score is at most 2. | `tests_inventory.test_file_count == 0` → cap 2 |
| If the repository has no CI configuration, score is at most 2. | `not ci_config.has_ci` → cap 2 |
| If every recent CI run failed, score is at most 2. | `workflow_runs.completed_runs > 0 and workflow_runs.success_rate == 0` → cap 2 |
| If the repository has no license, score is at most 3. | `not inventory.has_license` → cap 3 |
| If the repository has a single contributor, score is at most 5. | `contributors.contributor_count <= 1` → cap 5 |
| If issues are disabled, the pillar is not assessed. | `github_repo.has_issues_enabled == false` → abstain |

### Guidelines

- **Base the condition on a fact from section 6.** The expression can only use those fields,
  combined with comparisons, `and`, `or` and `not`. A rule about "poor architecture" can't be
  enforced by code; put it in the bands instead.
- **Keep them few.** One or two per pillar at most. Every rule overrides judgement.
- **Match your bands.** If the 0–2 band says "no tests", a cap of 2 for "no test files" keeps the
  rule and the band consistent.
- **Use "not assessed" only when scoring would be meaningless,** not as a penalty.
- **Missing facts don't fire rules.** If a fact is unavailable (for example no GitHub token), the
  rule is reported as not checked. It never silently passes or fails.

---

## 9. A complete example

```markdown
# Library Maintenance Readiness
Version: 1.0

## Pillar: Testing
Weight: 40%
Focus: Whether changes are protected by meaningful automated tests.

### Criteria
- Automated tests exist.
- Tests reach the core modules, not just a few files.
- Tests run automatically on every pull request.
- Test coverage is measured with a report, badge, or enforced threshold.
- Tests are meaningful and cover edge cases rather than trivial smoke tests.

### Bands
- 0-2: No tests, or only trivial smoke tests.
- 3-5: Some tests on a few modules; not run on pull requests or coverage not measured.
- 6-8: Most core modules tested and run on pull requests; coverage measured.
- 9-10: Nearly all modules tested on every pull request; enforced coverage threshold; meaningful edge-case tests.

### Hard rules
- If the repository has no test files, score is at most 2.

## Pillar: Release Hygiene
Weight: 30%
Focus: Whether users can rely on versioned, documented releases.

### Criteria
- The project has published a release in the last 12 months.
- Releases come with notes or a changelog describing what changed.
- The repository has a license.

### Bands
- 0-3: No releases or no license.
- 4-6: Releases exist but are infrequent or undocumented.
- 7-10: Regular releases with meaningful notes and a clear license.

### Hard rules
- If the repository has no license, score is at most 3.

## Pillar: Security Basics
Weight: 30%
Focus: Baseline practices for handling vulnerabilities and dependencies.

### Criteria
- A security policy explains how to report vulnerabilities.
- Dependency updates are automated.
- CI runs a security or dependency scan.

### Bands
- 0-3: No security policy, no automated dependency updates, no scanning.
- 4-6: One or two of the three practices in place.
- 7-10: All three practices in place.
```

What the planner will likely do with it:

| Criterion | Likely status | Evidence |
|---|---|---|
| Automated tests exist. | measured | `tests.inventory` |
| Tests reach the core modules. | measured | `tests.mapping` |
| Tests run on every pull request. | measured | `ci.config` `tests_run_on_pull_request` |
| Coverage is measured. | measured | `tests.coverage` |
| Tests are meaningful. | judgement | tests agent reads test files |
| A release in the last 12 months. | measured | `github.releases` |
| Releases come with notes. | judgement | docs agent reads release notes |
| The repository has a license. | measured | `repo.inventory` |
| A security policy exists. | measured | `file.exists` for `SECURITY.md` |
| Dependency updates are automated. | measured | `ci.config` `uses_dependabot` |
| CI runs a security scan. | measured | `ci.config` `has_security_step` |

Eleven criteria, nine measured by facts: this clause will score consistently.

---

## 10. From clause to evaluation

```bash
uv run gitcrawl plan my_clause.md -o my_plan.yaml     # one model call: draft plan
uv run gitcrawl plan approve my_plan.yaml             # after reviewing it
uv run gitcrawl evaluate owner/repo --plan my_plan.yaml
```

### Reviewing the plan

Before approving, check:

- [ ] **Statuses.** Is anything marked `judgement` that a fact could answer? Is anything
      `measured` by a check that doesn't really answer the criterion?
- [ ] **Not measurable.** Do you accept each exclusion and its reason? If not, reword the
      criterion in the clause and re-plan.
- [ ] **Checks.** Do the `why` lines make sense? Are generic checks (`file.exists`,
      `file.contains`) using sensible globs and patterns?
- [ ] **Rules.** Does each `when:` expression mean what your hard rule says? Is the cap right?
- [ ] **Questions.** Are judgement questions focused and answerable from the repository?

### Changing things later

| You change | Then |
|---|---|
| Anything in `clause.md` | Re-run `gitcrawl plan`; the old plan no longer matches the clause |
| The plan YAML (a check, rule or question) | Run `gitcrawl plan approve` again; edits un-approve it |
| Pillar names, weights, bands or criteria text in the plan | Not allowed; change the clause instead |

Bump `Version:` whenever you change the meaning of the clause, so reports show which version a
score was produced under.

---

## 11. How scores are computed

- Each pillar gets a whole-number score from 0 to 10. Code lowers it to any cap a hard rule set.
- Weighted score per pillar is **`weight × score`** (for example, 25% of 8 is 2.00).
- The total is the sum over assessed pillars, **renormalized** by their combined weight, so a
  pillar that is not assessed doesn't drag the total toward zero.
- The report always states how much of the rubric's weight was assessed, and lists every
  criterion that was not measured.

---

## 12. Checklist before you plan

- [ ] Weights add up to 100%.
- [ ] Bands cover 0–10 with no gaps; every criterion and band is on a single line.
- [ ] Every quality mentioned in a band has a matching criterion.
- [ ] Each criterion states one observable idea, with a threshold where "good" or "regular" matters.
- [ ] No criterion depends on data GitCrawl can't reach (section 6), unless you accept it being excluded.
- [ ] The same evidence isn't scored in two pillars.
- [ ] Hard rules are few, based on facts, and consistent with the bands.
- [ ] `Version:` reflects this revision.

---

## Current limitations

- **GitHub repositories only.** GitHub API facts need a `GITHUB_TOKEN`; without one those facts
  are unavailable, and rules that depend on them are reported as not checked.
- **Language support.** Source and test analysis recognizes common software languages (Python,
  JavaScript/TypeScript, Go, Rust, Java, Kotlin, C/C++, C#, Ruby, PHP, Swift, Dart, Elixir, Scala).
  Hardware description languages such as Verilog and VHDL aren't counted yet, and hardware
  test scripts are treated like software tests. Clauses for hardware or firmware projects should
  lean on judgement criteria for code and testing.
- **`examples/`, `docs/`, `scripts/` and similar directories** are not counted as source code.
- **Contributor counts** read up to the first 100 contributors.
