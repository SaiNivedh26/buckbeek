"""The three tools an investigator gets: list_directory, read_file,
search_repo. See docs/design.md §6.

Every tool in this module is built by build_tools() for one specific
(RepoHandle, pillar, BudgetLedger) — never shared across pillars, because
metering and citations both need to know which pillar spent the call.
Rules enforced here, not left to agent discipline:

  - paths are confined to the repo root (no ../ escape)
  - excluded paths (tools/filters.py) are never returned
  - every call is metered against the pillar's budget; over budget returns
    a marker, not an error
  - a missing/unreadable file returns an explicit marker, never fabricated
    content (the defect that makes mcp-git-ingest unusable — see §6)
  - every result is wrapped as untrusted data (tools/wrapping.py)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from agno.tools import tool
from agno.tools.function import Function

from gitcrawl.config import get_config
from gitcrawl.models import BudgetLedger
from gitcrawl.ranking import rank_candidates
from gitcrawl.tools.filters import is_binary_extension, is_excluded_dir, is_excluded_file
from gitcrawl.tools.wrapping import wrap_untrusted

BUDGET_EXHAUSTED_MARKER = "BUDGET_EXHAUSTED: no tool calls remain for this pillar."
NOT_FOUND_MARKER = "ERROR: file not found: {path}"
ESCAPE_MARKER = "ERROR: path escapes the repository root, refused: {path}"
BINARY_MARKER = "ERROR: binary or excluded file, not readable as text: {path}"


@dataclass
class ToolContext:
    root: Path
    pillar: str
    ledger: BudgetLedger


def _resolve_confined(root: Path, rel_path: str) -> Path | None:
    """Returns the resolved absolute path if it stays inside root, else None."""
    candidate = (root / rel_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def _meter(ctx: ToolContext) -> bool:
    """Returns True if a call may proceed; spends one call if so."""
    if ctx.ledger.remaining(ctx.pillar) <= 0:
        return False
    ctx.ledger.spend(ctx.pillar)
    return True


def build_tools(ctx: ToolContext) -> list[Function]:
    """Build the three repo tools bound to one investigator's context."""
    cfg = get_config()

    @tool(
        name="list_directory",
        description="List files under a path in the repository, ranked by likely relevance.",
    )
    def list_directory(path: str = ".") -> str:
        """List files under `path` (relative to the repo root).
        Excludes vendored/generated/binary content automatically.

        Calling this with "." (the root) walks the WHOLE repository and
        returns a ranked shortlist of the most informative files anywhere
        in the tree — not just what sits at the top level (see
        docs/design.md §5.3). Calling it with a specific subdirectory
        instead lists that directory's immediate entries, files and
        sub-folder names both, unranked, so you can navigate further.

        Args:
            path: Directory path relative to the repo root. Use "." for a
                repo-wide ranked shortlist, or a specific path to see what's
                directly inside that folder.
        """
        if not _meter(ctx):
            return BUDGET_EXHAUSTED_MARKER

        resolved = _resolve_confined(ctx.root, path)
        if resolved is None:
            return ESCAPE_MARKER.format(path=path)
        if not resolved.exists() or not resolved.is_dir():
            return NOT_FOUND_MARKER.format(path=path)

        if path == ".":
            rels: list[str] = []
            for dirpath, dirnames, filenames in os.walk(resolved):
                dirnames[:] = [d for d in dirnames if not is_excluded_dir(d)]
                for fname in filenames:
                    if is_excluded_file(fname):
                        continue
                    full = Path(dirpath) / fname
                    rels.append(str(full.relative_to(ctx.root)))
            ranked = rank_candidates(ctx.root, rels, limit=cfg.budget.shortlist_size)
            body = "\n".join(ranked) if ranked else "(no candidate files anywhere in the repo)"
        else:
            entries: list[str] = []
            for entry in sorted(resolved.iterdir()):
                if entry.is_dir():
                    if is_excluded_dir(entry.name):
                        continue
                    entries.append(f"{entry.name}/")
                elif not is_excluded_file(entry.name):
                    entries.append(entry.name)
            body = "\n".join(entries) if entries else "(empty, or everything here is excluded)"

        return wrap_untrusted(f"list_directory({path})", body)

    @tool(name="read_file", description="Read a file's text content from the repository.")
    def read_file(path: str) -> str:
        """Read the contents of `path` (relative to the repo root).

        Args:
            path: File path relative to the repo root.
        """
        if not _meter(ctx):
            return BUDGET_EXHAUSTED_MARKER

        resolved = _resolve_confined(ctx.root, path)
        if resolved is None:
            return ESCAPE_MARKER.format(path=path)
        if not resolved.exists() or not resolved.is_file():
            return NOT_FOUND_MARKER.format(path=path)
        if is_binary_extension(resolved.name):
            return BINARY_MARKER.format(path=path)

        try:
            raw = resolved.read_bytes()
        except OSError:
            return NOT_FOUND_MARKER.format(path=path)

        truncated = False
        if len(raw) > cfg.budget.max_file_bytes:
            raw = raw[: cfg.budget.max_file_bytes]
            truncated = True

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return BINARY_MARKER.format(path=path)

        ctx.ledger.examined_files += 1
        if truncated:
            text += f"\n\n[TRUNCATED at {cfg.budget.max_file_bytes} bytes]"
        return wrap_untrusted(path, text)

    @tool(name="search_repo", description="Search the repository for a regex pattern.")
    def search_repo(pattern: str, file_glob: str = "*") -> str:
        """Search candidate files for a regex pattern and return matching
        lines with their file and line number.

        Args:
            pattern: A regular expression to search for.
            file_glob: Restrict the search to files matching this glob (default: all candidate files).
        """
        if not _meter(ctx):
            return BUDGET_EXHAUSTED_MARKER

        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f"ERROR: invalid regex: {e}"

        matches: list[str] = []
        max_matches = 25
        for dirpath, dirnames, filenames in os.walk(ctx.root):
            dirnames[:] = [d for d in dirnames if not is_excluded_dir(d)]
            for fname in filenames:
                if is_excluded_file(fname):
                    continue
                if file_glob != "*" and not Path(fname).match(file_glob):
                    continue
                full = Path(dirpath) / fname
                rel = str(full.relative_to(ctx.root))
                try:
                    with full.open("r", encoding="utf-8", errors="ignore") as f:
                        for lineno, line in enumerate(f, start=1):
                            if regex.search(line):
                                matches.append(f"{rel}:{lineno}: {line.strip()[:200]}")
                                if len(matches) >= max_matches:
                                    break
                except OSError:
                    continue
                if len(matches) >= max_matches:
                    break
            if len(matches) >= max_matches:
                break

        body = "\n".join(matches) if matches else "(no matches)"
        return wrap_untrusted(f"search_repo(pattern={pattern!r}, file_glob={file_glob!r})", body)

    return [list_directory, read_file, search_repo]
