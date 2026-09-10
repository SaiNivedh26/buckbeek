"""Repo access — resolve a local path or a git URL to a RepoHandle pinned to
a commit SHA. See docs/design.md §2 stage 1.

Clones use --filter=blob:none (a blobless clone: full commit history and
trees, blobs fetched on demand) rather than mcp-git-ingest's unbounded full
clone, and are cached by URL hash with a TTL rather than reused forever —
see docs/design.md §6 "On mcp-git-ingest".
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
import time
from pathlib import Path

from gitcrawl.config import get_config

_URL_RE = re.compile(r"^(https?://|git@|ssh://)", re.IGNORECASE)


class SourceError(Exception):
    """Raised when a repo cannot be resolved or accessed. Never swallowed
    silently — an evaluation over a repo we failed to fetch must fail loudly,
    not report false-negative findings."""


def _is_url(target: str) -> bool:
    return bool(_URL_RE.match(target.strip()))


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
    # .resolve() matters here, not just style: tempfile.gettempdir() on
    # macOS returns the unresolved /var/folders/... form, while
    # tools/repo_tools.py's path confinement check calls .resolve() on
    # every path it builds (which follows the /var -> /private/var
    # symlink). Without resolving here too, RepoHandle.root and every
    # tool-built path disagree on the same directory's canonical string,
    # and relative_to() raises "not in the subpath" on literally every
    # file for a URL-cloned repo — confirmed live against a real GitHub
    # repo. resolve() is safe on a path that doesn't exist yet (Python's
    # default strict=False just resolves what already exists).
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
            import shutil

            shutil.rmtree(cache_dir, ignore_errors=True)

    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    _run_git(["clone", "--filter=blob:none", "--no-checkout", url, str(cache_dir)])
    _run_git(["checkout"], cwd=cache_dir)
    (cache_dir / ".gitcrawl_fetched_at").touch()
    return cache_dir


class RepoHandleDict(dict):
    """Internal helper; RepoHandle (models.py) is the public contract."""


def resolve(target: str):
    """Resolve target (local path or URL) to a RepoHandle pinned to HEAD's SHA."""
    from gitcrawl.models import RepoHandle

    target = target.strip()
    if _is_url(target):
        root = _clone_or_refresh(target)
        sha = _run_git(["rev-parse", "HEAD"], cwd=root)
        return RepoHandle(root=str(root), origin=target, commit_sha=sha, is_temp_clone=True)

    root = Path(target).expanduser().resolve()
    if not root.exists():
        raise SourceError(f"path does not exist: {root}")
    if not root.is_dir():
        raise SourceError(f"not a directory: {root}")

    git_dir = root
    is_git = (git_dir / ".git").exists()
    if is_git:
        sha = _run_git(["rev-parse", "HEAD"], cwd=root)
    else:
        # Not a git repo at all — still evaluable (e.g. an extracted
        # tarball), just with no real commit identity for the cache key.
        sha = "no-git-" + hashlib.sha256(str(root).encode()).hexdigest()[:12]

    return RepoHandle(root=str(root), origin=target, commit_sha=sha, is_temp_clone=False)
