"""Signed-upload control API for repository-tailored GitCrawl submissions."""

import datetime as dt
import json
import os
import re
import uuid

import functions_framework
import google.auth
from flask import jsonify
from google.auth.transport.requests import Request
from google.cloud import storage, tasks_v2
from google.protobuf import timestamp_pb2

BUCKET = os.environ["SUBMISSIONS_BUCKET"]
MAX_ARCHIVE_BYTES = int(os.environ.get("MAX_ARCHIVE_BYTES", "52428800"))
ID_RE = re.compile(r"^[0-9a-f]{32}$")
REPO_KEY_RE = re.compile(r"^[a-z0-9._-]+/[a-z0-9._-]+/[a-z0-9._-]+$")
storage_client = storage.Client()
credentials, _ = google.auth.default()
tasks_client = tasks_v2.CloudTasksClient()


def _schedule_cleanup(submission_id, *, delay_seconds, suffix, cleanup_url=None):
    queue = os.environ.get("CLEANUP_QUEUE")
    cleanup_url = cleanup_url or os.environ.get("CLEANUP_URL")
    cleanup_sa = os.environ.get("CLEANUP_SERVICE_ACCOUNT")
    if not queue or not cleanup_url or not cleanup_sa:
        return
    schedule = timestamp_pb2.Timestamp()
    schedule.FromDatetime(dt.datetime.now(dt.UTC) + dt.timedelta(seconds=delay_seconds))
    task = {
        "name": f"{queue}/tasks/{submission_id}-{suffix}",
        "schedule_time": schedule,
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{cleanup_url.rstrip('/')}/internal/cleanup/{submission_id}",
            "oidc_token": {"service_account_email": cleanup_sa, "audience": cleanup_url},
        },
    }
    try:
        tasks_client.create_task(parent=queue, task=task)
    except Exception as exc:
        if exc.__class__.__name__ != "AlreadyExists":
            raise


def _signed(blob, *, method="GET", content_type=None, minutes=15):
    credentials.refresh(Request())
    kwargs = {
        "version": "v4",
        "expiration": dt.timedelta(minutes=minutes),
        "method": method,
        "service_account_email": credentials.service_account_email,
        "access_token": credentials.token,
    }
    if content_type:
        kwargs["content_type"] = content_type
    return blob.generate_signed_url(**kwargs)


def _external_url(request):
    """Return the public HTTPS origin rather than Flask's proxied HTTP origin."""
    forwarded = request.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip()
    scheme = forwarded or request.scheme
    if scheme == "http" and request.host.endswith((".run.app", ".cloudfunctions.net")):
        scheme = "https"
    return f"{scheme}://{request.host}"


@functions_framework.http
def control(request):
    bucket = storage_client.bucket(BUCKET)
    if request.method == "POST" and "/internal/cleanup/" in request.path:
        if not request.headers.get("X-CloudTasks-TaskName"):
            return jsonify(error="cleanup endpoint accepts Cloud Tasks requests only"), 403
        submission_id = request.path.rstrip("/").rsplit("/", 1)[-1]
        if not ID_RE.fullmatch(submission_id):
            return jsonify(error="invalid submission id"), 400
        for blob in bucket.list_blobs(prefix=f"submissions/{submission_id}/"):
            blob.delete()
        return jsonify(submission_id=submission_id, deleted=True)

    if request.method == "POST" and request.path.rstrip("/").endswith("/uploads"):
        body = request.get_json(silent=True) or {}
        size = body.get("size")
        repo_key = body.get("repository_key", "")
        if not isinstance(size, int) or size <= 0 or size > MAX_ARCHIVE_BYTES:
            return jsonify(error=f"size must be between 1 and {MAX_ARCHIVE_BYTES}"), 400
        if not REPO_KEY_RE.fullmatch(repo_key):
            return jsonify(error="repository_key must be normalized host/owner/repository"), 400
        submission_id = uuid.uuid4().hex
        source_name = f"submissions/{submission_id}/source.tar.gz"
        metadata = {
            "submission_id": submission_id,
            "repository_key": repo_key,
            "commit_sha": str(body.get("commit_sha", ""))[:64],
            "archive_size": size,
            "cli_version": str(body.get("cli_version", ""))[:64],
            "eval_was_present": bool(body.get("eval_was_present", False)),
        }
        bucket.blob(f"submissions/{submission_id}/metadata.json").upload_from_string(
            json.dumps(metadata), content_type="application/json"
        )
        _schedule_cleanup(
            submission_id,
            delay_seconds=1800,
            suffix="orphan",
            cleanup_url=_external_url(request),
        )
        upload_url = _signed(bucket.blob(source_name), method="PUT", content_type="application/gzip")
        return jsonify(
            submission_id=submission_id,
            upload_url=upload_url,
            status_url=f"{request.url_root.rstrip('/')}/status/{submission_id}",
            expires_in=900,
        ), 201

    if request.method == "GET" and "/status/" in request.path:
        submission_id = request.path.rstrip("/").rsplit("/", 1)[-1]
        if not ID_RE.fullmatch(submission_id):
            return jsonify(error="invalid submission id"), 400
        result = bucket.blob(f"submissions/{submission_id}/result.json")
        status = bucket.blob(f"submissions/{submission_id}/status.json")
        source = bucket.blob(f"submissions/{submission_id}/source.tar.gz")
        if result.exists():
            value = json.loads(result.download_as_text())
            value.setdefault("phase", "complete" if "error" not in value else "failed")
            artifact = bucket.blob(f"submissions/{submission_id}/artifacts/eval.md")
            if artifact.exists():
                value["artifact_urls"] = {"eval.md": _signed(artifact, minutes=15)}
            return jsonify(value)
        if status.exists():
            return (status.download_as_text(), 200, {"Content-Type": "application/json"})
        if source.exists():
            return jsonify(submission_id=submission_id, phase="uploaded")
        return jsonify(error="submission not found"), 404
    return jsonify(error="use POST /uploads or GET /status/SUBMISSION_ID"), 404
