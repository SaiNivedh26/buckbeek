"""Shared low-level contracts: the repository handle and the tool budget ledger.

Rubric, plan, collector and result contracts live next to the code that owns
them: rubric/models.py, plan/models.py, collectors/base.py and results.py.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RepoHandle(BaseModel):
    """Where the repo lives on disk, and what commit it's pinned to."""

    root: str  # absolute local path to the checked-out repo
    origin: str  # canonical https://github.com/<owner>/<name> URL
    commit_sha: str
    is_temp_clone: bool = False
    owner: str = ""
    name: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}" if self.owner else self.origin


class BudgetLedger(BaseModel):
    """Plain-code bookkeeping for agent tool calls, keyed by agent id. Never
    shown to a model; enforced at the tool layer (tools/repo_tools.py)."""

    allocated: dict[str, int] = Field(default_factory=dict)
    spent: dict[str, int] = Field(default_factory=dict)
    # Calls rejected before a tool body ran — a wrong tool name or malformed
    # argument. They spend no budget (no work happened) but are real model
    # requests, so the report shows them separately.
    failed_calls: dict[str, int] = Field(default_factory=dict)
    # Paths each agent actually read (read_file, files matched by search_repo,
    # issues/N, pulls/N, releases/TAG). Citations are verified against this —
    # never trusted from the model's own account of what it looked at.
    read_paths: dict[str, list[str]] = Field(default_factory=dict)

    def remaining(self, owner: str) -> int:
        return max(0, self.allocated.get(owner, 0) - self.spent.get(owner, 0))

    def spend(self, owner: str, n: int = 1) -> None:
        self.spent[owner] = self.spent.get(owner, 0) + n

    def record_failed_call(self, owner: str) -> None:
        self.failed_calls[owner] = self.failed_calls.get(owner, 0) + 1

    def record_read(self, owner: str, path: str) -> None:
        paths = self.read_paths.setdefault(owner, [])
        if path not in paths:
            paths.append(path)
