import io
import tarfile
from pathlib import Path

import pytest

from gitcrawl.hosted.archive import ArchiveError, extract_repository


def _archive(path: Path, name: str):
    with tarfile.open(path, "w:gz") as tar:
        data = b"hello"
        member = tarfile.TarInfo(name)
        member.size = len(data)
        tar.addfile(member, io.BytesIO(data))


def test_extract_repository_accepts_safe_files(tmp_path: Path):
    archive, out = tmp_path / "source.tar.gz", tmp_path / "out"
    out.mkdir()
    _archive(archive, "src/app.py")
    extract_repository(archive, out)
    assert (out / "src/app.py").read_text() == "hello"


def test_extract_repository_rejects_traversal(tmp_path: Path):
    archive, out = tmp_path / "source.tar.gz", tmp_path / "out"
    out.mkdir()
    _archive(archive, "../escape")
    with pytest.raises(ArchiveError, match="unsafe"):
        extract_repository(archive, out)
