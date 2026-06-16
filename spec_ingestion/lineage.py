"""Per-file git lineage (AC-06, AC-18).

``file_lineage`` reads author / commit timestamp / commit SHA from the file's git
repo via ``git log -1``; a file not under git falls back to ``os.stat().st_mtime``
with sentinel author and SHA. A caller-provided ``override`` PRIMES over git (for
off-git entries such as an HTTP/zip upload).

Version chaining (``record_version`` / ``current_and_previous``) was a DB concern
and is deferred with the Postgres layer.
"""

from __future__ import annotations

import datetime as dt
import subprocess
from dataclasses import dataclass
from pathlib import Path

UNKNOWN_AUTHOR = "unknown"
UNKNOWN_SHA = "unknown"


@dataclass
class FileLineage:
    """Source provenance for one artifact file."""

    author: str
    committed_at: dt.datetime
    source_version: str


def file_lineage(path: Path | str, override: FileLineage | None = None) -> FileLineage:
    """Returns lineage for ``path`` (AC-06, AC-18).

    Resolution order: a caller-provided ``override`` PRIMES (for off-git entries
    such as an HTTP/zip upload); then git (author / commit timestamp / SHA); then
    ``mtime`` with sentinel author + SHA.
    """
    if override is not None:
        return override
    path = Path(path)
    git = _git_lineage(path)
    if git is not None:
        return git
    return _mtime_lineage(path)


def _git_lineage(path: Path) -> FileLineage | None:
    repo_dir = path.parent
    try:
        out = subprocess.run(
            [
                "git",
                "log",
                "-1",
                "--format=%H%x00%an%x00%aI",
                "--",
                path.name,
            ],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    sha, author, committed_iso = out.stdout.strip().split("\x00")
    return FileLineage(
        author=author,
        committed_at=dt.datetime.fromisoformat(committed_iso),
        source_version=sha,
    )


def _mtime_lineage(path: Path) -> FileLineage:
    mtime = path.stat().st_mtime
    return FileLineage(
        author=UNKNOWN_AUTHOR,
        committed_at=dt.datetime.fromtimestamp(mtime, tz=dt.timezone.utc),
        source_version=UNKNOWN_SHA,
    )
