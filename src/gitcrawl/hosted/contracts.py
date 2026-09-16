"""Stable JSON contracts shared by the control API, analyzer and Cloud Run service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

Phase = Literal[
    "uploaded",
    "inspecting",
    "generating_eval",
    "planning",
    "deploying",
    "routing",
    "analyzing",
    "complete",
    "failed",
]


class SubmissionMetadata(BaseModel):
    submission_id: str
    repository_key: str
    commit_sha: str = ""
    archive_size: int = Field(ge=0)
    cli_version: str
    eval_was_present: bool = False


class SubmissionStatus(BaseModel):
    submission_id: str
    phase: Phase
    active_eval_hash: str | None = None
    plan_hash: str | None = None
    planned: bool = False
    deployed: bool = False
    generated_eval: bool = False
    artifact_urls: dict[str, str] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    message: str | None = None
    agent_id: str | None = None
    eval_hash: str | None = None
    revision: str | None = None
    revision_url: str | None = None


class ActiveVersion(BaseModel):
    agent_id: str
    repository_key: str
    eval_hash: str
    plan_hash: str
    revision: str
    image_digest: str
    revision_tag: str
    revision_url: str
    activated_at: str


class VersionManifest(BaseModel):
    agent_id: str
    repository_key: str
    eval_hash: str
    plan_hash: str
    image_digest: str
    cloud_run_revision: str
    revision_tag: str
    revision_url: str
    gemini_model: str
    source_submission: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ObjectStore(Protocol):
    def read_text(self, path: str) -> str | None: ...
    def write_text(self, path: str, value: str, *, content_type: str = "text/plain") -> None: ...
    def read_json(self, path: str) -> dict[str, Any] | None: ...
    def write_json(self, path: str, value: BaseModel | dict[str, Any]) -> None: ...
    def create_json_if_absent(self, path: str, value: dict[str, Any]) -> bool: ...
    def delete(self, path: str) -> None: ...


class RevisionDeployer(Protocol):
    def deploy(
        self, *, agent_id: str, repository_key: str, eval_hash: str, plan_hash: str
    ) -> DeploymentTarget: ...


class DeploymentTarget(BaseModel):
    revision: str
    tag: str
    url: str
    created: bool = True
