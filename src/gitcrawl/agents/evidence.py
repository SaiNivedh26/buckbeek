"""Rendering facts and judgement answers as short text for prompts and reports.

Rendering is code, not model output, so the same facts always produce the
same text — which is also what makes prompt hashes usable as cache keys.
"""

from __future__ import annotations

import json
from typing import Any

from gitcrawl.collectors.base import Fact


def _value(v: Any, max_items: int) -> str:
    if isinstance(v, bool) or v is None:
        return json.dumps(v)
    if isinstance(v, float):
        return f"{v:.3g}"
    if isinstance(v, str):
        return v if len(v) <= 120 else v[:117] + "..."
    if isinstance(v, list):
        if not v:
            return "[]"
        if isinstance(v[0], dict):
            text = json.dumps(v[:3], separators=(",", ":"), default=str)
            text = text if len(text) <= 400 else text[:397] + "..."
            return f"{len(v)} item(s): {text}"
        shown = ", ".join(_value(x, max_items) for x in v[:max_items])
        return f"[{shown}{', …' if len(v) > max_items else ''}]"
    if isinstance(v, dict):
        text = json.dumps(v, separators=(",", ":"), default=str)
        return text if len(text) <= 300 else text[:297] + "..."
    return str(v)


def format_fact(fact: Fact, max_items: int = 8) -> str:
    head = f"{fact.check_id} [{fact.collector}]"
    if not fact.ok:
        return f"{head}: UNAVAILABLE ({fact.error})"
    fields = "; ".join(f"{k}={_value(v, max_items)}" for k, v in fact.data.items())
    return f"{head}: {fields}"
