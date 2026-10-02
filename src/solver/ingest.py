"""Multi-file ingest: session .txt files -> parsed hands -> SQLite."""

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from solver import store
from solver.models import FailedHand
from solver.parser.pokerstars import parse_session

SESSION_FILE_PATTERN = "session_*.txt"


@dataclass
class FileIngestResult:
    source_file: str  # basename
    parsed: int = 0
    inserted: int = 0
    updated: int = 0
    failed: list[FailedHand] = field(default_factory=list)
    read_error: str | None = None  # set if the file could not be read/decoded


def find_session_files(folder: Path, pattern: str = SESSION_FILE_PATTERN) -> list[Path]:
    """Non-recursive glob for session files, sorted by name."""
    files = (p for p in folder.glob(pattern) if p.is_file())
    return sorted(files, key=lambda p: p.name)


def ingest_file(
    path: Path, hero_name: str, conn: sqlite3.Connection
) -> FileIngestResult:
    """Parse one session file and store its hands in a single transaction."""
    try:
        # utf-8-sig: Portuguese characters, and tolerates a leading BOM.
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        return FileIngestResult(source_file=path.name, read_error=str(exc))

    parsed = parse_session(text, hero_name)
    inserted, updated = store.save_hands(conn, parsed.hands, path.name)
    return FileIngestResult(
        source_file=path.name,
        parsed=len(parsed.hands),
        inserted=inserted,
        updated=updated,
        failed=parsed.failed,
    )


def ingest_folder(
    folder: Path, hero_name: str, conn: sqlite3.Connection
) -> list[FileIngestResult]:
    """Ingest every session file in `folder`, in sorted filename order.

    Raises:
        FileNotFoundError: `folder` does not exist or is not a directory.
    """
    if not folder.is_dir():
        raise FileNotFoundError(f"not a directory: {folder}")
    return [ingest_file(path, hero_name, conn) for path in find_session_files(folder)]
