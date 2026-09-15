"""Shared, memoized access to the checked-out repository for one run.

Collectors and agent tools both read through RepoFiles, so a file is walked
and read at most once per run no matter how many checks or agents need it —
the fix for v1's "package.json read by 4 of 5 agents". Exclusion rules
(tools/filters.py) and path confinement apply here, below every consumer.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from gitcrawl.tools.filters import is_binary_extension, is_excluded_dir, is_excluded_file


@dataclass
class Inventory:
    total_files: int
    excluded_count: int
    files: list[str]  # candidate (non-excluded) files, repo-relative, posix, sorted
    root_files: list[str] = field(default_factory=list)
    top_level_dirs: list[str] = field(default_factory=list)


def glob_match(rel_path: str, pattern: str) -> bool:
    """Case-insensitive. A pattern without "/" matches the file name in any
    directory ("SECURITY.md"); a pattern with "/" matches the whole path, and a
    leading "**/" also matches at the root (".github/**/*.yml")."""
    rel = rel_path.lower()
    pat = pattern.lower().removeprefix("./")
    if "/" not in pat:
        return fnmatch.fnmatchcase(PurePosixPath(rel).name, pat)
    if fnmatch.fnmatchcase(rel, pat):
        return True
    return pat.startswith("**/") and fnmatch.fnmatchcase(rel, pat[3:])


def _count_files_under(dir_path: str) -> int:
    count = 0
    for _dirpath, _dirnames, filenames in os.walk(dir_path):
        count += len(filenames)
    return count


class RepoFiles:
    def __init__(self, root: Path | str, max_file_bytes: int = 100_000):
        self.root = Path(root).resolve()
        self.max_file_bytes = max_file_bytes
        self._inventory: Inventory | None = None
        self._texts: dict[str, str | None] = {}

    # --- inventory -------------------------------------------------------
    def inventory(self) -> Inventory:
        if self._inventory is None:
            self._inventory = self._walk()
        return self._inventory

    def _walk(self) -> Inventory:
        files: list[str] = []
        root_files: list[str] = []
        top_dirs: list[str] = []
        total = excluded = 0
        for dirpath, dirnames, filenames in os.walk(self.root):
            for d in [d for d in dirnames if is_excluded_dir(d)]:
                n = _count_files_under(os.path.join(dirpath, d))
                excluded += n
                total += n
            dirnames[:] = sorted(d for d in dirnames if not is_excluded_dir(d))
            rel_dir = os.path.relpath(dirpath, self.root).replace(os.sep, "/")
            if rel_dir == ".":
                top_dirs = list(dirnames)
            for fname in filenames:
                total += 1
                rel = fname if rel_dir == "." else f"{rel_dir}/{fname}"
                if rel_dir == ".":
                    root_files.append(fname)
                if is_excluded_file(fname):
                    excluded += 1
                    continue
                files.append(rel)
        return Inventory(
            total_files=total,
            excluded_count=excluded,
            files=sorted(files),
            root_files=sorted(root_files),
            top_level_dirs=top_dirs,
        )

    def files(self) -> list[str]:
        return self.inventory().files

    def glob(self, patterns: list[str] | str) -> list[str]:
        pats = [patterns] if isinstance(patterns, str) else patterns
        return [f for f in self.files() if any(glob_match(f, p) for p in pats)]

    def exists(self, rel_path: str) -> bool:
        path = self.resolve(rel_path)
        return path is not None and path.is_file()

    # --- reads -----------------------------------------------------------
    def resolve(self, rel_path: str) -> Path | None:
        """Absolute path if it stays inside the repo root, else None."""
        candidate = (self.root / rel_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError:
            return None
        return candidate

    def read_text(self, rel_path: str) -> str | None:
        """File text (byte-capped), or None if missing, outside the repo,
        excluded, binary, or not UTF-8. Memoized per run."""
        key = rel_path.removeprefix("./")
        if key in self._texts:
            return self._texts[key]
        text = self._read(key)
        self._texts[key] = text
        return text

    def _read(self, rel_path: str) -> str | None:
        path = self.resolve(rel_path)
        if path is None or not path.is_file():
            return None
        if is_binary_extension(path.name) or is_excluded_file(path.name):
            return None
        if any(is_excluded_dir(part) for part in Path(rel_path).parts[:-1]):
            return None
        try:
            raw = path.read_bytes()[: self.max_file_bytes]
            return raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def line_count(self, rel_path: str) -> int:
        text = self.read_text(rel_path)
        return 0 if text is None else text.count("\n") + (0 if text.endswith("\n") or not text else 1)

    @property
    def read_paths(self) -> list[str]:
        return sorted(p for p, t in self._texts.items() if t is not None)
