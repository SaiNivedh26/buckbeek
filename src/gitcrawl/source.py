"""Repo access: resolve a GitHub repository to a RepoHandle pinned to a commit SHA.

Clones use --filter=blob:none (a blobless clone: history and trees, blobs
fetched on demand) and are cached by URL hash with a TTL, rather than an
unbounded full clone reused forever.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from gitcrawl.config import get_config


class SourceError(Exception):
    """Raised when a repo cannot be resolved or accessed. Never swallowed
    silently — an evaluation over a repo we failed to fetch must fail loudly,
    not report false-negative facts."""


_GITHUB_RE = re.compile(
    r"^(?:https?://(?:www\.)?github\.com/|git@github\.com:|ssh://git@github\.com/|github\.com/)?"
    r"(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/(?P<name>[A-Za-z0-9._-]+?)(?:\.git)?/?$"
)


def parse_github_target(target: str) -> tuple[str, str]:
    """(owner, name) from a GitHub URL, SSH remote, or owner/repo shorthand.
    GitCrawl evaluates GitHub repositories only — anything else is refused
    loudly rather than evaluated without the GitHub data its plans rely on."""
    m = _GITHUB_RE.match(target.strip())
    if not m:
        raise SourceError(
            f"not a GitHub repository: {target!r}. GitCrawl evaluates GitHub repositories only — "
            "use https://github.com/<owner>/<repo> or <owner>/<repo>."
        )
    return m.group("owner"), m.group("name")


def _run_git(args: list[str], cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except FileNotFoundError as e:
        raise SourceError("git is not installed or not on PATH") from e
    except subprocess.TimeoutExpired as e:
        raise SourceError(f"git {' '.join(args)} timed out") from e
    if result.returncode != 0:
        raise SourceError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _cache_dir_for(url: str) -> Path:
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    # .resolve() matters here, not just style: tempfile.gettempdir() on macOS
    # returns the unresolved /var/folders/... form, while path confinement in
    # collectors/files.py and tools/repo_tools.py resolves every path it builds
    # (following /var -> /private/var). Without resolving here too, every
    # confinement check on a cloned repo raises "not in the subpath" —
    # confirmed live against a real GitHub repo.
    return (Path(tempfile.gettempdir()) / "gitcrawl_clones" / url_hash).resolve()


def _clone_or_refresh(url: str) -> Path:
    cfg = get_config()
    cache_dir = _cache_dir_for(url)
    ttl_seconds = cfg.cache.clone_ttl_hours * 3600

    if cache_dir.exists():
        marker = cache_dir / ".gitcrawl_fetched_at"
        stale = True
        if marker.exists():
            age = time.time() - marker.stat().st_mtime
            stale = age > ttl_seconds
        if not stale:
            return cache_dir
        try:
            _run_git(["fetch", "--depth", "1", "origin"], cwd=cache_dir)
            _run_git(["reset", "--hard", "origin/HEAD"], cwd=cache_dir)
            marker.touch()
            return cache_dir
        except SourceError:
            # Cache is corrupt or origin/HEAD unavailable — reclone rather
            # than silently serving a stale checkout.
            shutil.rmtree(cache_dir, ignore_errors=True)

    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    _run_git(["clone", "--filter=blob:none", "--no-checkout", url, str(cache_dir)])
    _run_git(["checkout"], cwd=cache_dir)
    (cache_dir / ".gitcrawl_fetched_at").touch()
    return cache_dir


def resolve(target: str):
    """Resolve a GitHub repository to a RepoHandle pinned to HEAD's SHA."""
    from gitcrawl.models import RepoHandle

    owner, name = parse_github_target(target)
    origin = f"https://github.com/{owner}/{name}"
    root = _clone_or_refresh(f"{origin}.git")
    sha = _run_git(["rev-parse", "HEAD"], cwd=root)
    return RepoHandle(root=str(root), origin=origin, commit_sha=sha, is_temp_clone=True, owner=owner, name=name)


def local_handle(path: Path | str, owner: str = "local", name: str | None = None):
    """A RepoHandle over an already-checked-out directory. Not reachable from
    the CLI — used by tests (fixtures have no .git) and by library callers
    that manage their own checkout."""
    from gitcrawl.models import RepoHandle

    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise SourceError(f"not a directory: {root}")
    if (root / ".git").exists():
        sha = _run_git(["rev-parse", "HEAD"], cwd=root)
    else:
        sha = "no-git-" + hashlib.sha256(str(root).encode()).hexdigest()[:12]
    return RepoHandle(root=str(root), origin=str(root), commit_sha=sha, owner=owner, name=name or root.name)
