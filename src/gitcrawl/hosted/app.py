"""Private controller and revision-pinned worker HTTP endpoints for hosted GitCrawl."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from flask import Flask, jsonify, request

from gitcrawl.config import get_config
from gitcrawl.engine import evaluate_handle
from gitcrawl.hosted.archive import extract_repository, repository_root
from gitcrawl.hosted.deployer import CloudRunRevisionDeployer
from gitcrawl.hosted.lifecycle import RubricLifecycle
from gitcrawl.hosted.runtime import load_pinned
from gitcrawl.hosted.storage import GCSObjectStore
from gitcrawl.source import local_handle
from gitcrawl.storage import db

logger = logging.getLogger(__name__)


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _owner_repo(repo_key: str) -> tuple[str, str]:
    parts = repo_key.split("/")
    return (parts[-2], parts[-1]) if len(parts) >= 2 else ("local", parts[-1])


def _status(store, submission_id: str, phase: str, message: str, **fields) -> None:
    current = store.read_json(f"submissions/{submission_id}/status.json") or {}
    current.update(
        {
            "submission_id": submission_id,
            "phase": phase,
            "message": message,
            "updated_at": datetime.now(UTC).isoformat(),
            **fields,
        }
    )
    store.write_json(f"submissions/{submission_id}/status.json", current)


def _worker_request(url: str, payload: dict) -> dict:
    import google.auth.transport.requests
    import google.oauth2.id_token

    auth_request = google.auth.transport.requests.Request()
    parsed = urlsplit(url)
    base_host = parsed.netloc.split("---", 1)[-1]
    audience = urlunsplit((parsed.scheme, base_host, "", "", ""))
    token = google.oauth2.id_token.fetch_id_token(auth_request, audience)
    worker = urllib.request.Request(
        f"{url.rstrip('/')}/execute",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(worker, timeout=900) as response:
        return json.load(response)


def create_app(*, store=None, lifecycle=None, worker_invoker=None) -> Flask:
    app = Flask(__name__)
    bucket_name = os.getenv("SUBMISSIONS_BUCKET", "")
    store = store or (GCSObjectStore(bucket_name) if bucket_name else None)
    worker_invoker = worker_invoker or _worker_request

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.get("/readyz")
    def readyz():
        try:
            agent_id = os.getenv("GITCRAWL_AGENT_ID")
            eval_digest = os.getenv("GITCRAWL_EVAL_HASH")
            plan_digest = os.getenv("GITCRAWL_PLAN_HASH")
            if agent_id and eval_digest and plan_digest:
                if store is None:
                    raise RuntimeError("SUBMISSIONS_BUCKET is required for a pinned revision")
                load_pinned(
                    store,
                    agent_id=agent_id,
                    expected_eval_hash=eval_digest,
                    expected_plan_hash=plan_digest,
                )
            return jsonify({"status": "ready", "mode": "worker" if agent_id else "controller"})
        except Exception as exc:
            logger.exception("readiness validation failed")
            return jsonify({"status": "not-ready", "error": str(exc)}), 503

    @app.post("/analyze")
    def analyze():
        payload = request.get_json(silent=True) or {}
        missing = sorted({"submission_id", "repository_key", "source_object"} - payload.keys())
        if missing:
            return jsonify({"error": f"missing fields: {', '.join(missing)}"}), 400
        if store is None:
            return jsonify({"error": "SUBMISSIONS_BUCKET is not configured"}), 500
        try:
            result = asyncio.run(
                _coordinate(payload, store=store, lifecycle=lifecycle, worker_invoker=worker_invoker)
            )
            return jsonify(result)
        except Exception as exc:
            logger.exception("analysis coordination failed for %s", payload.get("submission_id"))
            return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500

    @app.post("/execute")
    def execute():
        payload = request.get_json(silent=True) or {}
        missing = sorted(
            {"submission_id", "repository_key", "source_object", "agent_id", "eval_hash", "plan_hash"}
            - payload.keys()
        )
        if missing:
            return jsonify({"error": f"missing fields: {', '.join(missing)}"}), 400
        if store is None:
            return jsonify({"error": "SUBMISSIONS_BUCKET is not configured"}), 500
        try:
            expected = {
                "agent_id": _required("GITCRAWL_AGENT_ID"),
                "eval_hash": _required("GITCRAWL_EVAL_HASH"),
                "plan_hash": _required("GITCRAWL_PLAN_HASH"),
            }
            for name, value in expected.items():
                if payload[name] != value:
                    return jsonify({"error": f"request {name} does not match pinned revision"}), 409
            return jsonify(asyncio.run(_execute(payload, store=store)))
        except Exception as exc:
            logger.exception("pinned analysis failed for %s", payload.get("submission_id"))
            return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500

    return app


def _lifecycle(store) -> RubricLifecycle:
    cfg = get_config()
    bucket = _required("SUBMISSIONS_BUCKET")
    image = _required("GITCRAWL_IMAGE_DIGEST")
    return RubricLifecycle(
        store,
        CloudRunRevisionDeployer(
            project=_required("GOOGLE_CLOUD_PROJECT"),
            region=os.getenv("CLOUD_RUN_REGION", "us-central1"),
            service=os.getenv("CLOUD_RUN_SERVICE", "gitcrawl-agent"),
            image_digest=image,
            bucket=bucket,
        ),
        image_digest=image,
        gemini_model=cfg.models.planner or cfg.models.scorer,
        cfg=cfg,
    )


async def _coordinate(payload: dict, *, store, lifecycle=None, worker_invoker=None) -> dict:
    submission_id = payload["submission_id"]
    lifecycle = lifecycle or _lifecycle(store)
    with tempfile.TemporaryDirectory(prefix="gitcrawl-coordinate-") as work:
        archive = Path(work) / "source.tar.gz"
        store.bucket.blob(payload["source_object"]).download_to_filename(archive)
        extracted = Path(work) / "repo"
        extracted.mkdir()
        extract_repository(archive, extracted)
        root = repository_root(extracted)

        def status(phase: str) -> None:
            messages = {
                "generating_eval": "Generating a repository-tailored eval.md",
                "planning": "Building and validating the agent plan",
                "deploying": "Creating an immutable tagged Cloud Run revision",
            }
            _status(store, submission_id, phase, messages.get(phase, phase.replace("_", " ").title()))

        reconciled = await lifecycle.reconcile_with_status(
            root,
            repository_key=payload["repository_key"],
            submission_id=submission_id,
            on_phase=status,
        )

    _status(
        store,
        submission_id,
        "routing",
        f"Routing to pinned revision {reconciled.revision}",
        agent_id=reconciled.agent_id,
        eval_hash=reconciled.eval_hash,
        plan_hash=reconciled.plan_hash,
        revision=reconciled.revision,
        revision_url=reconciled.revision_url,
        planned=reconciled.planned,
        deployed=reconciled.deployed,
        generated_eval=reconciled.generated,
    )
    worker_payload = {
        **payload,
        "agent_id": reconciled.agent_id,
        "eval_hash": reconciled.eval_hash,
        "plan_hash": reconciled.plan_hash,
    }
    result = await asyncio.to_thread(worker_invoker or _worker_request, reconciled.revision_url, worker_payload)
    result.update(
        {
            "agent_id": reconciled.agent_id,
            "active_eval_hash": reconciled.eval_hash,
            "plan_hash": reconciled.plan_hash,
            "generated_eval": reconciled.generated,
            "planned": reconciled.planned,
            "deployed": reconciled.deployed,
            "revision": reconciled.revision,
            "revision_url": reconciled.revision_url,
        }
    )
    store.write_json(f"submissions/{submission_id}/result.json", result)
    return result


async def _execute(payload: dict, *, store) -> dict:
    cfg = get_config()
    pinned = load_pinned(
        store,
        agent_id=payload["agent_id"],
        expected_eval_hash=payload["eval_hash"],
        expected_plan_hash=payload["plan_hash"],
    )
    submission_id = payload["submission_id"]
    _status(
        store,
        submission_id,
        "analyzing",
        "Running collectors and plan-assigned agents",
        agent_id=payload["agent_id"],
        eval_hash=payload["eval_hash"],
        plan_hash=payload["plan_hash"],
        revision=os.getenv("K_REVISION"),
    )
    with tempfile.TemporaryDirectory(prefix="gitcrawl-execute-") as work:
        archive = Path(work) / "source.tar.gz"
        store.bucket.blob(payload["source_object"]).download_to_filename(archive)
        extracted = Path(work) / "repo"
        extracted.mkdir()
        extract_repository(archive, extracted)
        root = repository_root(extracted)
        owner, name = _owner_repo(payload["repository_key"])
        handle = local_handle(root, owner=owner, name=name).model_copy(
            update={"commit_sha": payload.get("commit_sha") or local_handle(root).commit_sha}
        )
        report = await evaluate_handle(handle, pinned.plan, cfg=cfg, conn=db.connect(":memory:"))
    return {"submission_id": submission_id, "evaluation": report.model_dump(mode="json")}


app = create_app()
