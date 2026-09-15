from pathlib import Path

from gitcrawl.collectors import CheckRequest, CollectorContext, RepoFiles, run_check
from gitcrawl.config import get_config
from gitcrawl.source import local_handle

FIXTURES = Path(__file__).parent / "fixtures"


async def _ci(root: Path):
    ctx = CollectorContext(handle=local_handle(root), cfg=get_config(), files=RepoFiles(root))
    fact = await run_check(CheckRequest("ci", "ci.config"), ctx)
    assert fact.ok, fact.error
    return fact


async def test_ci_rich_follows_reusable_workflows_composite_actions_make_and_scripts():
    fact = await _ci(FIXTURES / "ci_rich")
    d = fact.data
    assert d["has_ci"] and d["systems"] == ["github_actions"]
    assert d["triggers_push"] and d["triggers_pull_request"]
    # test step lives only in the reusable workflow called from ci.yml
    assert d["has_test_step"] and d["tests_run_on_pull_request"]
    assert d["has_coverage_step"] and d["coverage_threshold_enforced"]
    # `make lint` -> Makefile -> ruff; `./scripts/audit.sh` -> pip-audit
    assert d["has_lint_step"] and d["has_security_step"]
    assert d["has_deploy_step"]  # release.yml publishes to PyPI
    assert d["uses_dependabot"]
    assert d["opaque_steps"] == ['echo "done"']
    assert {"Makefile", "scripts/audit.sh", ".github/workflows/reusable-test.yml"} <= set(fact.citations)

    release = next(w for w in d["workflows"] if w["path"].endswith("release.yml"))
    assert release["triggers"] == ["push"] and release["step_kinds"] == ["deploy"]


async def test_no_ci_repo():
    d = (await _ci(FIXTURES / "no_tests")).data
    assert d["has_ci"] is False
    assert d["workflow_count"] == 0
    assert not d["tests_run_on_pull_request"]


async def test_push_only_workflow_with_typecheck_and_package_script(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "deploy.yml").write_text(
        "on:\n  push:\n    branches: [main]\njobs:\n  deploy:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - run: npm ci\n      - run: npm run typecheck\n      - run: npx supabase db push\n"
    )
    (tmp_path / "package.json").write_text('{"scripts": {"typecheck": "tsc --noEmit"}}')
    d = (await _ci(tmp_path)).data
    assert d["triggers_push"] and not d["triggers_pull_request"]
    assert d["has_lint_step"] and d["has_deploy_step"]
    assert not d["has_test_step"] and not d["tests_run_on_pull_request"]


async def test_invalid_yaml_is_reported_not_crashed(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "bad.yml").write_text("on: [push\njobs: {")
    d = (await _ci(tmp_path)).data
    assert d["has_ci"] is True
    assert d["parse_errors"] and "invalid YAML" in d["parse_errors"][0]
