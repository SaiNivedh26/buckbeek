"""Parser for the fixed clause.md template (defaults/clause.template.md).

Strict on purpose: a rubric that doesn't follow the template is rejected
with every problem listed, rather than half-parsed. Guessing at a weight
or band boundary is exactly the kind of silent error that would make every
score built on top of it wrong without anyone noticing.
"""

from __future__ import annotations

import hashlib
import re
from importlib import resources
from pathlib import Path

from gitcrawl.rubric.models import Band, PillarSpec, Rubric, RubricError

_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_VERSION_RE = re.compile(r"^Version:\s*(\S+)\s*$", re.MULTILINE | re.IGNORECASE)
_PILLAR_RE = re.compile(r"^##\s+Pillar:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_WEIGHT_RE = re.compile(r"^Weight:\s*([\d.]+)\s*%\s*$", re.MULTILINE | re.IGNORECASE)
_FOCUS_RE = re.compile(r"^Focus:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_SUBSECTION_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+?)\s*$", re.MULTILINE)
_BAND_RE = re.compile(r"^(\d+)\s*[-–]\s*(\d+)\s*:\s*(.+)$")

_SUBSECTIONS = {"criteria": "criteria", "bands": "bands", "hard rules": "hard_rules"}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _split_subsections(body: str) -> dict[str, str]:
    matches = list(_SUBSECTION_RE.finditer(body))
    out: dict[str, str] = {}
    for i, m in enumerate(matches):
        key = m.group(1).strip().lower()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        out[key] = body[m.end() : end]
    return out


def _parse_pillar(name: str, body: str, errors: list[str]) -> PillarSpec | None:
    where = f"pillar {name!r}"
    before_subsections = body.split("\n###", 1)[0]

    weight_m = _WEIGHT_RE.search(before_subsections)
    if not weight_m:
        errors.append(f"{where}: missing 'Weight: N%' line")
    focus_m = _FOCUS_RE.search(before_subsections)

    sections = _split_subsections(body)
    unknown = set(sections) - set(_SUBSECTIONS)
    for key in sorted(unknown):
        errors.append(f"{where}: unknown subsection '### {key}' (allowed: Criteria, Bands, Hard rules)")

    criteria = _BULLET_RE.findall(sections.get("criteria", ""))
    if not criteria:
        errors.append(f"{where}: '### Criteria' needs at least one '- ' bullet")

    bands: list[Band] = []
    for raw in _BULLET_RE.findall(sections.get("bands", "")):
        m = _BAND_RE.match(raw)
        if not m:
            errors.append(f"{where}: band line {raw!r} must look like '0-2: description'")
            continue
        low, high = int(m.group(1)), int(m.group(2))
        if low > high or high > 10:
            errors.append(f"{where}: band {low}-{high} is not a valid range within 0-10")
            continue
        bands.append(Band(low=low, high=high, text=m.group(3).strip()))
    if not sections.get("bands"):
        errors.append(f"{where}: missing '### Bands' subsection")
    elif bands:
        bands.sort(key=lambda b: b.low)
        if bands[0].low != 0:
            errors.append(f"{where}: bands must start at 0 (first band starts at {bands[0].low})")
        if bands[-1].high != 10:
            errors.append(f"{where}: bands must end at 10 (last band ends at {bands[-1].high})")
        for prev, nxt in zip(bands, bands[1:], strict=False):
            if nxt.low != prev.high + 1:
                errors.append(
                    f"{where}: bands {prev.low}-{prev.high} and {nxt.low}-{nxt.high} leave a gap or overlap"
                )

    hard_rules = _BULLET_RE.findall(sections.get("hard rules", ""))

    if not weight_m:
        return None
    return PillarSpec(
        id=_slug(name),
        name=name,
        weight=float(weight_m.group(1)) / 100.0,
        focus=focus_m.group(1) if focus_m else "",
        criteria=criteria,
        bands=bands,
        hard_rules=hard_rules,
    )


def parse_rubric(text: str) -> Rubric:
    errors: list[str] = []

    title_m = _TITLE_RE.search(text)
    version_m = _VERSION_RE.search(text)
    if not title_m:
        errors.append("missing '# Title' line")
    if not version_m:
        errors.append("missing 'Version: X' line")

    pillar_matches = list(_PILLAR_RE.finditer(text))
    if not pillar_matches:
        errors.append("no '## Pillar: <name>' sections found")

    pillars: list[PillarSpec] = []
    for i, m in enumerate(pillar_matches):
        end = pillar_matches[i + 1].start() if i + 1 < len(pillar_matches) else len(text)
        spec = _parse_pillar(m.group(1), text[m.end() : end], errors)
        if spec is not None:
            pillars.append(spec)

    ids = [p.id for p in pillars]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"duplicate pillar id {dup!r} (pillar names must be distinct)")
    if pillars and not errors:
        total = sum(p.weight for p in pillars)
        if abs(total - 1.0) > 1e-6:
            errors.append(f"pillar weights must add up to 100%, got {total * 100:g}%")

    if errors:
        raise RubricError(errors)

    return Rubric(
        title=title_m.group(1),
        version=version_m.group(1),
        pillars=pillars,
        content_hash=hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16],
    )


def load_rubric(path: Path | str | None = None) -> Rubric:
    """Parse a user clause.md, or the bundled default when path is None."""
    if path is None:
        return load_default_rubric()
    return parse_rubric(Path(path).read_text(encoding="utf-8"))


def load_default_rubric() -> Rubric:
    return parse_rubric(default_rubric_text())


def default_rubric_text() -> str:
    return resources.files("gitcrawl").joinpath("defaults/clause.md").read_text(encoding="utf-8")
