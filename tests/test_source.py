
from gitcrawl.source import _cache_dir_for


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
