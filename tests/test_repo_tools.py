from pathlib import Path

from gitcrawl.models import BudgetLedger
from gitcrawl.tools.repo_tools import (
    BUDGET_EXHAUSTED_MARKER,
    ToolContext,
    build_tools,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _tools(root: Path, calls: int = 10, pillar: str = "test_coverage"):
    ledger = BudgetLedger(allocated={pillar: calls}, spent={pillar: 0})
    ctx = ToolContext(root=root, pillar=pillar, ledger=ledger)
    list_directory, read_file, search_repo = build_tools(ctx)
    return list_directory, read_file, search_repo, ledger


def test_read_file_blocks_path_escape():
    _, read_file, _, _ = _tools(FIXTURES / "no_tests")
    result = read_file.entrypoint(path="../../../../etc/passwd")
    assert "escapes the repository root" in result


def test_read_file_missing_returns_explicit_marker_not_content():
    _, read_file, _, _ = _tools(FIXTURES / "no_tests")
    result = read_file.entrypoint(path="src/does_not_exist.py")
    assert "ERROR: file not found" in result
    # Must never look like real file content wrapped as if it were found.
    assert "def " not in result


def test_read_file_returns_real_content_wrapped_as_untrusted():
    _, read_file, _, _ = _tools(FIXTURES / "no_tests")
    result = read_file.entrypoint(path="src/app.py")
    assert "def add(a, b):" in result
    assert "<untrusted-repo-content" in result


def test_list_directory_never_surfaces_excluded_paths():
    list_directory, _, _, _ = _tools(FIXTURES / "vendored_heavy")
    result = list_directory.entrypoint(path=".")
    for junk in ("node_modules", ".venv", "package-lock.json", "dist/"):
        assert junk not in result


def test_list_directory_root_call_reaches_nested_files():
    """Regression: list_directory(".") once only walked the root's own
    directory and never descended, so a file that only exists under
    src/ or tests/ was invisible to an investigator that starts by
    listing "." — exactly how every investigator brief tells it to start.
    """
    list_directory, _, _, _ = _tools(FIXTURES / "well_tested", calls=5)
    result = list_directory.entrypoint(path=".")
    assert "src/parser.py" in result or "src/payments.py" in result
    assert "tests/test_parser.py" in result


def test_list_directory_specific_subdir_lists_its_contents():
    list_directory, _, _, _ = _tools(FIXTURES / "well_tested", calls=5)
    result = list_directory.entrypoint(path="tests")
    assert "test_parser.py" in result


def test_budget_exhausts_after_allocated_calls():
    list_directory, read_file, _, ledger = _tools(FIXTURES / "no_tests", calls=2)
    r1 = list_directory.entrypoint(path=".")
    assert r1 != BUDGET_EXHAUSTED_MARKER
    r2 = read_file.entrypoint(path="src/app.py")
    assert r2 != BUDGET_EXHAUSTED_MARKER
    # Third call on a 2-call budget must refuse, not silently succeed.
    r3 = read_file.entrypoint(path="README.md")
    assert r3 == BUDGET_EXHAUSTED_MARKER


def test_search_repo_finds_matches_and_excludes_junk():
    _, _, search_repo, _ = _tools(FIXTURES / "vendored_heavy", calls=5)
    result = search_repo.entrypoint(pattern="def main")
    assert "src/app.py" in result
    assert "node_modules" not in result


def test_read_file_limit_truncates_to_requested_line_count():
    """A model asking for `limit` on a large file is a reasonable request
    (e.g. a quick look at a long CHANGELOG without spending the whole
    budget on it) — confirmed live that ministral-8b tried exactly this
    and got a hard pydantic rejection because the parameter didn't exist.
    """
    _, read_file, _, _ = _tools(FIXTURES / "well_tested", calls=5)
    full = read_file.entrypoint(path="src/parser.py")
    limited = read_file.entrypoint(path="src/parser.py", limit=3)

    assert limited != full
    assert "truncated at 3 lines" in limited
    assert len(full.splitlines()) > len(limited.splitlines())


def test_failed_call_hook_counts_and_reraises():
    """The regression this guards: a malformed call (extra kwarg the tool
    doesn't accept) is rejected by pydantic before _meter() ever runs, so
    it must not silently vanish from the scope log — it's still a real
    API call a weaker model burned.

    Note: `.entrypoint(...)` (used by every other test in this file) calls
    the raw function directly and does NOT go through tool_hooks — Agno
    only wraps hooks around the full agent-dispatch path (FunctionCall.
    execute), a different call than the one these tests use. So the hook
    itself is unit-tested directly here rather than through .entrypoint().
    """
    from gitcrawl.tools.repo_tools import _make_failed_call_hook

    root = FIXTURES / "no_tests"
    ledger = BudgetLedger(allocated={"test_coverage": 5}, spent={"test_coverage": 0})
    ctx = ToolContext(root=root, pillar="test_coverage", ledger=ledger)
    hook = _make_failed_call_hook(ctx)

    def failing_func(**kwargs):
        raise TypeError("unexpected keyword argument: offset")

    try:
        hook("read_file", failing_func, {"path": "src/app.py", "offset": 10})
        raised = False
    except TypeError:
        raised = True

    assert raised, "the hook must re-raise, not swallow, the underlying failure"
    assert ledger.failed_calls.get("test_coverage", 0) == 1

    def ok_func(**kwargs):
        return "fine"

    assert hook("read_file", ok_func, {"path": "src/app.py"}) == "fine"
    assert ledger.failed_calls.get("test_coverage", 0) == 1  # unchanged on success
