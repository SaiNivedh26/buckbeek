"""Eventarc adapter that invokes the private GitCrawl Cloud Run service."""

import json
import os
import traceback
import urllib.request
from datetime import UTC, datetime, timedelta

import functions_framework
import google.auth.transport.requests
import google.oauth2.id_token
from google.api_core.exceptions import PreconditionFailed
from google.cloud import storage, tasks_v2
from google.protobuf import timestamp_pb2

AGENT_URL = os.environ["GITCRAWL_AGENT_URL"].rstrip("/")
storage_client = storage.Client()
tasks_client = tasks_v2.CloudTasksClient()


def _schedule_cleanup(submission_id):
    queue = os.environ.get("CLEANUP_QUEUE")
    cleanup_url = os.environ.get("CLEANUP_URL")
    cleanup_sa = os.environ.get("CLEANUP_SERVICE_ACCOUNT")
    if not queue or not cleanup_url or not cleanup_sa:
        return
    schedule = timestamp_pb2.Timestamp()
    schedule.FromDatetime(datetime.now(UTC) + timedelta(minutes=10))
    task = {
        "name": f"{queue}/tasks/{submission_id}-final",
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


def _write(bucket, submission_id, value, *, result=False):
    leaf = "result.json" if result else "status.json"
    bucket.blob(f"submissions/{submission_id}/{leaf}").upload_from_string(
        json.dumps(value), content_type="application/json"
    )


@functions_framework.cloud_event
def analyze_submission(cloud_event):
    event = cloud_event.data
    name = event.get("name", "")
    if not name.startswith("submissions/") or not name.endswith("/source.tar.gz"):
        return
    submission_id = name.split("/")[1]
    bucket = storage_client.bucket(event["bucket"])
    result_blob = bucket.blob(f"submissions/{submission_id}/result.json")
    if result_blob.exists():
        return
    try:
        bucket.blob(f"submissions/{submission_id}/processing.lock").upload_from_string(
            datetime.now(UTC).isoformat(), if_generation_match=0
        )
    except PreconditionFailed:
        return
    try:
        metadata = json.loads(bucket.blob(f"submissions/{submission_id}/metadata.json").download_as_text())
        _write(bucket, submission_id, {"submission_id": submission_id, "phase": "inspecting"})
        token = google.oauth2.id_token.fetch_id_token(google.auth.transport.requests.Request(), AGENT_URL)
        payload = {
            "submission_id": submission_id,
            "repository_key": metadata["repository_key"],
            "commit_sha": metadata.get("commit_sha", ""),
            "source_object": name,
        }
        request = urllib.request.Request(
            f"{AGENT_URL}/analyze",
            data=json.dumps(payload).encode(),
            method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=900) as response:
            result = json.load(response)
        result["phase"] = "complete"
        result["completed_at"] = datetime.now(UTC).isoformat()
        _write(bucket, submission_id, result, result=True)
        _schedule_cleanup(submission_id)
    except Exception as exc:
        _write(
            bucket,
            submission_id,
            {
                "submission_id": submission_id,
                "phase": "failed",
                "error": str(exc),
                "trace": traceback.format_exc(limit=8),
            },
            result=True,
        )
        _schedule_cleanup(submission_id)
        raise
