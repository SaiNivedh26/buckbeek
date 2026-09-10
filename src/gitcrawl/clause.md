# Repository Quality Evaluation Clause (clause.md)

This document defines a standard scoring model and evaluation rubric that agents MUST follow when assessing the quality, integrity, and maintainability of an open-source GitHub repository.

---

## 1. Purpose

Provide a consistent, quantitative framework to evaluate repositories across five core pillars:

- Code Health
- Test Coverage
- CI/CD
- Issue Management
- Community

Each pillar is scored on a 0–10 scale, weighted, and aggregated into a final **Repository Quality Score** out of 10.

---

## 2. Scoring Model

### 2.1 Pillars, Weights, and Score Range

| Pillar           | Weight | Score Range |
|------------------|--------|-------------|
| Code Health      | 25%    | 0–10        |
| Test Coverage    | 20%    | 0–10        |
| CI/CD            | 20%    | 0–10        |
| Issue Management | 20%    | 0–10        |
| Community        | 15%    | 0–10        |
| **Total**        | 100%   | —           |

### 2.2 Weighted Score Calculation

For each pillar:

Weighted Score_i = Weight_i × (Score_i / 10)

Overall Repository Quality Score:

Total Score = Σ_i Weighted Score_i

The final score is reported as **X.XX / 10**.

**Example:**

| Pillar           | Weight | Score (0–10) | Weighted Score |
|------------------|--------|--------------|----------------|
| Code Health      | 25%    | 8            | 2.00           |
| Test Coverage    | 20%    | 7            | 1.40           |
| CI/CD            | 20%    | 9            | 1.80           |
| Issue Management | 20%    | 6            | 1.20           |
| Community        | 15%    | 5            | 0.75           |
| **Total**        | 100%   | —            | **7.15 / 10**  |

---

## 3. Pillar Definitions & Scoring Rubrics

Agents MUST use the following criteria when assigning a 0–10 score to each pillar.

---

### 3.1 Code Health (25%)

**Focus:** Structure, modularity, readability, and maintainability of the codebase.

**Data sources:**
- Repository directory structure (via `github_directory_structure`).
- Key files: `README.md`, architecture docs, main source files, config files (via `github_read_important_files`).
- Static analysis outputs (if available).

**Scoring guidelines:**

- **0–2:** 
  - No clear structure; mixed concerns everywhere.
  - Very large “god” files/folders.
  - No recognizable architecture or patterns.
- **3–5:**
  - Some modularization but inconsistent.
  - Occasional tangled dependencies or duplicated logic.
  - Basic separation of concerns, but many smells.
- **6–8:**
  - Clear modular structure (e.g., by feature/layer/domain).
  - Reasonable file sizes, cohesive modules.
  - Follows a known pattern (Clean Architecture, N‑Layered, Vertical Slice, etc.) with minor issues.
- **9–10:**
  - Very clean, well-documented architecture.
  - Strong separation of concerns, low coupling, high cohesion.
  - Minimal duplication, consistent patterns, easy to navigate.

---

### 3.2 Test Coverage (20%)

**Focus:** Presence, breadth, and quality of automated tests.

**Data sources:**
- Test directories and files (e.g., `tests/`, `*_test.go`, `*.spec.ts`).
- Coverage reports (e.g., `coverage.xml`, `lcov.info`, CI badges).
- CI configuration showing test execution.

**Scoring guidelines:**

- **0–2:**
  - No tests or only trivial smoke tests.
  - No coverage data; core logic untested.
- **3–5:**
  - Some unit tests, but low coverage.
  - Critical paths partially tested.
  - Tests exist but are brittle or poorly structured.
- **6–8:**
  - Good unit/integration test coverage on core modules.
  - Coverage badge/report shows moderate–high coverage.
  - Tests are organized, meaningful, and mostly reliable.
- **9–10:**
  - High coverage on critical paths and most modules.
  - Clear test strategy (unit, integration, E2E).
  - Tests are well-structured, documented, and stable.

---

### 3.3 CI/CD (20%)

**Focus:** Automation, reliability, and quality gates in pipelines.

**Data sources:**
- CI configuration files (e.g., `.github/workflows/*.yml`, `.gitlab-ci.yml`).
- CI run history (green/red status, frequency).
- Presence of lint, test, security, and build steps.

**Scoring guidelines:**

- **0–2:**
  - No CI/CD configured.
  - Or pipelines are always failing / not run on PRs.
