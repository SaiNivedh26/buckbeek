"""ci.config: parse CI configuration into triggers and classified steps.

GitHub Actions is parsed fully, following local reusable workflows
(`uses: ./.github/workflows/x.yml`), local composite actions
(`uses: ./.github/actions/x`), package-manager scripts (`npm run ci` →
package.json's script text), Makefile targets and repo-local shell scripts,
so a step like `run: make ci` is classified by what it actually runs.
GitLab CI is parsed for job scripts. Other CI systems are detected and
reported as unparsed — the planner can route those to a judgement agent.
"""

from __future__ import annotations

import json
import re
from typing import Any

import yaml
from pydantic import BaseModel

from gitcrawl.collectors.base import CollectorContext, CollectorResult, collector

STEP_KINDS = ("lint", "test", "security", "build", "deploy", "coverage")

_KIND_PATTERNS: dict[str, re.Pattern[str]] = {
    "test": re.compile(
        r"\b(pytest|py\.test|jest|vitest|mocha|ava|go test|cargo test|cargo nextest|(npm|pnpm|bun)( run)? test"
        r"|yarn test|mvn\b.*\b(test|verify)|gradlew?\b.*\btest|rspec|phpunit|tox|nox|ctest|dotnet test|make test"
        r"|playwright test|cypress run|unittest)\b",
        re.IGNORECASE,
    ),
    "lint": re.compile(
        r"\b(eslint|ruff|flake8|pylint|black --check|isort --check|prettier (--check|-c)|golangci-lint|go vet"
        r"|clippy|rubocop|mypy|pyright|tsc\b[^\n]*--noemit|typecheck|type-check|stylelint|shellcheck|pre-commit"
        r"|biome (check|lint)|(npm|pnpm|bun)( run)? lint|yarn lint|hadolint|markdownlint|ktlint|checkstyle)\b",
        re.IGNORECASE,
    ),
    "security": re.compile(
        r"(github/codeql-action|snyk|trivy|bandit|npm audit|yarn audit|pnpm audit|pip-audit|safety check|gosec"
        r"|semgrep|dependency-review-action|ossf/scorecard|gitleaks|trufflehog|anchore|grype|osv-scanner"
        r"|cargo audit|cargo deny|govulncheck|zizmor)",
        re.IGNORECASE,
    ),
    "build": re.compile(
        r"\b((npm|pnpm|bun)( run)? build|yarn build|go build|cargo build|mvn\b.*\b(package|install)|gradlew?\b.*"
        r"\b(build|assemble)|docker build|docker/build-push-action|python -m build|uv build|poetry build"
        r"|vite build|next build|webpack|rollup|tsc\b(?![^\n]*--noemit)|make( build|$)|dotnet build|hatch build)",
        re.IGNORECASE,
    ),
    "deploy": re.compile(
        r"(deploy|vercel|netlify|heroku|aws-actions/|azure/webapps-deploy|google-github-actions/deploy"
        r"|firebase deploy|kubectl apply|helm (upgrade|install)|gh-pages|actions-gh-pages|twine upload"
        r"|npm publish|pypa/gh-action-pypi-publish|cargo publish|goreleaser|supabase (db push|functions deploy)"
        r"|fly deploy|wrangler (deploy|publish)|docker push|semantic-release|changesets/action)",
        re.IGNORECASE,
    ),
    "coverage": re.compile(
        r"(--cov\b|--cov=|coverage run|--coverage|\bnyc\b|\bc8\b|codecov/codecov-action|coverallsapp|jacoco"
        r"|go test[^\n]*-cover|cargo (tarpaulin|llvm-cov)|--collect:\"xplat code coverage\")",
        re.IGNORECASE,
    ),
}
_THRESHOLD_RE = re.compile(
    r"(--cov-fail-under|fail_under|--fail-under|coverageThreshold|check-coverage|--min-coverage|fail_ci_if_error)",
    re.IGNORECASE,
)
# Environment setup: recognized, but not a quality step and not "opaque" either.
_SETUP_RE = re.compile(
    r"^\s*(pip3? install|python -m pip install|uv (sync|pip install)|poetry install|pipenv install"
    r"|(npm|pnpm|bun) (ci|install|i)\b|yarn( install)?\s*$|yarn install|apt(-get)? (update|install)"
    r"|brew install|go mod (download|tidy)|bundle install|composer install|corepack enable|cd\s)",
    re.IGNORECASE,
)
_PKG_SCRIPT_RE =re.compile(r"\b(?:npm|pnpm|bun)\s+(?:run\s+)?([\w:.-]+)|\byarn\s+(?:run\s+)?([\w:.-]+)")
_MAKE_RE = re.compile(r"\bmake\s+([\w.-]+)")
_SCRIPT_FILE_RE = re.compile(r"(?:^|\s)(?:bash\s+|sh\s+)?\.?/?((?:[\w.-]+/)*[\w.-]+\.(?:sh|bash|py))\b")
_NPM_BUILTINS = {"install", "ci", "i", "add", "exec", "npx", "init", "cache", "config", "set"}

