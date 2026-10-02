import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from solver import ingest, store
from solver.parser.pokerstars import split_into_hands

SAMPLE_HANDS_DIR = Path(__file__).parent.parent / "data" / "sample_hands"
SESSION_FILE = "session_2026-08-28.txt"
HERO_NAME = "osorio211"
BROKEN_BLOCK = "Mão #999 da PokerStars: garbage"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(store.connect(tmp_path / "solver.db")) as connection:
        yield connection


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    return sessions


@pytest.fixture(scope="module")
def session_blocks() -> list[str]:
    raw_text = (SAMPLE_HANDS_DIR / SESSION_FILE).read_text(encoding="utf-8")
    return split_into_hands(raw_text)


def _write_session(folder: Path, name: str, blocks: list[str]) -> Path:
    path = folder / name
    path.write_text("\n\n".join(blocks), encoding="utf-8")
    return path


def _sample_block(filename: str) -> str:
    raw_text = (SAMPLE_HANDS_DIR / filename).read_text(encoding="utf-8")
    return split_into_hands(raw_text)[0]


def _source_file(conn: sqlite3.Connection, hand_id: str) -> str:
    row = conn.execute(
        "SELECT source_file FROM hands WHERE hand_id = ?", (hand_id,)
    ).fetchone()
    return row["source_file"]


def test_find_session_files_is_sorted_non_recursive_and_files_only(
    folder: Path,
) -> None:
    (folder / "session_b.txt").write_text("", encoding="utf-8")
    (folder / "session_a.txt").write_text("", encoding="utf-8")
    (folder / "notes.txt").write_text("", encoding="utf-8")
    (folder / "session_dir.txt").mkdir()
    (folder / "nested").mkdir()
    (folder / "nested" / "session_c.txt").write_text("", encoding="utf-8")

    found = ingest.find_session_files(folder)

    assert [p.name for p in found] == ["session_a.txt", "session_b.txt"]


def test_ingest_folder_processes_only_matching_files_in_sorted_order(
    conn: sqlite3.Connection, folder: Path
) -> None:
    # Written out of order so sorting can't come from creation order.
    _write_session(folder, "session_b.txt", [_sample_block("hand_002.txt")])
    _write_session(folder, "session_a.txt", [_sample_block("hand_001.txt")])
    _write_session(folder, "notes.txt", [_sample_block("hand_005.txt")])

    results = ingest.ingest_folder(folder, HERO_NAME, conn)

    assert [r.source_file for r in results] == ["session_a.txt", "session_b.txt"]
    assert [(r.parsed, r.inserted, r.updated) for r in results] == [
        (1, 1, 0),
        (1, 1, 0),
    ]
    assert store.count_hands(conn) == 2


