import pytest

from gitcrawl.source import SourceError, _cache_dir_for, parse_github_target


@pytest.mark.parametrize(
    "target",
    [
        "https://github.com/imbaraniii/relink",
        "https://github.com/imbaraniii/relink.git",
        "https://github.com/imbaraniii/relink/",
        "git@github.com:imbaraniii/relink.git",
        "github.com/imbaraniii/relink",
        "imbaraniii/relink",
    ],
)
def test_parse_github_target_accepts_common_forms(target):
    assert parse_github_target(target) == ("imbaraniii", "relink")


@pytest.mark.parametrize(
    "target",
    ["https://gitlab.com/a/b", "https://github.com/a/b/tree/main", "./tests/fixtures/no_tests", "relink"],
)
def test_parse_github_target_refuses_non_github(target):
    with pytest.raises(SourceError, match="GitHub repositories only"):
        parse_github_target(target)


def test_cache_dir_is_already_fully_resolved():
    """Regression: tempfile.gettempdir() returns the unresolved
    /var/folders/... form on macOS, while tools/repo_tools.py resolves
    every path it builds (following the /var -> /private/var symlink).
    If RepoHandle.root isn't resolved the same way, relative_to() raises
    "not in the subpath" on every single file for a URL-cloned repo —
    reproduced live against a real GitHub clone, not a hypothetical.
    A path that's already fully resolved is a fixed point of .resolve().
    """
    cache_dir = _cache_dir_for("https://github.com/example/repo.git")
    assert cache_dir == cache_dir.resolve()


def test_cache_dir_is_deterministic_per_url():
    a = _cache_dir_for("https://github.com/example/repo.git")
    b = _cache_dir_for("https://github.com/example/repo.git")
    other = _cache_dir_for("https://github.com/example/other.git")
    assert a == b
    assert a != other


def test_confinement_check_agrees_with_a_resolved_root():
    """The actual failure mode: build a path the way list_directory does
    (root / rel).resolve()) and confirm relative_to(root) doesn't raise
    when root itself came from _cache_dir_for."""
    root = _cache_dir_for("https://github.com/example/repo.git")
    root.mkdir(parents=True, exist_ok=True)
    try:
        child = (root / "some_file.py").resolve()
        # Must not raise — this is exactly what broke before the fix.
        child.relative_to(root)
    finally:
        root.rmdir()
