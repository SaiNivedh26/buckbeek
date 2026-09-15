"""Runs a set of checks for one repository: de-duplicated, concurrent, cached.

Two checks that use the same collector with the same params run once. File
collectors are cached by commit SHA (the repo can't change under a SHA);
GitHub collectors are cached by time bucket instead, because issues, PRs and
CI runs change independently of the commit. Failed facts are never cached —
a transient error must be retried on the next run, not served back forever.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime

from gitcrawl.collectors.base import REGISTRY, CheckRequest, CollectorContext, Fact, params_hash, run_check


def snapshot_bucket(ttl_hours: int, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return str(int(now.timestamp() // (max(ttl_hours, 1) * 3600)))


def default_requests(include_github: bool = True) -> list[CheckRequest]:
    """Every collector that needs no parameters, id'd by its own name —
    what `gitcrawl facts` runs when no plan is given."""
    return [
        CheckRequest(id=spec.name, collector=spec.name)
        for spec in REGISTRY.values()
        if not spec.has_required_params() and (include_github or not spec.requires_github)
    ]


async def collect(
    requests: list[CheckRequest],
    ctx: CollectorContext,
    *,
    conn: sqlite3.Connection | None = None,
    now: datetime | None = None,
) -> dict[str, Fact]:
    from gitcrawl.storage import cache

    groups: dict[tuple[str, str], list[CheckRequest]] = {}
    for req in requests:
        groups.setdefault((req.collector, params_hash(req.params)), []).append(req)

    ttl = ctx.cfg.github.snapshot_ttl_hours

    async def run_group(key: tuple[str, str], reqs: list[CheckRequest]) -> dict[str, Fact]:
        first = reqs[0]
        spec = REGISTRY.get(first.collector)
        cache_key = None
        if conn is not None and spec is not None:
            cache_key = {
                "repo": ctx.handle.full_name,
                "commit_sha": ctx.handle.commit_sha,
                "collector": spec.name,
                "params_hash": key[1],
                "collector_version": spec.version,
                "snapshot_bucket": snapshot_bucket(ttl, now) if spec.requires_github else "",
            }

        fact = cache.load_fact(conn, **cache_key) if cache_key else None
        if fact is not None:
            fact = fact.model_copy(update={"cached": True})
        else:
            fact = await run_check(first, ctx)
            if cache_key and fact.ok:
                cache.save_fact(conn, **cache_key, fact=fact)

        return {r.id: fact.model_copy(update={"check_id": r.id, "params": r.params}) for r in reqs}

    results = await asyncio.gather(*(run_group(k, v) for k, v in groups.items()))
    merged: dict[str, Fact] = {}
    for part in results:
        merged.update(part)
    return {req.id: merged[req.id] for req in requests}
