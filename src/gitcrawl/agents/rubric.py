"""Parses clause.md §3.x into pillar -> verbatim rubric text. A scorer
receives exactly the section for its own pillar — never the whole
document — which is part of what keeps pillars from leaking into each
other. See docs/design.md §3 "Scorers" and §9.

clause.md ships packaged inside gitcrawl/ (see pyproject.toml) so it
travels with the installed library rather than depending on a docs/
folder existing relative to the current working directory. docs/clause.md
at the project root is the same document, kept for human reference — if
you edit the rubric, edit gitcrawl/clause.md (the one actually read at
runtime) and copy the change back to docs/clause.md, or vice versa.
"""

from __future__ import annotations

import functools
import re
from importlib import resources

# clause.md §3.x section number -> our pillar key.
_SECTION_TO_PILLAR: dict[str, str] = {
    "3.1": "code_health",
    "3.2": "test_coverage",
    "3.3": "ci_cd",
    "3.4": "issue_management",
    "3.5": "community",
}

_SECTION_RE = re.compile(r"^### (3\.\d) (.+)$", re.MULTILINE)


class RubricError(Exception):
    """Raised when clause.md can't be parsed into the expected 5 sections."""


def _read_clause_md() -> str:
    return resources.files("gitcrawl").joinpath("clause.md").read_text(encoding="utf-8")


@functools.lru_cache(maxsize=1)
def load_rubric() -> dict[str, str]:
    """Returns {pillar_key: verbatim §3.x section text (heading included)}."""
    text = _read_clause_md()
    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        raise RubricError("no §3.x sections found in clause.md")

    sections: dict[str, str] = {}
    for i, m in enumerate(matches):
        section_num = m.group(1)
        pillar = _SECTION_TO_PILLAR.get(section_num)
        if pillar is None:
            continue
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        # Each §3.x section is terminated by a "---" divider before the
        # next section (see clause.md) — trim it so the rubric text handed
        # to a scorer doesn't trail off into markdown noise.
        body = re.sub(r"\n---\s*$", "", body).strip()
        sections[pillar] = body

    missing = set(_SECTION_TO_PILLAR.values()) - set(sections)
    if missing:
        raise RubricError(f"clause.md is missing rubric sections for: {sorted(missing)}")
    return sections


def rubric_version() -> str:
    """Pulled from clause.md §6, so a version bump there is picked up
    without touching config.toml (which also carries it for convenience —
    see docs/design.md §10)."""
    text = _read_clause_md()
    m = re.search(r"\*\*Version:\*\*\s*([0-9.]+)", text)
    return m.group(1) if m else "unknown"