def test_ingest_folder_missing_folder_raises(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    with pytest.raises(FileNotFoundError):
        ingest.ingest_folder(tmp_path / "nope", HERO_NAME, conn)


def test_ingest_folder_rejects_a_file_path(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    a_file = tmp_path / "session_a.txt"
    a_file.write_text("", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="not a directory"):
        ingest.ingest_folder(a_file, HERO_NAME, conn)


def test_find_session_files_sorts_even_when_glob_does_not(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (folder / "session_a.txt").write_text("", encoding="utf-8")
    (folder / "session_b.txt").write_text("", encoding="utf-8")
    monkeypatch.setattr(
        Path,
        "glob",
        lambda self, pattern: iter([self / "session_b.txt", self / "session_a.txt"]),
    )

    found = ingest.find_session_files(folder)

    assert [p.name for p in found] == ["session_a.txt", "session_b.txt"]


def test_ingest_folder_no_matching_files_returns_empty(
    conn: sqlite3.Connection, folder: Path
) -> None:
    (folder / "notes.txt").write_text("hello", encoding="utf-8")

    assert ingest.ingest_folder(folder, HERO_NAME, conn) == []


def test_overlapping_sessions_are_deduped(
    conn: sqlite3.Connection, folder: Path, session_blocks: list[str]
) -> None:
    assert len(session_blocks) == 75
    # Hands 1-50 and 40-75 share hands 40-50: 11 overlaps.
    _write_session(folder, "session_a.txt", session_blocks[:50])
    _write_session(folder, "session_b.txt", session_blocks[39:])

    first, second = ingest.ingest_folder(folder, HERO_NAME, conn)

    assert (first.parsed, first.inserted, first.updated) == (50, 50, 0)
    assert (second.parsed, second.inserted, second.updated) == (36, 25, 11)
    assert store.count_hands(conn) == 75
    # An overlapping hand is attributed to the file processed last.
    overlap_id = store.load_hands(conn, source_file="session_b.txt")[0].hand_id
    assert _source_file(conn, overlap_id) == "session_b.txt"
    assert len(store.load_hands(conn, source_file="session_a.txt")) == 39
    assert len(store.load_hands(conn, source_file="session_b.txt")) == 36


def test_reingest_updates_everything(
    conn: sqlite3.Connection, folder: Path, session_blocks: list[str]
) -> None:
    _write_session(folder, "session_a.txt", session_blocks[:50])
    _write_session(folder, "session_b.txt", session_blocks[50:])
    ingest.ingest_folder(folder, HERO_NAME, conn)

    results = ingest.ingest_folder(folder, HERO_NAME, conn)

    assert all(r.inserted == 0 and r.updated == r.parsed for r in results)
    assert sum(r.parsed for r in results) == 75
    assert store.count_hands(conn) == 75


def test_ingest_file_isolates_a_broken_hand(
    conn: sqlite3.Connection, folder: Path, session_blocks: list[str]
) -> None:
    path = _write_session(folder, "session_a.txt", [*session_blocks, BROKEN_BLOCK])

    result = ingest.ingest_file(path, HERO_NAME, conn)

    assert result.parsed == 75
    assert result.inserted == 75
    assert len(result.failed) == 1
    assert result.failed[0].raw_text.startswith(BROKEN_BLOCK)
    assert result.read_error is None
    assert store.count_hands(conn) == 75


def test_ingest_folder_isolates_an_undecodable_file(
    conn: sqlite3.Connection, folder: Path
) -> None:
    (folder / "session_a.txt").write_bytes(b"\xff\xfe\x00")
    _write_session(folder, "session_b.txt", [_sample_block("hand_001.txt")])

    bad, good = ingest.ingest_folder(folder, HERO_NAME, conn)

    assert bad.read_error is not None
    assert (bad.parsed, bad.inserted, bad.updated, bad.failed) == (0, 0, 0, [])
    assert good.read_error is None
    assert good.inserted == 1
    assert store.count_hands(conn) == 1


def test_ingest_file_tolerates_a_bom(conn: sqlite3.Connection, folder: Path) -> None:
    path = folder / "session_a.txt"
    path.write_text(_sample_block("hand_001.txt"), encoding="utf-8-sig")

    result = ingest.ingest_file(path, HERO_NAME, conn)

    assert (result.parsed, result.failed, result.read_error) == (1, [], None)


def test_ingest_file_with_no_hands_is_not_an_error(
    conn: sqlite3.Connection, folder: Path
) -> None:
    path = folder / "session_a.txt"
    path.write_text("nothing recognizable here\n", encoding="utf-8")

    result = ingest.ingest_file(path, HERO_NAME, conn)

    assert result == ingest.FileIngestResult(source_file="session_a.txt")


def test_ingest_passes_hero_name_through(
    conn: sqlite3.Connection, folder: Path
) -> None:
    _write_session(folder, "session_a.txt", [_sample_block("hand_001.txt")])

    ingest.ingest_folder(folder, "someone_else", conn)

    (hand,) = store.load_hands(conn)
    assert hand.hero_name == "someone_else"
