# Repository Quality Evaluation
Version: 2.0

## Pillar: Code Health
Weight: 25%
Focus: Structure, modularity, readability, and maintainability of the codebase.

### Criteria
- The directory structure follows a recognizable architecture (layered, feature-based, or domain-based).
- Modules are cohesive with clear separation of concerns and low coupling between them.
- There are no oversized "god" files or folders; file sizes are reasonable.
- Duplicated logic across the codebase is minimal.
- Code is readable and documented (docstrings or comments, architecture docs where needed).

### Bands
- 0-2: No clear structure; mixed concerns everywhere; very large god files or folders; no recognizable architecture or patterns.
- 3-5: Some modularization but inconsistent; occasional tangled dependencies or duplicated logic; basic separation of concerns but many smells.
- 6-8: Clear modular structure by feature, layer, or domain; reasonable file sizes and cohesive modules; follows a known pattern with minor issues.
- 9-10: Very clean, well-documented architecture; strong separation of concerns, low coupling, high cohesion; minimal duplication, consistent patterns, easy to navigate.

## Pillar: Test Coverage
Weight: 20%
Focus: Presence, breadth, and quality of automated tests.

### Criteria
- Automated tests exist.
- Tests cover the core modules and critical paths, not just a few files.
- Coverage data exists (coverage reports, badges, or coverage collected in CI) and shows the coverage level.
- There is a clear test strategy mixing unit, integration, and end-to-end tests.
- Tests are meaningful, well organized, and reliable rather than trivial smoke tests.
- CI runs the test suite.

### Bands
- 0-2: No tests or only trivial smoke tests; no coverage data; core logic untested.
- 3-5: Some unit tests but low coverage; critical paths partially tested; tests brittle or poorly structured.
- 6-8: Good unit and integration coverage on core modules; coverage report shows moderate to high coverage; tests organized, meaningful, and mostly reliable.
- 9-10: High coverage on critical paths and most modules; clear test strategy (unit, integration, E2E); tests well structured, documented, and stable.

### Hard rules
- If the repository has no test files, score is at most 2.

## Pillar: CI/CD
Weight: 20%
Focus: Automation, reliability, and quality gates in pipelines.

### Criteria
- CI/CD pipelines are configured.
- Pipelines run on every push and pull request.
- Pipelines include lint, test, security, and build steps.
- Quality gates are enforced (coverage thresholds, required lint or security checks).
- Pipeline runs are mostly green with a high first-attempt pass rate.
- Deployment is automated.

### Bands
- 0-2: No CI/CD configured, or pipelines are always failing or not run on pull requests.
- 3-5: Basic CI present (build and some tests); intermittent failures; limited quality gates; flaky or inconsistent runs.
- 6-8: CI runs on every push and pull request; includes lint, tests, and basic security checks; mostly green with occasional failures.
- 9-10: Robust CI/CD with a high first-attempt pass rate; enforced quality gates (coverage thresholds, lint, security scans); reliable build, test, and deployment pipelines.

### Hard rules
- If the repository has no CI configuration, score is at most 2.
- If every recent CI run failed, score is at most 2.

## Pillar: Issue Management
Weight: 20%
Focus: How issues and pull requests are tracked, triaged, and resolved.

### Criteria
- Issues are closed regularly and few open issues are stale.
- Issues and pull requests use labels, templates, and milestones.
- Maintainers respond to issues and review pull requests promptly.
- Contribution guidelines describe the issue and pull request workflow.
- Discussion on issues and pull requests is constructive and helpful.

### Bands
- 0-2: Many stale open issues with no activity; no labels, templates, or triage process; pull requests sit unreviewed for long periods.
- 3-5: Some issues closed regularly but many remain stale; basic labels or templates exist but are not used consistently; review response times vary widely.
- 6-8: Active triage with most issues addressed in reasonable time; clear labels, templates, and contribution guidelines; pull requests reviewed promptly with good discussion.
- 9-10: Very responsive maintainers who close most issues quickly; well-structured issue and pull request workflow (templates, labels, bots); transparent backlog, milestones, and release planning.

## Pillar: Community
Weight: 15%
Focus: Adoption, contributor base, and long-term maintenance signals.

### Criteria
- Stars, forks, and watchers show adoption.
- There are multiple active contributors and commits are not concentrated in one person.
- Releases are regular and come with meaningful changelogs.
- The project shows recent activity and ongoing maintenance.
- The project has a README and a license.
- There is evidence of external adoption (dependents, tutorials, talks, or blog posts).

### Bands
- 0-2: Very low stars and forks; single contributor; no recent releases or activity; no evidence of adoption.
- 3-5: Moderate stars and forks; small contributor base; irregular releases with some activity; limited but visible adoption.
- 6-8: Healthy stars and forks; multiple active contributors; regular releases with meaningful changelogs; clear signs of adoption.
- 9-10: Strong community with many contributors and users; frequent, well-documented releases; widely adopted and referenced.

### Hard rules
- If the repository has no README and no license, score is at most 3.
- If the repository has a single contributor, score is at most 5.
