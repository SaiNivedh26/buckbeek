Agent-ID: 8f70d7c6-9c58-4b2c-8f1d-2a6e4c71b903
# GitCrawl Evaluation Rubric
Version: 1.1

## Pillar: Code Health
Weight: 25%
Focus: Maintainability, cleanliness, modularity, and structural organization of Python source files.

### Criteria
- Source files stay reasonably sized with minimal oversized modules.
- Code uses docstrings and appropriate commenting density.
- Internal imports follow clear modular boundaries.
- Code is free of import cycles between modules.

### Bands
- 0-2: Extremely tangled dependency graph, pervasive import cycles, and lack of modular grouping.
- 3-5: Moderate organization with some oversized files and un-documented modules.
- 6-8: Clean module boundaries, reasonable file lengths, and proper docstring coverage.
- 9-10: Exemplary modularity, clean import hierarchies, complete docstring coverage, and zero import cycles.

### Hard rules
- If there are no source files, the pillar is not assessed.

## Pillar: Test Coverage
Weight: 20%
Focus: Presence, breadth, test-to-source ratio, and coverage instrumentation of test files.

### Criteria
- Dedicated test files exist in the repository.
- Unit, integration, or end-to-end testing directories are structured clearly.
- Test files cover primary core source modules.
- Coverage reports or enforcement mechanisms are present.

### Bands
- 0-2: Zero test files or completely untested core application code.
- 3-5: Minimal test files that only target a small percentage of source modules.
- 6-8: Solid test suite covering key functional paths with explicit mapping to source modules.
- 9-10: Comprehensive test suite spanning unit and integration tests with enforced coverage thresholds.

### Hard rules
- If the repository has no test files, score is at most 2.

## Pillar: CI/CD
Weight: 20%
Focus: Robustness, automation, triggers, and execution gates of continuous integration pipelines.

### Criteria
- Continuous integration workflow files exist and are syntactically valid.
- Workflows trigger automatically on pull requests and pushes.
- Pipelines include linting, security scans, and test execution steps.
- Recent workflow run history shows positive completion rates.

### Bands
- 0-2: No CI pipelines configured, or all pipeline definitions are failing / invalid.
- 3-5: Basic workflow configuration present but missing pull request triggers or security checks.
- 6-8: Fully configured pipelines executing linting, tests, and build steps on every pull request.
- 9-10: Advanced CI/CD pipelines featuring robust quality gates, security audits, and high first-attempt success rates.

### Hard rules
- If the repository has no CI configuration, score is at most 2.

## Pillar: Issue Management
Weight: 20%
Focus: Health, triage responsiveness, templates, and active tracking of issues and pull requests.

### Criteria
- Issue trackers and pull requests demonstrate active maintenance.
- Issues and PRs utilize labels and milestones.
- Issue and pull request templates are available in the repository.
- Maintainers respond promptly to external contributions.

### Bands
- 0-2: Dormant issue tracker, high volume of stale open issues, and missing templates.
- 3-5: Basic tracking with occasional triage but sluggish maintainer response times.
- 6-8: Active triage, frequent issue resolution, and proper template and label usage.
- 9-10: Highly responsive maintainer team, structured templates, automated labeling, and low stale issue ratios.

## Pillar: Community
Weight: 15%
Focus: Documentation, licensing, contributor diversity, and release cadence.

### Criteria
- A clear project README and license file exist in the root directory.
- CONTRIBUTING guides or security policies are provided.
- Releases occur regularly with meaningful release notes or changelogs.
- Contributor spread shows healthy project distribution without single-author concentration.

### Bands
- 0-2: Missing README and LICENSE files with zero releases or contributor diversity.
- 3-5: Presence of README/LICENSE but sparse documentation and irregular releases.
- 6-8: Well-written README, explicit license, regular version releases, and multiple active contributors.
- 9-10: Thriving community presence, comprehensive community health files, frequent structured releases, and balanced contributions.

### Hard rules
- If the repository has no README and no license, score is at most 3.
- If the repository has a single contributor, score is at most 5.
