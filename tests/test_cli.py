import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from solver import cli, store
from solver.parser.pokerstars import split_into_hands

SAMPLE_HANDS_DIR = Path(__file__).parent.parent / "data" / "sample_hands"
SESSION_FILE = "session_2026-08-28.txt"
HERO_NAME = "osorio211"
BROKEN_BLOCK = "Mão #999 da PokerStars: garbage"


@pytest.fixture(autouse=True)
def _no_ambient_hero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(cli.HERO_ENV_VAR, raising=False)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "solver.db"


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    return sessions


def _ingest_args(folder: Path, db: Path, *extra: str) -> list[str]:
    return ["ingest", str(folder), "--db", str(db), *extra]


def _sample_block(filename: str) -> str:
    raw_text = (SAMPLE_HANDS_DIR / filename).read_text(encoding="utf-8")
    return split_into_hands(raw_text)[0]


def test_ingest_happy_path_then_reingest(
    db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _ingest_args(SAMPLE_HANDS_DIR, db, "--hero", HERO_NAME)

    assert cli.main(args) == 0
    first = capsys.readouterr().out
    assert f"{SESSION_FILE}  parsed 75  new 75  updated 0   failed 0" in first
    assert "Files: 1  Parsed: 75  New: 75  Updated: 0  Failed: 0" in first
    assert f"DB: {db} (total hands: 75)" in first

    assert cli.main(args) == 0
    second = capsys.readouterr().out
    assert "Files: 1  Parsed: 75  New: 0  Updated: 75  Failed: 0" in second
    assert f"DB: {db} (total hands: 75)" in second


def test_no_matching_files_is_fatal(
    folder: Path, db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (folder / "notes.txt").write_text("hello", encoding="utf-8")

    assert cli.main(_ingest_args(folder, db, "--hero", HERO_NAME)) == 1
    assert "no files matching" in capsys.readouterr().err


def test_missing_hero_is_fatal(
    folder: Path, db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(_ingest_args(SAMPLE_HANDS_DIR, db)) == 1
    assert "hero" in capsys.readouterr().err
    assert not db.exists()


def test_hero_falls_back_to_env_var(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cli.HERO_ENV_VAR, HERO_NAME)

    assert cli.main(_ingest_args(SAMPLE_HANDS_DIR, db)) == 0

    with closing(store.connect(db)) as conn:
        assert {h.hero_name for h in store.load_hands(conn)} == {HERO_NAME}


def test_hero_flag_overrides_env_var(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cli.HERO_ENV_VAR, "from_env")

    assert cli.main(_ingest_args(SAMPLE_HANDS_DIR, db, "--hero", HERO_NAME)) == 0

    with closing(store.connect(db)) as conn:
        assert {h.hero_name for h in store.load_hands(conn)} == {HERO_NAME}


def test_missing_folder_is_fatal(
    tmp_path: Path, db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nope"

    assert cli.main(_ingest_args(missing, db, "--hero", HERO_NAME)) == 1
    assert "not a directory" in capsys.readouterr().err
    assert not db.exists()


def test_folder_that_is_a_file_is_fatal(
    tmp_path: Path, db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a_file = tmp_path / "session_a.txt"
    a_file.write_text("", encoding="utf-8")

    assert cli.main(_ingest_args(a_file, db, "--hero", HERO_NAME)) == 1
    assert "not a directory" in capsys.readouterr().err
    assert not db.exists()


def test_broken_hand_exits_2_and_reports_failed_line(
    folder: Path, db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    session = "\n\n".join([_sample_block("hand_001.txt"), BROKEN_BLOCK])
    (folder / "session_a.txt").write_text(session, encoding="utf-8")

    assert cli.main(_ingest_args(folder, db, "--hero", HERO_NAME)) == 2

    out = capsys.readouterr().out
    assert "session_a.txt  parsed 1   new 1   updated 0   failed 1" in out
    failed_lines = [line for line in out.splitlines() if "FAILED" in line]
    assert len(failed_lines) == 1
    source, raw_first_line, error = (
        failed_lines[0].removeprefix("  FAILED  ").split(" | ", maxsplit=2)
    )
    assert source == "session_a.txt"
    assert raw_first_line == BROKEN_BLOCK
    assert error
    with closing(store.connect(db)) as conn:
        assert store.count_hands(conn) == 1


def test_unreadable_file_exits_2_and_still_ingests_the_rest(
    folder: Path, db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (folder / "session_a.txt").write_bytes(b"\xff\xfe\x00")
    (folder / "session_b.txt").write_text(
        _sample_block("hand_001.txt"), encoding="utf-8"
    )

    assert cli.main(_ingest_args(folder, db, "--hero", HERO_NAME)) == 2

    out = capsys.readouterr().out
    assert "  ERROR   session_a.txt | could not read file:" in out
    assert "Files: 2  Parsed: 1  New: 1  Updated: 0  Failed: 0" in out


def test_file_without_hands_warns_but_exits_0(
    folder: Path, db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (folder / "session_a.txt").write_text("nothing here\n", encoding="utf-8")

    assert cli.main(_ingest_args(folder, db, "--hero", HERO_NAME)) == 0
    assert "  WARNING session_a.txt | no hands found" in capsys.readouterr().out


def test_python_dash_m_entry_point(db: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "solver",
            *_ingest_args(SAMPLE_HANDS_DIR, db, "--hero", HERO_NAME),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "total hands: 75" in completed.stdout
