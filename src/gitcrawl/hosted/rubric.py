"""Canonical eval.md naming, normalization, hashing and repository identity."""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from urllib.parse import urlparse

EVAL_FILE = "eval.md"
LEGACY_EVAL_FILE = "clause.md"
_SAFE = re.compile(r"[^a-z0-9._-]+")
_AGENT_ID_RE = re.compile(
    r"^Agent-ID:\s*([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\s*$",
    re.IGNORECASE,
)


def normalize_eval(text: str) -> str:
    """Normalize representation without changing meaningful Markdown content."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).rstrip() + "\n"


def eval_hash(text: str) -> str:
    return hashlib.sha256(normalize_eval(text).encode("utf-8")).hexdigest()


def new_agent_id() -> str:
    return str(uuid.uuid4())


def parse_agent_id(text: str) -> str:
    """Return a strict UUIDv4 from the first line of a hosted eval.md."""
    normalized = normalize_eval(text)
    lines = normalized.splitlines()
    match = _AGENT_ID_RE.fullmatch(lines[0]) if lines else None
    if not match:
        raise ValueError("hosted eval.md must start with 'Agent-ID: <uuid-v4>'")
    if sum(1 for line in lines if line.lower().startswith("agent-id:")) != 1:
        raise ValueError("hosted eval.md must contain exactly one Agent-ID declaration")
    return str(uuid.UUID(match.group(1)))


def with_agent_id(text: str, agent_id: str | None = None) -> str:
    """Prepend a new hosted agent identity after validating the rubric body."""
    identifier = str(uuid.UUID(agent_id or new_agent_id()))
    if uuid.UUID(identifier).version != 4:
        raise ValueError("Agent-ID must be a UUIDv4")
    if any(line.lower().startswith("agent-id:") for line in normalize_eval(text).splitlines()):
        raise ValueError("eval.md already contains an Agent-ID declaration")
    return normalize_eval(f"Agent-ID: {identifier}\n{normalize_eval(text)}")


def find_eval(root: Path) -> tuple[Path | None, str | None]:
    """Find eval.md first, retaining clause.md compatibility for older repos."""
    for name in (EVAL_FILE, LEGACY_EVAL_FILE):
        path = root / name
        if path.is_file():
            return path, normalize_eval(path.read_text(encoding="utf-8"))
    return None, None


def repository_key(remote: str) -> str:
    """Normalize HTTPS/SSH Git remotes into a Storage-safe host/owner/repo key."""
    value = remote.strip()
    if not value:
        raise ValueError("repository remote is required")
    if value.startswith("git@") and ":" in value:
        host, path = value[4:].split(":", 1)
    else:
        parsed = urlparse(value if "://" in value else f"https://{value}")
        host, path = parsed.hostname or "", parsed.path
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = [p for p in path.split("/") if p]
    if not host or len(parts) < 2:
        raise ValueError(f"cannot derive repository identity from remote {remote!r}")
    owner, repo = parts[-2:]
    return "/".join(_SAFE.sub("-", item.lower()).strip("-") for item in (host, owner, repo))


def rubric_prefix(repo_key: str, digest: str) -> str:
    return f"repos/{repo_key}/rubrics/{digest}"


def active_path(repo_key: str) -> str:
    return f"repos/{repo_key}/active.json"


def agent_version_prefix(agent_id: str, digest: str) -> str:
    return f"agents/{agent_id}/versions/{digest}"


def agent_active_path(agent_id: str) -> str:
    return f"agents/{agent_id}/active.json"


def repository_agent_path(repo_key: str) -> str:
    return f"repos/{repo_key}/agent.json"
