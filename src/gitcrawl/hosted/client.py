"""Local signed-upload client and safe eval.md synchronization."""

from __future__ import annotations

import json
import os
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from urllib.parse import urlsplit

from gitcrawl.hosted.rubric import EVAL_FILE, parse_agent_id, repository_key, with_agent_id

_EXCLUDED_PARTS = {".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__", ".terraform"}
_EXCLUDED_NAMES = {".env", "qwik.json"}


def validate_endpoint(endpoint: str) -> str:
    """Return a normalized absolute control URL or raise a useful CLI error."""
    value = endpoint.strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(
            "GitCrawl control endpoint is missing or invalid. Set GITCRAWL_ENDPOINT to the "
            "absolute HTTPS control URL, or pass --endpoint https://... explicitly."
        )
    return value


def discover_repository_key(root: Path) -> str:
    result = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"], cwd=root, capture_output=True, text=True, check=False
    )
    if result.returncode == 0 and result.stdout.strip():
        return repository_key(result.stdout.strip())
    marker = root / ".gitcrawl-project-id"
    if marker.exists():
        value = marker.read_text(encoding="utf-8").strip()
    else:
        value = str(uuid.uuid4())
        temp = marker.with_suffix(".tmp")
        temp.write_text(value + "\n", encoding="utf-8")
        os.replace(temp, marker)
    return f"local/project/{value}"


def current_commit(root: Path) -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def build_archive(root: Path, destination: Path) -> int:
    count = 0
    with tarfile.open(destination, "w:gz") as tar:
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if not path.is_file() or any(part in _EXCLUDED_PARTS for part in relative.parts):
                continue
            if path.name in _EXCLUDED_NAMES or path.suffix.lower() in {".pem", ".key", ".p12"}:
                continue
            tar.add(path, arcname=str(relative), recursive=False)
            count += 1
    return count


def identity_token(endpoint: str) -> str:
    result = subprocess.run(
        ["gcloud", "auth", "print-identity-token", f"--audiences={endpoint}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"could not obtain identity token: {result.stderr.strip()}")
    return result.stdout.strip()


def _json_request(url: str, token: str, *, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"API returned HTTP {exc.code}: {detail}") from exc


def sync_generated_eval(root: Path, content: bytes) -> None:
    destination = root / EVAL_FILE
    if destination.exists():
        raise FileExistsError("eval.md appeared while analysis was running; refusing to overwrite it")
    fd, name = tempfile.mkstemp(prefix=".eval.md.", dir=root)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, destination)
    finally:
        Path(name).unlink(missing_ok=True)


def ensure_local_agent_id(root: Path) -> tuple[str | None, bool]:
    """Atomically add Agent-ID to an existing eval.md; absent files are generated remotely."""
    destination = root / EVAL_FILE
    if not destination.exists():
        return None, False
    text = destination.read_text(encoding="utf-8")
    try:
        return parse_agent_id(text), False
    except ValueError:
        if any(line.lower().startswith("agent-id:") for line in text.splitlines()):
            raise
    updated = with_agent_id(text)
    identifier = parse_agent_id(updated)
    fd, name = tempfile.mkstemp(prefix=".eval.md.agent-id.", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(updated)
            file.flush()
            os.fsync(file.fileno())
        if destination.read_text(encoding="utf-8") != text:
            raise RuntimeError("eval.md changed while Agent-ID was being added")
        os.replace(name, destination)
    finally:
        Path(name).unlink(missing_ok=True)
    return identifier, True


def _file_chunks(path: Path, callback: Callable[[str, dict], None] | None) -> Iterator[bytes]:
    sent = 0
    total = path.stat().st_size
    with path.open("rb") as source:
        while chunk := source.read(1024 * 256):
            sent += len(chunk)
            if callback:
                callback("upload", {"sent": sent, "total": total})
            yield chunk


def submit(
    root: Path,
    endpoint: str,
    *,
    cli_version: str,
    poll_seconds: float = 2.0,
    on_event: Callable[[str, dict], None] | None = None,
) -> dict:
    root = root.resolve()
    endpoint = validate_endpoint(endpoint)
    agent_id, inserted = ensure_local_agent_id(root)
    if on_event and inserted:
        on_event("agent_id_added", {"agent_id": agent_id, "path": str(root / EVAL_FILE)})
    eval_was_present = (root / EVAL_FILE).exists()
    token = identity_token(endpoint)
    with tempfile.TemporaryDirectory(prefix="gitcrawl-upload-") as temp:
        archive = Path(temp) / "source.tar.gz"
        file_count = build_archive(root, archive)
        if on_event:
            on_event("archive", {"files": file_count, "size": archive.stat().st_size})
        upload = _json_request(
            f"{endpoint.rstrip('/')}/uploads",
            token,
            method="POST",
            body={
                "repository_key": discover_repository_key(root),
                "commit_sha": current_commit(root),
                "size": archive.stat().st_size,
                "cli_version": cli_version,
                "eval_was_present": eval_was_present,
            },
        )
        if on_event:
            on_event("submission", {"submission_id": upload["submission_id"]})
        import httpx

        with httpx.Client(timeout=300) as http:
            response = http.put(
                upload["upload_url"],
                content=_file_chunks(archive, on_event),
                headers={
                    "Content-Type": "application/gzip",
                    "Content-Length": str(archive.stat().st_size),
                },
            )
            response.raise_for_status()
        status_url = upload.get("status_url") or f"{endpoint.rstrip('/')}/status/{upload['submission_id']}"
        last_phase = None
        while True:
            status = _json_request(status_url, token)
            phase = status.get("phase") or status.get("status")
            if on_event and phase != last_phase:
                on_event("phase", status)
                last_phase = phase
            if status.get("phase") == "failed" or status.get("status") == "failed":
                raise RuntimeError(status.get("error") or "hosted analysis failed")
            if status.get("phase") == "complete" or status.get("status") == "complete":
                break
            time.sleep(poll_seconds)
        eval_url = (status.get("artifact_urls") or {}).get("eval.md")
        if eval_url and not eval_was_present:
            error = None
            for attempt in range(3):
                try:
                    if attempt:
                        status = _json_request(status_url, token)
                        eval_url = (status.get("artifact_urls") or {}).get("eval.md")
                    if not eval_url:
                        raise RuntimeError("completed submission did not expose generated eval.md")
                    with urllib.request.urlopen(eval_url, timeout=60) as response:
                        sync_generated_eval(root, response.read())
                    error = None
                    break
                except (OSError, RuntimeError, urllib.error.HTTPError) as exc:
                    error = exc
                    time.sleep(min(attempt + 1, 2))
            if error:
                raise RuntimeError(
                    f"submission {upload['submission_id']} completed but eval.md download failed: {error}"
                ) from error
            if on_event:
                on_event("download", {"path": str((root / EVAL_FILE).resolve())})
        elif not eval_was_present:
            raise RuntimeError(
                f"submission {upload['submission_id']} completed without a downloadable generated eval.md"
            )
        return status
