#!/usr/bin/env python3
import argparse
import fnmatch
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request


CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "build-submit" / "config.json"
DEFAULT_EXCLUDES = (
    ".git", ".git/*", ".terraform", ".terraform/*", "node_modules", "node_modules/*",
    "vendor", "vendor/*", "__pycache__", "__pycache__/*", "*.pyc", ".env", ".env.*",
    "*.pem", "*.key", "terraform.tfstate", "terraform.tfstate.*", "qwik.json", "*/qwik.json",
)


def excluded(relative, patterns=DEFAULT_EXCLUDES):
    value = PurePosixPath(relative).as_posix().lower()
    return any(fnmatch.fnmatch(value, pattern.lower()) or fnmatch.fnmatch(f"/{value}", f"*/{pattern.lower()}") for pattern in patterns)


def make_archive(root, output):
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")
    count = 0
    with tarfile.open(output, "w:gz") as archive:
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            if excluded(relative) or any(excluded(parent.as_posix()) for parent in PurePosixPath(relative).parents if parent.as_posix() != "."):
                continue
            if path.is_symlink() or not path.is_file():
                continue
            archive.add(path, arcname=relative, recursive=False)
            count += 1
    if not count:
        raise ValueError("no files remained after exclusions")
    return count


def identity_token():
    result = subprocess.run(
        ["gcloud", "auth", "print-identity-token"], check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def config():
    if not CONFIG_PATH.exists():
        raise RuntimeError("not configured; run: tool configure --endpoint URL")
    return json.loads(CONFIG_PATH.read_text())


def api(endpoint, token, path, method="GET", body=None):
    payload = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        endpoint.rstrip("/") + path,
        data=payload,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"API returned HTTP {exc.code}: {detail}") from exc


def put_archive(url, path):
    request = urllib.request.Request(
        url, data=path.read_bytes(), method="PUT", headers={"Content-Type": "application/gzip"}
    )
    with urllib.request.urlopen(request, timeout=300):
        pass


def show_result(value):
    status = value.get("status")
    if status == "complete":
        print(value.get("analysis", ""))
    elif status == "failed":
        print(f"analysis failed: {value.get('error', 'unknown error')}", file=sys.stderr)
    else:
        print(json.dumps(value, indent=2))
    return 0 if status != "failed" else 1


def main():
    parser = argparse.ArgumentParser(prog="tool", description="Submit source trees for Gemini analysis on Google Cloud")
    sub = parser.add_subparsers(dest="command", required=True)
    configure = sub.add_parser("configure")
    configure.add_argument("--endpoint", required=True)
    submit = sub.add_parser("submit")
    submit.add_argument("path", nargs="?", default=".")
    submit.add_argument("--async", dest="async_mode", action="store_true")
    submit.add_argument("--timeout", type=int, default=600)
    status = sub.add_parser("status")
    status.add_argument("submission_id")
    args = parser.parse_args()

    if args.command == "configure":
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps({"endpoint": args.endpoint.rstrip("/")}, indent=2) + "\n")
        CONFIG_PATH.chmod(0o600)
        print(f"Configured {args.endpoint}")
        return 0

    cfg = config()
    token = identity_token()
    if args.command == "status":
        return show_result(api(cfg["endpoint"], token, f"/status/{args.submission_id}"))

    with tempfile.TemporaryDirectory(prefix="build-submit-") as temp_dir:
        archive = Path(temp_dir) / "source.tar.gz"
        count = make_archive(Path(args.path), archive)
        print(f"Packing {count} files ({archive.stat().st_size} bytes)...")
        upload = api(cfg["endpoint"], token, "/uploads", "POST", {"size": archive.stat().st_size})
        put_archive(upload["upload_url"], archive)
        submission_id = upload["submission_id"]
        print(f"Submitted {submission_id}")

    if args.async_mode:
        return 0
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        value = api(cfg["endpoint"], token, f"/status/{submission_id}")
        if value.get("status") in {"complete", "failed"}:
            return show_result(value)
        print(f"Status: {value.get('status', 'queued')}", file=sys.stderr)
        time.sleep(3)
    print(f"Timed out; check later with: tool status {submission_id}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
