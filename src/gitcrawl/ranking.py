"""Ranks candidate files by expected information value, so an investigator's
first tool calls land on the most informative files rather than the
alphabetically-first ones. See docs/design.md §5.3.

Phase 1 signals: entrypoints, size outliers, one representative per
directory. Churn and fan-in ranking (phase 2) slot in here without touching
callers — see docs/design.md §14.
"""

from __future__ import annotations

import re
from pathlib import Path

_ENTRYPOINT_RE = re.compile(
    r"^(main|app|index|cli|server|__main__|setup|manage)\.\w+$", re.IGNORECASE
)

# Rough per-language "this file is unusually large" threshold, in lines.
_SIZE_OUTLIER_LINES = 400


def _line_count(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def rank_candidates(root: Path, relative_paths: list[str], limit: int) -> list[str]:
    """Return up to `limit` paths from relative_paths, most informative first.

    Scoring is a simple weighted sum, not a model call — this must stay
    cheap enough to run inside the zero-token survey.
    """
    scored: list[tuple[float, str]] = []
    seen_dirs: set[str] = set()

    for rel in relative_paths:
        p = root / rel
        name = p.name
        parent = str(Path(rel).parent)
        score = 0.0

        if _ENTRYPOINT_RE.match(name):
            score += 10.0

        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        if size == 0:
            score -= 5.0  # empty files are never informative
        elif size > 50_000:
            score += 4.0
        elif size > 15_000:
            score += 2.0

        # One representative per directory: the first file seen from a new
        # directory gets a bonus, so breadth beats depth in one folder.
        if parent not in seen_dirs:
            score += 3.0
            seen_dirs.add(parent)

        depth = rel.count("/")
        score -= depth * 0.3  # prefer shallower files, all else equal

        scored.append((score, rel))

    scored.sort(key=lambda t: (-t[0], t[1]))
    return [rel for _, rel in scored[:limit]]
