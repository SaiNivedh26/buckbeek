"""Rich live dashboard for hosted repository submissions."""

from __future__ import annotations

from time import monotonic

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TransferSpeedColumn,
)
from rich.table import Table
from rich.text import Text

PHASES = (
    ("preparing", "Prepare"),
    ("uploading", "Upload"),
    ("uploaded", "Uploaded"),
    ("inspecting", "Inspect"),
    ("generating_eval", "Generate rubric"),
    ("planning", "Plan"),
    ("deploying", "Deploy"),
    ("routing", "Route"),
    ("analyzing", "Analyze"),
    ("downloading", "Download rubric"),
    ("complete", "Complete"),
)
PHASE_INDEX = {phase: index for index, (phase, _label) in enumerate(PHASES)}


class HostedSubmitTUI:
    """Persistent dashboard showing transfer, lifecycle, identity, and elapsed time."""

    def __init__(self, console: Console):
        self.console = console
        self.started_at = monotonic()
        self.current_phase = "preparing"
        self.message = "Preparing repository archive"
        self.submission_id = "—"
        self.agent_id = "—"
        self.eval_hash = "—"
        self.revision = "—"
        self.file_count: int | None = None
        self.archive_size: int | None = None
        self.skipped: set[str] = set()
        self.upload = Progress(
            SpinnerColumn("dots12", style="bold cyan"),
            TextColumn("[bold]{task.description}"),
            BarColumn(bar_width=None, complete_style="cyan", finished_style="green"),
            TaskProgressColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            console=console,
            auto_refresh=False,
            expand=True,
        )
        self.upload_task = self.upload.add_task("Waiting to upload", total=None)
        self.lifecycle = Progress(
            SpinnerColumn("aesthetic", style="bold magenta"),
            TextColumn("[bold]{task.description}"),
            BarColumn(bar_width=None, complete_style="magenta", finished_style="green"),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
            auto_refresh=False,
            expand=True,
        )
        self.lifecycle_task = self.lifecycle.add_task(
            "Preparing repository archive",
            total=len(PHASES) - 1,
        )
        self.live = Live(
            console=console,
            get_renderable=self.render,
            refresh_per_second=10,
            transient=False,
            vertical_overflow="visible",
        )
        self._started = False

    def start(self) -> None:
        if not self._started:
            self.live.start(refresh=True)
            self._started = True

    def stop(self) -> None:
        if self._started:
            self.live.refresh()
            self.live.stop()
            self._started = False

    def update(self, kind: str, value: dict) -> None:
        if kind == "archive":
            self.file_count = value.get("files")
            self.archive_size = value.get("size")
            self.message = f"Archived {self.file_count or 0:,} files"
        elif kind == "submission":
            self.submission_id = str(value.get("submission_id") or "—")
            self.current_phase = "uploading"
            self.message = "Uploading repository securely"
        elif kind == "upload":
            total = max(int(value.get("total") or 0), 1)
            sent = min(int(value.get("sent") or 0), total)
            self.current_phase = "uploading"
            self.message = "Uploading repository securely"
            self.upload.update(
                self.upload_task,
                description="Repository archive",
                total=total,
                completed=sent,
            )
        elif kind == "phase":
            phase = str(value.get("phase") or value.get("status") or "inspecting")
            self.current_phase = phase if phase in PHASE_INDEX else self.current_phase
            self.message = str(value.get("message") or phase.replace("_", " ").title())
            self._capture_identity(value)
        elif kind == "download":
            self.current_phase = "downloading"
            self.message = f"Downloaded eval.md → {value.get('path', '')}"
        elif kind == "agent_id_added":
            self.agent_id = str(value.get("agent_id") or "—")
            self.message = "Added Agent-ID to the local eval.md"
        self.lifecycle.update(
            self.lifecycle_task,
            description=self.message,
            completed=PHASE_INDEX.get(self.current_phase, 0),
        )
        self.live.refresh()

    def complete(self, result: dict) -> None:
        self._capture_identity(result)
        if not result.get("planned"):
            self.skipped.update({"generating_eval", "planning"})
        if not result.get("deployed"):
            self.skipped.add("deploying")
        if not result.get("generated_eval"):
            self.skipped.add("downloading")
        self.current_phase = "complete"
        self.message = "Analysis completed successfully"
        self.lifecycle.update(
            self.lifecycle_task,
            description=self.message,
            completed=len(PHASES) - 1,
        )
        task = self.upload.tasks[0]
        if task.total is not None:
            self.upload.update(self.upload_task, completed=task.total)
        self.stop()

    def fail(self, message: str) -> None:
        self.message = message
        self.stop()

    def _capture_identity(self, value: dict) -> None:
        self.agent_id = str(value.get("agent_id") or self.agent_id)
        self.eval_hash = str(value.get("active_eval_hash") or value.get("eval_hash") or self.eval_hash)
        self.revision = str(value.get("revision") or self.revision)

    def _phase_table(self) -> Table:
        table = Table.grid(expand=True)
        for _ in range(4):
            table.add_column(ratio=1)
        current = PHASE_INDEX.get(self.current_phase, 0)
        cells = []
        for index, (_phase, label) in enumerate(PHASES):
            if _phase in self.skipped:
                cells.append(Text.assemble(("– ", "dim yellow"), (label, "dim")))
            elif index < current or self.current_phase == "complete":
                cells.append(Text.assemble(("✓ ", "bold green"), (label, "green")))
            elif index == current:
                cells.append(Text.assemble(("◆ ", "bold cyan"), (label, "bold white")))
            else:
                cells.append(Text.assemble(("○ ", "dim"), (label, "dim")))
        while len(cells) % 4:
            cells.append(Text(""))
        for offset in range(0, len(cells), 4):
            table.add_row(*cells[offset : offset + 4])
        return table

    def _details(self) -> Table:
        details = Table.grid(padding=(0, 2), expand=True)
        details.add_column(style="bold bright_black", width=12)
        details.add_column(overflow="fold")
        details.add_row("Submission", self.submission_id)
        details.add_row("Agent", self.agent_id)
        details.add_row("Revision", self.revision)
        details.add_row("Eval hash", self.eval_hash[:16] if self.eval_hash != "—" else "—")
        if self.file_count is not None:
            details.add_row("Archive", f"{self.file_count:,} files · {_human_bytes(self.archive_size or 0)}")
        return details

    def render(self) -> Panel:
        elapsed = max(monotonic() - self.started_at, 0)
        header = Text.assemble(
            (" GitCrawl ", "bold black on cyan"),
            ("  Repository-tailored analysis", "bold white"),
            (f"  {elapsed:,.1f}s", "cyan"),
        )
        status = Text.assemble(("● ", "bold cyan"), (self.message, "bold"))
        return Panel(
            Group(
                header,
                Text(""),
                self.upload,
                self.lifecycle,
                Text(""),
                self._phase_table(),
                Text(""),
                status,
                self._details(),
            ),
            border_style="cyan",
            padding=(1, 2),
            title="[bold]Hosted analysis[/bold]",
            title_align="left",
        )


def _human_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if amount < 1024 or unit == "GiB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return f"{amount:.1f} GiB"
