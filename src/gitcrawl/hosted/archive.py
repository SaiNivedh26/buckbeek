"""Safe extraction for untrusted repository tar archives."""

from __future__ import annotations

import tarfile
from pathlib import Path, PurePosixPath


class ArchiveError(ValueError):
    pass


def extract_repository(archive: Path, destination: Path, *, max_bytes: int = 250_000_000) -> None:
    destination = destination.resolve()
    total = 0
    with tarfile.open(archive, "r:gz") as tar:
        members = []
        for member in tar.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise ArchiveError(f"unsafe archive member: {member.name}")
            if member.issym() or member.islnk() or not (member.isdir() or member.isfile()):
                continue
            total += member.size
            if total > max_bytes:
                raise ArchiveError("expanded archive exceeds the configured limit")
            members.append(member)
        tar.extractall(destination, members=members, filter="data")


def repository_root(destination: Path) -> Path:
    """Accept either a flat archive or one conventional top-level directory."""
    entries = [p for p in destination.iterdir() if p.name != "__MACOSX"]
    return entries[0] if len(entries) == 1 and entries[0].is_dir() else destination
