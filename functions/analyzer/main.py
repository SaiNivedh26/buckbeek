import io
import json
import os
import tarfile
import traceback
from datetime import datetime, timezone
from pathlib import PurePosixPath

import functions_framework
from google import genai
from google.cloud import storage


BUCKET = os.environ["SUBMISSIONS_BUCKET"]
PROJECT = os.environ["GCP_PROJECT"]
LOCATION = os.environ.get("GEMINI_LOCATION", "global")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
MAX_CONTEXT_BYTES = int(os.environ.get("MAX_CONTEXT_BYTES", "768000"))
MAX_ARCHIVE_BYTES = int(os.environ.get("MAX_ARCHIVE_BYTES", "52428800"))
MAX_FILE_BYTES = 256_000

TEXT_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".go", ".h", ".hpp", ".html",
    ".java", ".js", ".json", ".jsx", ".kt", ".md", ".php", ".proto",
    ".py", ".rb", ".rs", ".sh", ".sql", ".swift", ".tf", ".toml",
    ".ts", ".tsx", ".txt", ".xml", ".yaml", ".yml",
}
TEXT_NAMES = {"Dockerfile", "Makefile", "Procfile", ".gitignore"}
SKIP_PARTS = {".git", ".terraform", "node_modules", "vendor", "__pycache__"}

storage_client = storage.Client()
genai_client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)


def _write_json(bucket, name, value):
    bucket.blob(name).upload_from_string(
        json.dumps(value, ensure_ascii=False), content_type="application/json"
    )


def _safe_members(archive):
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if member.isfile() and not path.is_absolute() and ".." not in path.parts:
            yield member, path


def _build_context(data):
    chunks = []
    used = 0
    included = []
    skipped = []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member, path in sorted(_safe_members(archive), key=lambda item: item[1].as_posix()):
            lower_parts = {part.lower() for part in path.parts}
            if "qwik.json" in lower_parts or lower_parts & SKIP_PARTS:
                skipped.append(path.as_posix())
                continue
            if member.size > MAX_FILE_BYTES:
                skipped.append(path.as_posix())
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in TEXT_NAMES:
                skipped.append(path.as_posix())
                continue
            raw = archive.extractfile(member).read()
            if b"\x00" in raw:
                skipped.append(path.as_posix())
                continue
            text = raw.decode("utf-8", errors="replace")
            chunk = f"\n--- FILE: {path.as_posix()} ---\n{text}\n"
            encoded = chunk.encode("utf-8")
            if used + len(encoded) > MAX_CONTEXT_BYTES:
                skipped.append(path.as_posix())
                continue
            chunks.append(chunk)
            included.append(path.as_posix())
            used += len(encoded)
    return "".join(chunks), included, skipped


@functions_framework.cloud_event
def analyze_submission(cloud_event):
    event = cloud_event.data
    name = event.get("name", "")
    if not name.startswith("uploads/") or not name.endswith(".tar.gz"):
        return
    submission_id = name.removeprefix("uploads/").removesuffix(".tar.gz")
    bucket = storage_client.bucket(event["bucket"])
    status_name = f"status/{submission_id}.json"
    result_name = f"results/{submission_id}.json"

    # Eventarc is at-least-once. A completed result makes retries idempotent.
    if bucket.blob(result_name).exists():
        return

    try:
        _write_json(bucket, status_name, {"submission_id": submission_id, "status": "analyzing"})
        blob = bucket.blob(name)
        blob.reload()
        if blob.size > MAX_ARCHIVE_BYTES:
            raise ValueError("archive exceeds configured size limit")
        archive_data = blob.download_as_bytes()
        context, included, skipped = _build_context(archive_data)
        if not included:
            raise ValueError("archive contained no supported text source files")

        prompt = f"""You are a senior software engineer reviewing a submitted codebase.
Build a contextual understanding of its purpose, architecture, data/control flow,
important components, dependencies, operational behavior, risks, and pragmatic next
steps. Cite repository paths when making claims. Be explicit about uncertainty and
do not assume files that are not supplied. Return clear Markdown.

Repository snapshot ({len(included)} included files):
{context}
"""
        response = genai_client.models.generate_content(model=MODEL, contents=prompt)
        result = {
            "submission_id": submission_id,
            "status": "complete",
            "model": MODEL,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "included_files": included,
            "skipped_files": skipped,
            "analysis": response.text,
        }
        _write_json(bucket, result_name, result)
    except Exception as exc:
        _write_json(
            bucket,
            result_name,
            {
                "submission_id": submission_id,
                "status": "failed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "error": str(exc),
                "trace": traceback.format_exc(limit=8),
            },
        )
        raise
