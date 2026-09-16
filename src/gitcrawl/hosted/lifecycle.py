"""Idempotent eval -> plan -> revision activation transaction."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from gitcrawl.config import GitCrawlConfig, get_config
from gitcrawl.hosted.contracts import ActiveVersion, ObjectStore, RevisionDeployer, VersionManifest
from gitcrawl.hosted.deployer import revision_tag
from gitcrawl.hosted.generator import generate_eval
from gitcrawl.hosted.rubric import (
    agent_active_path,
    agent_version_prefix,
    eval_hash,
    find_eval,
    normalize_eval,
    parse_agent_id,
    repository_agent_path,
    with_agent_id,
)
from gitcrawl.plan.io import approve, dump_plan
from gitcrawl.plan.planner import generate_plan
from gitcrawl.plan.validate import PlanValidationError, validate_plan
from gitcrawl.rubric import parse_rubric


@dataclass(frozen=True)
class LifecycleResult:
    agent_id: str
    eval_markdown: str
    eval_hash: str
    plan_hash: str
    generated: bool
    planned: bool
    deployed: bool
    revision: str
    revision_tag: str
    revision_url: str


async def _await(value):
    return await value if inspect.isawaitable(value) else value


class RubricLifecycle:
    def __init__(
        self,
        store: ObjectStore,
        deployer: RevisionDeployer,
        *,
        image_digest: str,
        gemini_model: str,
        cfg: GitCrawlConfig | None = None,
        eval_generator: Callable[[Path], str | Awaitable[str]] | None = None,
        plan_generator=None,
    ):
        self.store = store
        self.deployer = deployer
        self.image_digest = image_digest
        self.gemini_model = gemini_model
        self.cfg = cfg or get_config()
        self.eval_generator = eval_generator or (lambda root: generate_eval(root, cfg=self.cfg))
        self.plan_generator = plan_generator or (lambda rubric: generate_plan(rubric, cfg=self.cfg))

    async def reconcile(self, root: Path, *, repository_key: str, submission_id: str) -> LifecycleResult:
        return await self.reconcile_with_status(
            root, repository_key=repository_key, submission_id=submission_id, on_phase=None
        )

    async def reconcile_with_status(
        self,
        root: Path,
        *,
        repository_key: str,
        submission_id: str,
        on_phase: Callable[[str], None] | None,
    ) -> LifecycleResult:
        found, text = find_eval(root)
        generated = found is None
        if text is None:
            if on_phase:
                on_phase("generating_eval")
            text = with_agent_id(await _await(self.eval_generator(root)))
        text = normalize_eval(text)
        agent_id = parse_agent_id(text)
        rubric = parse_rubric(text)
        digest = eval_hash(text)
        current_json = self.store.read_json(agent_active_path(agent_id))
        current = ActiveVersion.model_validate(current_json) if current_json else None
        if current and current.eval_hash == digest and current.image_digest == self.image_digest:
            target = self.deployer.deploy(
                agent_id=agent_id,
                repository_key=repository_key,
                eval_hash=digest,
                plan_hash=current.plan_hash,
            )
            if target.revision != current.revision or target.url != current.revision_url:
                current = current.model_copy(
                    update={
                        "repository_key": repository_key,
                        "revision": target.revision,
                        "revision_tag": target.tag,
                        "revision_url": target.url,
                        "activated_at": datetime.now(UTC).isoformat(),
                    }
                )
                self.store.write_json(agent_active_path(agent_id), current)
            self.store.write_json(
                repository_agent_path(repository_key),
                {"repository_key": repository_key, "agent_id": agent_id, "active_eval_hash": digest},
            )
            return LifecycleResult(
                agent_id,
                text,
                digest,
                current.plan_hash,
                generated,
                False,
                target.created,
                current.revision,
                current.revision_tag,
                current.revision_url,
            )

        prefix = agent_version_prefix(agent_id, digest)
        lock_path = f"{prefix}/deployment.lock"
        acquired = self.store.create_json_if_absent(
            lock_path,
            {
                "agent_id": agent_id,
                "eval_hash": digest,
                "submission_id": submission_id,
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
        if not acquired:
            existing_lock = self.store.read_json(lock_path) or {}
            try:
                created_at = datetime.fromisoformat(existing_lock.get("created_at", ""))
            except ValueError:
                created_at = datetime.min.replace(tzinfo=UTC)
            if created_at < datetime.now(UTC) - timedelta(minutes=20):
                self.store.delete(lock_path)
                acquired = self.store.create_json_if_absent(
                    lock_path,
                    {
                        "agent_id": agent_id,
                        "eval_hash": digest,
                        "submission_id": submission_id,
                        "created_at": datetime.now(UTC).isoformat(),
                    },
                )
        if not acquired:
            for _ in range(300):
                await asyncio.sleep(2)
                concurrent_json = self.store.read_json(agent_active_path(agent_id))
                if not concurrent_json:
                    continue
                concurrent = ActiveVersion.model_validate(concurrent_json)
                if concurrent.eval_hash == digest and concurrent.image_digest == self.image_digest:
                    self.store.write_json(
                        repository_agent_path(repository_key),
                        {"repository_key": repository_key, "agent_id": agent_id, "active_eval_hash": digest},
                    )
                    return LifecycleResult(
                        agent_id,
                        text,
                        digest,
                        concurrent.plan_hash,
                        generated,
                        False,
                        False,
                        concurrent.revision,
                        concurrent.revision_tag,
                        concurrent.revision_url,
                    )
            raise TimeoutError("timed out waiting for concurrent agent deployment")

        try:
            return await self._plan_deploy_activate(
                text=text,
                rubric=rubric,
                agent_id=agent_id,
                digest=digest,
                generated=generated,
                repository_key=repository_key,
                submission_id=submission_id,
                on_phase=on_phase,
            )
        finally:
            self.store.delete(lock_path)

    async def _plan_deploy_activate(
        self,
        *,
        text,
        rubric,
        agent_id,
        digest,
        generated,
        repository_key,
        submission_id,
        on_phase,
    ) -> LifecycleResult:
        if on_phase:
            on_phase("planning")
        draft = await _await(self.plan_generator(rubric))
        errors = validate_plan(draft, rubric)
        if errors:
            raise PlanValidationError(errors)
        plan = approve(draft)
        if not plan.is_approved():
            raise PlanValidationError(["automatic plan approval hash did not validate"])
        plan_hash = plan.content_hash()
        prefix = agent_version_prefix(agent_id, digest)

        tag = revision_tag(agent_id, digest, self.image_digest)
        binding_path = f"agents/tags/{tag}.json"
        binding = {
            "agent_id": agent_id,
            "eval_hash": digest,
            "image_digest": self.image_digest,
        }
        if not self.store.create_json_if_absent(binding_path, binding):
            existing_binding = self.store.read_json(binding_path)
            if existing_binding != binding:
                raise RuntimeError(f"Cloud Run revision tag collision for {tag}")

        # Immutable version objects may be written before deployment. The active pointer is not.
        self.store.write_text(f"{prefix}/eval.md", text, content_type="text/markdown")
        self.store.write_text(f"{prefix}/plan.yaml", dump_plan(plan), content_type="application/yaml")
        if on_phase:
            on_phase("deploying")
        target = self.deployer.deploy(
            agent_id=agent_id,
            repository_key=repository_key,
            eval_hash=digest,
            plan_hash=plan_hash,
        )
        manifest = VersionManifest(
            agent_id=agent_id,
            repository_key=repository_key,
            eval_hash=digest,
            plan_hash=plan_hash,
            image_digest=self.image_digest,
            cloud_run_revision=target.revision,
            revision_tag=target.tag,
            revision_url=target.url,
            gemini_model=self.gemini_model,
            source_submission=submission_id,
        )
        self.store.write_json(f"{prefix}/manifest.json", manifest)
        active = ActiveVersion(
            agent_id=agent_id,
            repository_key=repository_key,
            eval_hash=digest,
            plan_hash=plan_hash,
            revision=target.revision,
            image_digest=self.image_digest,
            revision_tag=target.tag,
            revision_url=target.url,
            activated_at=datetime.now(UTC).isoformat(),
        )
        # Last write is the commit point; a failed deployment leaves the previous pointer untouched.
        self.store.write_json(agent_active_path(agent_id), active)
        self.store.write_json(
            repository_agent_path(repository_key),
            {"repository_key": repository_key, "agent_id": agent_id, "active_eval_hash": digest},
        )
        if generated:
            self.store.write_text(
                f"submissions/{submission_id}/artifacts/eval.md", text, content_type="text/markdown"
            )
        return LifecycleResult(
            agent_id,
            text,
            digest,
            plan_hash,
            generated,
            True,
            True,
            target.revision,
            target.tag,
            target.url,
        )
