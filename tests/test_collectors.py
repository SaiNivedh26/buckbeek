from pathlib import Path

import pytest
from pydantic import BaseModel

from gitcrawl.collectors import (
    REGISTRY,
    CheckRequest,
    CollectorContext,
    CollectorResult,
    RepoFiles,
    collect,
    collector,
    glob_match,
    run_check,
    validate_check,
)
from gitcrawl.config import get_config
from gitcrawl.source import local_handle
from gitcrawl.storage import db

FIXTURES = Path(__file__).parent / "fixtures"


def _ctx(root: Path) -> CollectorContext:
    return CollectorContext(handle=local_handle(root), cfg=get_config(), files=RepoFiles(root))


class _CountOut(BaseModel):
    calls: int


@pytest.fixture
def temp_collector():
    """Register throwaway collectors for a test and always unregister them."""
    added: list[str] = []

    def register(name, func, **kwargs):
        collector(name, description="test", category="files", output=_CountOut, **kwargs)(func)
        added.append(name)

    yield register
    for name in added:
        REGISTRY.pop(name, None)


def test_glob_match_rules():
    assert glob_match("docs/SECURITY.md", "security.md")
    assert glob_match(".github/workflows/ci.yml", ".github/workflows/*.yml")
    assert glob_match("ci.yml", "**/ci.yml")
    assert not glob_match("src/app.py", "tests/*.py")


async def test_inventory_on_fixture_excludes_vendored_and_flags_community_files():
    fact = await run_check(CheckRequest("inv", "repo.inventory"), _ctx(FIXTURES / "vendored_heavy"))
    assert fact.ok
    assert fact.data["excluded_files"] > 0
    assert not any("node_modules" in p for p in fact.data["ranked_shortlist"])
    assert fact.data["has_readme"] is True

    no_tests = await run_check(CheckRequest("inv", "repo.inventory"), _ctx(FIXTURES / "no_tests"))
    assert no_tests.data["has_license"] is True
    assert no_tests.data["has_security_policy"] is False


async def test_file_exists_and_contains():
    ctx = _ctx(FIXTURES / "well_tested")
    readme = await run_check(CheckRequest("r", "file.exists", {"globs": ["README.md"]}), ctx)
    assert readme.data["found"] is True
    security = await run_check(CheckRequest("s", "file.exists", {"globs": ["SECURITY.md"]}), ctx)
    assert security.data == {"found": False, "count": 0, "paths": []}

    defs = await run_check(CheckRequest("d", "file.contains", {"globs": ["*.py"], "pattern": r"^def "}), ctx)
    assert defs.data["found"] is True
    assert all(m.split(":")[0].endswith(".py") for m in defs.data["matches"])


async def test_manifest_field_reads_nested_keys(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts": {"test": "jest --coverage"}}')
    ctx = _ctx(tmp_path)
    def req(key):
        return CheckRequest("m", "manifest.field", {"file": "package.json", "key_path": key})

    hit = await run_check(req("scripts.test"), ctx)
    assert hit.data == {"file_exists": True, "found": True, "value": "jest --coverage"}
    miss = await run_check(req("scripts.lint"), ctx)
    assert miss.data["found"] is False


def test_validate_check_rejects_unknown_collectors_and_bad_params():
    assert validate_check("nope.collector", {}) == ["unknown collector 'nope.collector'"]
    errors = validate_check("file.contains", {"globs": ["*.py"], "pattern": "("})
    assert errors and "invalid regex" in errors[0]
    assert validate_check("file.exists", {"globs": []})
    assert validate_check("file.exists", {"globs": ["a"], "surprise": 1})
    assert validate_check("file.exists", {"globs": ["README.md"]}) == []


async def test_crashing_collector_becomes_an_error_fact_not_data(temp_collector, caplog):
    def boom(ctx, params):
        raise RuntimeError("disk on fire")

    temp_collector("test.boom", boom)
    fact = await run_check(CheckRequest("b", "test.boom"), _ctx(FIXTURES / "no_tests"))
    assert fact.error and "disk on fire" in fact.error
    assert fact.data == {}
    assert "test.boom" in caplog.text  # logged, never silent


async def test_github_collector_without_client_errors_clearly(temp_collector):
    temp_collector("test.gh", lambda ctx, params: CollectorResult(_CountOut(calls=1)), requires_github=True)
    fact = await run_check(CheckRequest("g", "test.gh"), _ctx(FIXTURES / "no_tests"))
    assert fact.error and "GitHub token" in fact.error


async def test_collect_dedupes_identical_checks_and_caches_successes(temp_collector):
    calls = {"n": 0}

    def counting(ctx, params):
        calls["n"] += 1
        return CollectorResult(_CountOut(calls=calls["n"]))

    temp_collector("test.counting", counting)
    ctx = _ctx(FIXTURES / "no_tests")
    conn = db.connect(":memory:")
    reqs = [CheckRequest("a", "test.counting"), CheckRequest("b", "test.counting")]

    first = await collect(reqs, ctx, conn=conn)
    assert calls["n"] == 1
    assert set(first) == {"a", "b"} and first["b"].check_id == "b"

    second = await collect(reqs, ctx, conn=conn)
    assert calls["n"] == 1  # served from cache
    assert second["a"].cached and second["a"].data == {"calls": 1}


async def test_failed_facts_are_not_cached(temp_collector):
    state = {"fail": True}

    def flaky(ctx, params):
        if state["fail"]:
            raise RuntimeError("transient")
        return CollectorResult(_CountOut(calls=1))

    temp_collector("test.flaky", flaky)
    ctx = _ctx(FIXTURES / "no_tests")
    conn = db.connect(":memory:")
    assert not (await collect([CheckRequest("f", "test.flaky")], ctx, conn=conn))["f"].ok
    state["fail"] = False
    retried = (await collect([CheckRequest("f", "test.flaky")], ctx, conn=conn))["f"]
    assert retried.ok and not retried.cached


def test_repo_files_confines_and_memoizes(tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    files = RepoFiles(tmp_path)
    assert files.read_text("../../etc/passwd") is None
    assert files.read_text("a.txt") == "hello"
    (tmp_path / "a.txt").write_text("changed")
    assert files.read_text("./a.txt") == "hello"  # one read per run
    assert files.read_paths == ["a.txt"]
