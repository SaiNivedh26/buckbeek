# Repository Quality Evaluation
Version: 1.1

<!--
Based on the original clause.md (v1.0, 2026-09-10), in the GitCrawl template.
- Pillars, weights, focus lines and score bands are carried over verbatim.
- v1.1: criteria rewritten to cover everything the bands score (not just presence), split into
  checkable statements; hard rules added where bands state absolutes; "static analysis outputs"
  and "project boards" dropped (no data source).
-->

## Pillar: Code Health
Weight: 25%
Focus: Structure, modularity, readability, and maintainability of the codebase.

### Criteria
- The directory structure follows a recognizable architecture (layered, feature-based, or domain-based).
- Modules have clear separation of concerns and low coupling between them.
- There are no oversized "god" files or folders.
- Duplicated logic across the codebase is minimal.
- Code is readable, and non-obvious parts are documented.

### Bands
- 0-2: No clear structure; mixed concerns everywhere. Very large "god" files/folders. No recognizable architecture or patterns.
- 3-5: Some modularization but inconsistent. Occasional tangled dependencies or duplicated logic. Basic separation of concerns, but many smells.
- 6-8: Clear modular structure (e.g., by feature/layer/domain). Reasonable file sizes, cohesive modules. Follows a known pattern (Clean Architecture, N-Layered, Vertical Slice, etc.) with minor issues.
- 9-10: Very clean, well-documented architecture. Strong separation of concerns, low coupling, high cohesion. Minimal duplication, consistent patterns, easy to navigate.

## Pillar: Test Coverage
Weight: 20%
Focus: Presence, breadth, and quality of automated tests.

### Criteria
- Automated tests exist.
- Tests reach the core modules and critical paths, not just a few files.
- Coverage is measured: a coverage report, badge, or enforced coverage threshold exists.
- The test suite mixes unit, integration, and end-to-end tests.
- Tests are meaningful and well structured rather than trivial smoke tests.

### Bands
- 0-2: No tests or only trivial smoke tests. No coverage data; core logic untested.
- 3-5: Some unit tests, but low coverage. Critical paths partially tested. Tests exist but are brittle or poorly structured.
- 6-8: Good unit/integration test coverage on core modules. Coverage badge/report shows moderate-high coverage. Tests are organized, meaningful, and mostly reliable.
- 9-10: High coverage on critical paths and most modules. Clear test strategy (unit, integration, E2E). Tests are well-structured, documented, and stable.

### Hard rules
- If the repository has no test files, score is at most 2.

## Pillar: CI/CD
Weight: 20%
Focus: Automation, reliability, and quality gates in pipelines.

### Criteria
- CI pipelines are configured.
- Pipelines run on every push and pull request.
- Pipelines include lint, test, security, and build steps.
- Quality gates are enforced (coverage threshold, required lint or security checks).
- Recent pipeline runs are mostly green with a high first-attempt pass rate.
- Deployment is automated.

### Bands
- 0-2: No CI/CD configured. Or pipelines are always failing / not run on PRs.
- 3-5: Basic CI present (build + some tests). Intermittent failures; limited quality gates. Flaky or inconsistent runs.
- 6-8: CI runs on every push/PR. Includes lint, tests, and basic security checks. Mostly green; occasional failures with clear reasons.
- 9-10: Robust CI/CD with high first-attempt pass rate. Enforced quality gates (coverage thresholds, lint, security scans). Reliable pipelines for build, test, and deployment.

### Hard rules
- If the repository has no CI configuration, score is at most 2.
- If every recent CI run failed, score is at most 2.

## Pillar: Issue Management
Weight: 20%
Focus: How issues and PRs are tracked, triaged, and resolved.

### Criteria
- Most issues get closed, and few open issues are stale.
- Issues and pull requests use labels and milestones.
- Issue and pull request templates and contribution guidelines exist.
- Maintainers respond to new issues promptly.
- Pull requests are reviewed promptly before merging.
- Discussion on issues and pull requests is constructive.

### Bands
- 0-2: Many stale/open issues with no activity. No labels, templates, or triage process. PRs sit unreviewed for long periods.
- 3-5: Some issues closed regularly, but many remain stale. Basic labels/templates exist but not consistently used. PRs reviewed, but response times vary widely.
- 6-8: Active issue triage; most issues addressed in reasonable time. Clear labels, templates, and contribution guidelines. PRs reviewed promptly; good discussion quality.
- 9-10: Very responsive maintainers; most issues closed quickly. Well-structured issue/PR workflow (templates, labels, bots). Transparent backlog, milestones, and release planning.

## Pillar: Community
Weight: 15%
Focus: Adoption, contributor base, and long-term maintenance signals.

### Criteria
- Stars, forks, and watchers show adoption.
- There are multiple active contributors and commits are not concentrated in one person.
- Releases are regular and come with meaningful changelogs.
- The project shows recent activity and ongoing maintenance.
- There is external adoption (dependents, mentions, blog posts).

### Bands
- 0-2: Very low stars/forks; single contributor. No recent releases or activity. No evidence of external adoption.
- 3-5: Moderate stars/forks; small contributor base. Irregular releases; some activity. Limited but visible adoption.
- 6-8: Healthy stars/forks ratio; multiple active contributors. Regular releases with meaningful changelogs. Clear signs of adoption (dependents, tutorials, talks).
- 9-10: Strong community with many contributors and users. Frequent, well-documented releases. Widely adopted; referenced in docs, blogs, or products.

### Hard rules
- If the repository has a single contributor, score is at most 5.