_OTHER_SYSTEMS = {
    ".circleci/config.yml": "circleci",
    ".circleci/config.yaml": "circleci",
    "jenkinsfile": "jenkins",
    ".travis.yml": "travis",
    "azure-pipelines.yml": "azure_pipelines",
    "azure-pipelines.yaml": "azure_pipelines",
    "bitbucket-pipelines.yml": "bitbucket",
    ".drone.yml": "drone",
    "buildkite.yml": "buildkite",
}


class WorkflowSummary(BaseModel):
    path: str
    name: str
    triggers: list[str]
    jobs: int
    step_kinds: list[str]


class CiConfigOutput(BaseModel):
    has_ci: bool
    systems: list[str]
    unparsed_systems: list[str]
    workflow_count: int
    workflows: list[WorkflowSummary]
    triggers_push: bool
    triggers_pull_request: bool
    triggers_schedule: bool
    has_lint_step: bool
    has_test_step: bool
    has_security_step: bool
    has_build_step: bool
    has_deploy_step: bool
    has_coverage_step: bool
    coverage_threshold_enforced: bool
    tests_run_on_pull_request: bool
    uses_dependabot: bool
    opaque_steps: list[str]
    parse_errors: list[str]


class _Analysis:
    def __init__(self) -> None:
        self.kinds: set[str] = set()
        self.threshold = False
        self.opaque: list[str] = []
        self.citations: set[str] = set()


def _classify_text(text: str, analysis: _Analysis) -> set[str]:
    kinds = {kind for kind, pat in _KIND_PATTERNS.items() if pat.search(text)}
    if _THRESHOLD_RE.search(text):
        analysis.threshold = True
    analysis.kinds |= kinds
    return kinds


def _triggers(doc: dict[str, Any]) -> list[str]:
    # PyYAML (YAML 1.1) parses a bare `on:` key as boolean True.
    raw = doc.get("on", doc.get(True))
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(t) for t in raw]
    if isinstance(raw, dict):
        return [str(t) for t in raw]
    return []


