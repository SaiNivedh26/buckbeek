from pathlib import Path

import pytest

from gitcrawl.hosted.client import discover_repository_key, ensure_local_agent_id, submit, sync_generated_eval
from gitcrawl.hosted.rubric import (
    eval_hash,
    find_eval,
    normalize_eval,
    parse_agent_id,
    repository_key,
    with_agent_id,
)


def test_normalize_and_hash_ignore_line_endings_and_trailing_space():
    left = "# Rubric  \r\nVersion: 1.0\r\n"
    right = "# Rubric\nVersion: 1.0\n\n"
    assert normalize_eval(left) == right.rstrip() + "\n"
    assert eval_hash(left) == eval_hash(right)


def test_eval_md_is_canonical_but_clause_md_remains_compatible(tmp_path: Path):
    (tmp_path / "clause.md").write_text("legacy")
    path, text = find_eval(tmp_path)
    assert path.name == "clause.md" and text == "legacy\n"
    (tmp_path / "eval.md").write_text("canonical")
    path, text = find_eval(tmp_path)
    assert path.name == "eval.md" and text == "canonical\n"


@pytest.mark.parametrize(
    "remote",
    [
        "https://github.com/OpenAI/example.git",
        "git@github.com:OpenAI/example.git",
        "github.com/OpenAI/example",
    ],
)
def test_repository_key_normalizes_git_remotes(remote):
    assert repository_key(remote) == "github.com/openai/example"


def test_local_repository_id_is_persisted(monkeypatch, tmp_path: Path):
    class Result:
        returncode = 1
        stdout = ""

    monkeypatch.setattr("gitcrawl.hosted.client.subprocess.run", lambda *a, **k: Result())
    first = discover_repository_key(tmp_path)
    assert discover_repository_key(tmp_path) == first
    assert (tmp_path / ".gitcrawl-project-id").exists()


def test_generated_eval_is_atomic_and_never_overwrites(tmp_path: Path):
    sync_generated_eval(tmp_path, b"generated\n")
    assert (tmp_path / "eval.md").read_text() == "generated\n"
    with pytest.raises(FileExistsError):
        sync_generated_eval(tmp_path, b"replacement\n")
    assert (tmp_path / "eval.md").read_text() == "generated\n"


def test_agent_id_is_strict_uuid4_and_first_line():
    hosted = with_agent_id("# Rubric\nVersion: 1\n")
    assert hosted.startswith(f"Agent-ID: {parse_agent_id(hosted)}\n# Rubric")
    with pytest.raises(ValueError, match="must start"):
        parse_agent_id("# Rubric\nAgent-ID: 00000000-0000-4000-8000-000000000000\nVersion: 1\n")


def test_existing_eval_gets_agent_id_atomically(tmp_path: Path):
    (tmp_path / "eval.md").write_text("# Rubric\nVersion: 1\n")
    agent_id, inserted = ensure_local_agent_id(tmp_path)
    assert inserted and parse_agent_id((tmp_path / "eval.md").read_text()) == agent_id
    same, inserted_again = ensure_local_agent_id(tmp_path)
    assert same == agent_id and not inserted_again


def test_submit_downloads_generated_eval_before_success(monkeypatch, tmp_path: Path):
    (tmp_path / "app.py").write_text("print('ok')\n")
    generated = with_agent_id("# Rubric\nVersion: 1\n")
    events = []

    monkeypatch.setattr("gitcrawl.hosted.client.identity_token", lambda _endpoint: "token")
    monkeypatch.setattr("gitcrawl.hosted.client.discover_repository_key", lambda _root: "host/owner/repo")
    monkeypatch.setattr("gitcrawl.hosted.client.current_commit", lambda _root: "commit")
    monkeypatch.setattr(
        "gitcrawl.hosted.client._json_request",
        lambda url, token, method="GET", body=None: (
            {
                "submission_id": "a" * 32,
                "upload_url": "https://upload.example",
                "status_url": "https://status.example",
            }
            if method == "POST"
            else {
                "submission_id": "a" * 32,
                "phase": "complete",
                "artifact_urls": {"eval.md": "https://download.example"},
            }
        ),
    )

    class PutResponse:
        def raise_for_status(self):
            return None

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def put(self, _url, *, content, headers):
            b"".join(content)
            assert int(headers["Content-Length"]) > 0
            return PutResponse()

    class Download:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return generated.encode()

    monkeypatch.setattr("httpx.Client", Client)
    monkeypatch.setattr("gitcrawl.hosted.client.urllib.request.urlopen", lambda *_a, **_k: Download())

    result = submit(
        tmp_path,
        "https://control.example",
        cli_version="test",
        poll_seconds=0,
        on_event=lambda kind, value: events.append((kind, value)),
    )
    assert result["phase"] == "complete"
    assert (tmp_path / "eval.md").read_text() == generated
    assert any(kind == "download" for kind, _ in events)
