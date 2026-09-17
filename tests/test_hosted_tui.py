import re
from io import StringIO

from rich.console import Console

from gitcrawl.hosted.tui import HostedSubmitTUI, _human_bytes


def test_dashboard_renders_upload_timeline_and_identity():
    output = StringIO()
    console = Console(file=output, force_terminal=True, width=120)
    dashboard = HostedSubmitTUI(console)
    dashboard.update("archive", {"files": 42, "size": 2048})
    dashboard.update("submission", {"submission_id": "submission-123"})
    dashboard.update("upload", {"sent": 1024, "total": 2048})
    dashboard.update(
        "phase",
        {
            "phase": "deploying",
            "agent_id": "123e4567-e89b-42d3-a456-426614174000",
            "active_eval_hash": "a" * 64,
            "revision": "gitcrawl-agent-00042-abc",
        },
    )

    console.print(dashboard.render())
    rendered = re.sub(r"\x1b\[[0-9;]*m", "", output.getvalue())
    assert "Repository archive" in rendered
    assert "50%" in rendered
    assert "✓ Upload" in rendered
    assert "◆ Deploy" in rendered
    assert "submission-123" in rendered
    assert "gitcrawl-agent-00042-abc" in rendered


def test_human_bytes_uses_readable_units():
    assert _human_bytes(512) == "512 B"
    assert _human_bytes(2048) == "2.0 KiB"