class _Parser:
    def __init__(self, ctx: CollectorContext):
        self.ctx = ctx
        self.errors: list[str] = []
        self._package_scripts: dict[str, str] | None = None

    def load_yaml(self, path: str) -> dict[str, Any] | None:
        text = self.ctx.files.read_text(path)
        if text is None:
            return None
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError as e:
            self.errors.append(f"{path}: invalid YAML ({str(e).splitlines()[0]})")
            return None
        return doc if isinstance(doc, dict) else None

    def package_scripts(self) -> dict[str, str]:
        if self._package_scripts is None:
            self._package_scripts = {}
            text = self.ctx.files.read_text("package.json")
            if text:
                try:
                    scripts = json.loads(text).get("scripts") or {}
                    self._package_scripts = {k: str(v) for k, v in scripts.items()}
                except (json.JSONDecodeError, AttributeError):
                    self.errors.append("package.json: invalid JSON")
        return self._package_scripts

    def expand_run(self, text: str, analysis: _Analysis, depth: int = 0) -> set[str]:
        """Classify a shell snippet, following package scripts, make targets and local scripts once."""
        kinds = _classify_text(text, analysis)
        if depth >= 2:
            return kinds
        for m in _PKG_SCRIPT_RE.finditer(text):
            name = m.group(1) or m.group(2)
            script = self.package_scripts().get(name) if name not in _NPM_BUILTINS else None
            if script:
                analysis.citations.add("package.json")
                kinds |= self.expand_run(script, analysis, depth + 1)
        for m in _MAKE_RE.finditer(text):
            recipe = self._make_target(m.group(1))
            if recipe:
                analysis.citations.add("Makefile")
                kinds |= self.expand_run(recipe, analysis, depth + 1)
        for m in _SCRIPT_FILE_RE.finditer(text):
            script_text = self.ctx.files.read_text(m.group(1))
            if script_text:
                analysis.citations.add(m.group(1))
                kinds |= self.expand_run(script_text, analysis, depth + 1)
        return kinds

    def _make_target(self, target: str) -> str | None:
        text = self.ctx.files.read_text("Makefile")
        if not text:
            return None
        m = re.search(rf"^{re.escape(target)}\s*:[^\n]*\n((?:\t[^\n]*\n?)+)", text, re.MULTILINE)
        return m.group(1) if m else None

    def analyze_steps(self, steps: list[Any], analysis: _Analysis, depth: int) -> None:
        for step in steps or []:
            if not isinstance(step, dict):
                continue
            label = " ".join(str(step.get(k, "")) for k in ("name", "uses"))
            run = str(step.get("run", ""))
            uses = str(step.get("uses", ""))
            kinds = _classify_text(label, analysis)
            if run:
                kinds |= self.expand_run(run, analysis)
            with_args = step.get("with")
            if isinstance(with_args, dict):
                kinds |= _classify_text(" ".join(f"{k} {v}" for k, v in with_args.items()), analysis)
            if uses.startswith("./") and depth < 3:
                self.analyze_composite(uses, analysis, depth + 1)
            elif run and not kinds and not _SETUP_RE.match(run) and len(analysis.opaque) < 10:
                analysis.opaque.append(run.strip().splitlines()[0][:120])

    def analyze_composite(self, uses: str, analysis: _Analysis, depth: int) -> None:
        base = uses[2:].rstrip("/")
        for name in ("action.yml", "action.yaml"):
            doc = self.load_yaml(f"{base}/{name}")
            if doc:
                analysis.citations.add(f"{base}/{name}")
                runs = doc.get("runs") or {}
                self.analyze_steps(runs.get("steps") or [], analysis, depth)
                return

    def analyze_workflow(self, path: str, doc: dict[str, Any], analysis: _Analysis, depth: int = 0) -> int:
        jobs = doc.get("jobs") or {}
        if not isinstance(jobs, dict):
            return 0
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            _classify_text(f"{job_name} {job.get('name', '')}", analysis)
            uses = str(job.get("uses", ""))
            if uses.startswith("./") and depth < 3:
                target = uses[2:].split("@")[0]
                sub = self.load_yaml(target)
                if sub:
                    analysis.citations.add(target)
                    self.analyze_workflow(target, sub, analysis, depth + 1)
            elif uses:
                _classify_text(uses, analysis)
            self.analyze_steps(job.get("steps") or [], analysis, depth)
        return len(jobs)


