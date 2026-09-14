import datetime as dt
import json
import os
import re
import uuid

import functions_framework
from flask import jsonify
import google.auth
from google.auth.transport.requests import Request
from google.cloud import storage


BUCKET = os.environ["SUBMISSIONS_BUCKET"]
MAX_ARCHIVE_BYTES = int(os.environ.get("MAX_ARCHIVE_BYTES", "52428800"))
ID_RE = re.compile(r"^[0-9a-f]{32}$")
storage_client = storage.Client()
credentials, _ = google.auth.default()


def _json_body(request):
    return request.get_json(silent=True) or {}


@functions_framework.http
def control(request):
    if request.method == "POST" and request.path.rstrip("/").endswith("/uploads"):
        body = _json_body(request)
        size = body.get("size")
        if not isinstance(size, int) or size <= 0 or size > MAX_ARCHIVE_BYTES:
            return jsonify(error=f"size must be between 1 and {MAX_ARCHIVE_BYTES}"), 400

        submission_id = uuid.uuid4().hex
        blob = storage_client.bucket(BUCKET).blob(f"uploads/{submission_id}.tar.gz")
        # Cloud Functions exposes short-lived metadata credentials, not a private
        # key. Passing the refreshed access token and service-account email makes
        # google-cloud-storage sign through IAM Credentials signBlob instead.
        credentials.refresh(Request())
        url = blob.generate_signed_url(
            version="v4",
            expiration=dt.timedelta(minutes=15),
            method="PUT",
            content_type="application/gzip",
            service_account_email=credentials.service_account_email,
            access_token=credentials.token,
        )
        return jsonify(
            submission_id=submission_id,
            upload_url=url,
            expires_in=900,
        ), 201

    if request.method == "GET" and "/status/" in request.path:
        submission_id = request.path.rstrip("/").rsplit("/", 1)[-1]
        if not ID_RE.fullmatch(submission_id):
            return jsonify(error="invalid submission id"), 400

        bucket = storage_client.bucket(BUCKET)
        result = bucket.blob(f"results/{submission_id}.json")
        progress = bucket.blob(f"status/{submission_id}.json")
        if result.exists():
            return (result.download_as_text(), 200, {"Content-Type": "application/json"})
        if progress.exists():
            return (progress.download_as_text(), 200, {"Content-Type": "application/json"})
        if bucket.blob(f"uploads/{submission_id}.tar.gz").exists():
            return jsonify(submission_id=submission_id, status="queued"), 200
        return jsonify(error="submission not found"), 404

    return jsonify(error="use POST /uploads or GET /status/SUBMISSION_ID"), 404
