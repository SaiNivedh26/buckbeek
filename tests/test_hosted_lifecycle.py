import json
from pathlib import Path

import pytest

from gitcrawl.hosted.contracts import DeploymentTarget
from gitcrawl.hosted.lifecycle import RubricLifecycle
from gitcrawl.hosted.rubric import agent_active_path, parse_agent_id, with_agent_id
from gitcrawl.plan.io import load_default_plan
from gitcrawl.rubric.parse import default_rubric_text


class MemoryStore:
    def __init__(self):
        self.values = {}

    def read_text(self, path):
        return self.values.get(path)

    def write_text(self, path, value, *, content_type="text/plain"):
        self.values[path] = value

    def read_json(self, path):
        value = self.values.get(path)
        return json.loads(value) if isinstance(value, str) else value

    def write_json(self, path, value):
        self.values[path] = value.model_dump(mode="json") if hasattr(value, "model_dump") else value

    def create_json_if_absent(self, path, value):
        if path in self.values:
            return False
        self.values[path] = value
        return True

    def delete(self, path):
        self.values.pop(path, None)


class Deployer:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail
        self.targets = {}

    def deploy(self, **kwargs):
        if self.fail:
            self.calls.append(kwargs)
            raise RuntimeError("not ready")
        key = (kwargs["agent_id"], kwargs["eval_hash"], kwargs["plan_hash"])
        if key in self.targets:
            return self.targets[key].model_copy(update={"created": False})
        self.calls.append(kwargs)
        target = DeploymentTarget(
            revision=f"gitcrawl-{len(self.calls):05d}",
            tag=f"tag-{len(self.calls)}",
            url=f"https://tag-{len(self.calls)}---agent.example.run.app",
            created=True,
        )
        self.targets[key] = target
        return target


def planner(rubric):
    return load_default_plan().model_copy(
        update={"rubric_hash": rubric.content_hash, "approved": False, "approved_hash": None}
    )


@pytest.mark.asyncio
async def test_new_generated_eval_plans_deploys_and_activates(tmp_path: Path):
    store, deployer = MemoryStore(), Deployer()
    lifecycle = RubricLifecycle(
        store,
        deployer,
        image_digest="image@sha256:abc",
        gemini_model="gemini-test",
        eval_generator=lambda _root: default_rubric_text(),
        plan_generator=planner,
    )
    result = await lifecycle.reconcile(tmp_path, repository_key="github.com/o/r", submission_id="s1")
    assert result.generated and result.planned and result.deployed
    assert len(deployer.calls) == 1
    assert store.read_json(agent_active_path(result.agent_id))["eval_hash"] == result.eval_hash
    assert parse_agent_id(result.eval_markdown) == result.agent_id
    assert store.read_text("submissions/s1/artifacts/eval.md") == result.eval_markdown

    (tmp_path / "eval.md").write_text(result.eval_markdown)
    again = await lifecycle.reconcile(tmp_path, repository_key="github.com/o/r", submission_id="s2")
    assert not again.planned and not again.deployed
    assert len(deployer.calls) == 1


@pytest.mark.asyncio
async def test_user_eval_is_not_written_as_generated_artifact(tmp_path: Path):
    (tmp_path / "eval.md").write_text(with_agent_id(default_rubric_text()))
    store = MemoryStore()
    result = await RubricLifecycle(
        store,
        Deployer(),
        image_digest="image@sha256:abc",
        gemini_model="gemini-test",
        plan_generator=planner,
    ).reconcile(tmp_path, repository_key="github.com/o/r", submission_id="s1")
    assert not result.generated
    assert store.read_text("submissions/s1/artifacts/eval.md") is None


@pytest.mark.asyncio
async def test_failed_deployment_does_not_replace_active_pointer(tmp_path: Path):
    eval_text = with_agent_id(default_rubric_text())
    (tmp_path / "eval.md").write_text(eval_text)
    agent_id = parse_agent_id(eval_text)
    store = MemoryStore()
    store.write_json(
        agent_active_path(agent_id),
        {
            "agent_id": agent_id,
            "repository_key": "github.com/o/r",
            "eval_hash": "old",
            "plan_hash": "old-plan",
            "revision": "old-revision",
            "image_digest": "old@sha256:x",
            "revision_tag": "old-tag",
            "revision_url": "https://old.example.run.app",
            "activated_at": "2026-01-01T00:00:00Z",
        },
    )
    lifecycle = RubricLifecycle(
        store,
        Deployer(fail=True),
        image_digest="image@sha256:abc",
        gemini_model="gemini-test",
        plan_generator=planner,
    )
    with pytest.raises(RuntimeError, match="not ready"):
        await lifecycle.reconcile(tmp_path, repository_key="github.com/o/r", submission_id="s1")
    assert store.read_json(agent_active_path(agent_id))["revision"] == "old-revision"