@collector(
    "ci.config",
    description=(
        "Parsed CI configuration: CI systems present, triggers (push / pull_request / schedule), steps "
        "classified as lint/test/security/build/deploy/coverage (following reusable workflows, composite "
        "actions, package scripts, Makefile targets and local scripts), coverage thresholds, whether tests "
        "run on pull requests, Dependabot config, and steps that could not be classified."
    ),
    category="ci",
    output=CiConfigOutput,
    version="1",
)
def ci_config(ctx: CollectorContext, params) -> CollectorResult:
    files = ctx.files.files()
    parser = _Parser(ctx)
    overall = _Analysis()
    workflows: list[WorkflowSummary] = []
    systems: set[str] = set()
    unparsed: set[str] = set()
    pr_test = False
    all_triggers: set[str] = set()

    for path in files:
        lower = path.lower()
        if lower.startswith(".github/workflows/") and lower.endswith((".yml", ".yaml")):
            systems.add("github_actions")
            doc = parser.load_yaml(path)
            if doc is None:
                continue
            analysis = _Analysis()
            triggers = _triggers(doc)
            jobs = parser.analyze_workflow(path, doc, analysis)
            workflows.append(
                WorkflowSummary(
                    path=path,
                    name=str(doc.get("name") or path.rsplit("/", 1)[-1]),
                    triggers=triggers,
                    jobs=jobs,
                    step_kinds=sorted(analysis.kinds),
                )
            )
            all_triggers.update(triggers)
            overall.kinds |= analysis.kinds
            overall.threshold |= analysis.threshold
            overall.opaque.extend(analysis.opaque)
            overall.citations |= analysis.citations | {path}
            if "pull_request" in triggers or "pull_request_target" in triggers:
                pr_test |= "test" in analysis.kinds
        elif lower in (".gitlab-ci.yml", ".gitlab-ci.yaml"):
            systems.add("gitlab_ci")
            doc = parser.load_yaml(path) or {}
            analysis = _Analysis()
            jobs = 0
            for name, job in doc.items():
                if isinstance(job, dict) and "script" in job:
                    jobs += 1
                    _classify_text(str(name), analysis)
                    for key in ("before_script", "script"):
                        lines = job.get(key) or []
                        lines = lines if isinstance(lines, list) else [lines]
                        for line in lines:
                            parser.expand_run(str(line), analysis)
            # GitLab runs pipelines on push by default; merge request pipelines are opt-in.
            triggers = ["push"] + (["pull_request"] if "merge_request" in json.dumps(doc, default=str) else [])
            workflows.append(
                WorkflowSummary(path=path, name="GitLab CI", triggers=triggers, jobs=jobs,
                                step_kinds=sorted(analysis.kinds))
            )
            all_triggers.update(triggers)
            overall.kinds |= analysis.kinds
            overall.threshold |= analysis.threshold
            overall.citations |= analysis.citations | {path}
            if "pull_request" in triggers:
                pr_test |= "test" in analysis.kinds
        elif lower in _OTHER_SYSTEMS:
            systems.add(_OTHER_SYSTEMS[lower])
            unparsed.add(_OTHER_SYSTEMS[lower])
            overall.citations.add(path)

    dependabot = [f for f in files if f.lower() in (".github/dependabot.yml", ".github/dependabot.yaml")]
    data = CiConfigOutput(
        has_ci=bool(systems),
        systems=sorted(systems),
        unparsed_systems=sorted(unparsed),
        workflow_count=len(workflows),
        workflows=workflows,
        triggers_push="push" in all_triggers,
        triggers_pull_request=bool({"pull_request", "pull_request_target"} & all_triggers),
        triggers_schedule="schedule" in all_triggers,
        has_lint_step="lint" in overall.kinds,
        has_test_step="test" in overall.kinds,
        has_security_step="security" in overall.kinds,
        has_build_step="build" in overall.kinds,
        has_deploy_step="deploy" in overall.kinds,
        has_coverage_step="coverage" in overall.kinds,
        coverage_threshold_enforced=overall.threshold,
        tests_run_on_pull_request=pr_test,
        uses_dependabot=bool(dependabot),
        opaque_steps=list(dict.fromkeys(overall.opaque))[:10],
        parse_errors=parser.errors,
    )
    return CollectorResult(data=data, citations=sorted(overall.citations) + dependabot)