- **3–5:**
  - Basic CI present (build + some tests).
  - Intermittent failures; limited quality gates.
  - Flaky or inconsistent runs.
- **6–8:**
  - CI runs on every push/PR.
  - Includes lint, tests, and basic security checks.
  - Mostly green; occasional failures with clear reasons.
- **9–10:**
  - Robust CI/CD with high first‑attempt pass rate.
  - Enforced quality gates (coverage thresholds, lint, security scans).
  - Reliable pipelines for build, test, and deployment.

---

### 3.4 Issue Management (20%)

**Focus:** How issues and PRs are tracked, triaged, and resolved.

**Data sources:**
- GitHub Issues and Pull Requests (open/closed counts, timestamps).
- Labels, milestones, project boards.
- Response times and closure rates (if available).

**Scoring guidelines:**

- **0–2:**
  - Many stale/open issues with no activity.
  - No labels, templates, or triage process.
  - PRs sit unreviewed for long periods.
- **3–5:**
  - Some issues closed regularly, but many remain stale.
  - Basic labels/templates exist but not consistently used.
  - PRs reviewed, but response times vary widely.
- **6–8:**
  - Active issue triage; most issues addressed in reasonable time.
  - Clear labels, templates, and contribution guidelines.
  - PRs reviewed promptly; good discussion quality.
- **9–10:**
  - Very responsive maintainers; most issues closed quickly.
  - Well-structured issue/PR workflow (templates, labels, bots).
  - Transparent backlog, milestones, and release planning.

---

### 3.5 Community (15%)

**Focus:** Adoption, contributor base, and long-term maintenance signals.

**Data sources:**
- Stars, forks, watchers.
- Number of contributors and commit distribution.
- Release cadence, changelog quality.
- External adoption (dependents, mentions, blog posts).

**Scoring guidelines:**

- **0–2:**
  - Very low stars/forks; single contributor.
  - No recent releases or activity.
  - No evidence of external adoption.
- **3–5:**
  - Moderate stars/forks; small contributor base.
  - Irregular releases; some activity.
  - Limited but visible adoption.
- **6–8:**
  - Healthy stars/forks ratio; multiple active contributors.
  - Regular releases with meaningful changelogs.
  - Clear signs of adoption (dependents, tutorials, talks).
- **9–10:**
  - Strong community with many contributors and users.
  - Frequent, well-documented releases.
  - Widely adopted; referenced in docs, blogs, or products.

---

## 4. Agent Instructions

When evaluating a repository:

1. **Collect data** using available tools:
   - `github_directory_structure` for repo layout.
   - `github_read_important_files` for:
     - `README.md`, `LICENSE`, `CONTRIBUTING.md`, `CHANGELOG.md`, `SECURITY.md`
     - Key source files (e.g., `src/**`, `app/**`)
     - Test files (e.g., `tests/**`, `*_test.*`)
     - CI config (e.g., `.github/workflows/*.yml`)
   - GitHub API / other tools for:
     - Issues/PRs metrics
     - Stars, forks, contributors
     - CI run history (if accessible)

2. **Score each pillar (0–10)** using the rubrics in Section 3.

3. **Compute weighted scores** using the formula in Section 2.2.

4. **Output** a structured evaluation including:
   - Per-pillar score and brief justification.
   - Weighted score per pillar.
   - Final total score (X.XX / 10).
   - Optional: key strengths, risks, and improvement suggestions.

---

## 5. Example Output Format

```markdown
## Repository Quality Evaluation

### Pillar Scores

| Pillar           | Weight | Score (0–10) | Weighted Score | Notes                                      |
|------------------|--------|--------------|----------------|--------------------------------------------|
| Code Health      | 25%    | 8            | 2.00           | Clear modular structure, minor duplication |
| Test Coverage    | 20%    | 7            | 1.40           | Good unit tests, integration tests sparse  |
| CI/CD            | 20%    | 9            | 1.80           | Robust CI, high pass rate                  |
| Issue Management | 20%    | 6            | 1.20           | Active but some stale issues               |
| Community        | 15%    | 5            | 0.75           | Small but growing community                |
| **Total**        | 100%   | —            | **7.15 / 10**  |                                            |

### Summary

- Strengths: Clean architecture, reliable CI.
- Risks: Limited integration tests, some stale issues.
- Recommendations: Add E2E tests, improve issue triage automation.
```

---

## 6. Versioning

- **Version:** 1.0
- **Last Updated:** 2026-09-10
- **Maintainer:** Repository Quality Evaluation Working Group

---


