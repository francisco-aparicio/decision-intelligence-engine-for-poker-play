import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from helpers import make_hand

from solver import store
from solver.models import (
    CheckStatus,
    DecisionCheck,
    DeviationKind,
    Hand,
    Move,
    Node,
    Position,
)
from solver.parser.pokerstars import parse_hand, parse_session, split_into_hands

SAMPLE_HANDS_DIR = Path(__file__).parent.parent / "data" / "sample_hands"
SESSION_FILE = "session_2026-08-28.txt"
HERO_NAME = "osorio211"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(store.connect(tmp_path / "solver.db")) as connection:
        yield connection


@pytest.fixture(scope="module")
def session_hands() -> list[Hand]:
    raw_text = (SAMPLE_HANDS_DIR / SESSION_FILE).read_text(encoding="utf-8")
    return parse_session(raw_text, HERO_NAME).hands


def _hand_001() -> Hand:
    raw_text = (SAMPLE_HANDS_DIR / "hand_001.txt").read_text(encoding="utf-8")
    return parse_hand(split_into_hands(raw_text)[0], HERO_NAME)


def _sorted_chronologically(hands: list[Hand]) -> list[Hand]:
    return sorted(hands, key=lambda hand: (hand.timestamp_utc, hand.hand_id))


def test_round_trip_hand_001(conn: sqlite3.Connection) -> None:
    hand = _hand_001()

    assert store.save_hands(conn, [hand], "hand_001.txt") == (1, 0)

    assert store.get_hand(conn, hand.hand_id) == hand


def test_get_hand_missing_returns_none(conn: sqlite3.Connection) -> None:
    assert store.get_hand(conn, "0") is None


def test_save_hands_is_idempotent(conn: sqlite3.Connection) -> None:
    hands = [_hand_001()]
    store.save_hands(conn, hands, "a.txt")

    assert store.save_hands(conn, hands, "a.txt") == (0, 1)
    assert store.count_hands(conn) == 1


def test_upsert_replaces_row(conn: sqlite3.Connection) -> None:
    hand = _hand_001()
    store.save_hands(conn, [hand], "a.txt")

    store.save_hands(conn, [hand.model_copy(update={"rake": 9.99})], "b.txt")

    stored = store.get_hand(conn, hand.hand_id)
    assert stored is not None
    assert stored.rake == 9.99
    row = conn.execute(
        "SELECT source_file FROM hands WHERE hand_id = ?", (hand.hand_id,)
    ).fetchone()
    assert row["source_file"] == "b.txt"
    assert store.count_hands(conn) == 1


def test_duplicate_hand_id_within_one_call_counts_as_updated(
    conn: sqlite3.Connection,
) -> None:
    hand = _hand_001()

    assert store.save_hands(conn, [hand, hand], "a.txt") == (1, 1)
    assert store.count_hands(conn) == 1


def test_save_session_batch(
    conn: sqlite3.Connection, session_hands: list[Hand]
) -> None:
    assert store.save_hands(conn, session_hands, SESSION_FILE) == (75, 0)
    assert store.count_hands(conn) == 75


def test_load_hands_equal_to_parsed_and_chronological(
    conn: sqlite3.Connection, session_hands: list[Hand]
) -> None:
    # Saved in reverse so ordering can only come from the query.
    store.save_hands(conn, list(reversed(session_hands)), SESSION_FILE)

    assert store.load_hands(conn) == _sorted_chronologically(session_hands)


def test_load_hands_filters(
    conn: sqlite3.Connection, session_hands: list[Hand]
) -> None:
    store.save_hands(conn, session_hands[:30], "a.txt")
    store.save_hands(conn, session_hands[30:], "b.txt")
    ordered = _sorted_chronologically(session_hands)
    pivot = ordered[40].timestamp_utc

    from_a = store.load_hands(conn, source_file="a.txt")
    assert from_a == _sorted_chronologically(session_hands[:30])

    since = store.load_hands(conn, since=pivot)
    assert since == [h for h in ordered if h.timestamp_utc >= pivot]
    assert ordered[40] in since

    until = store.load_hands(conn, until=pivot)
    assert until == [h for h in ordered if h.timestamp_utc < pivot]
    assert ordered[40] not in until

    window = store.load_hands(
        conn,
        source_file="b.txt",
        since=pivot,
        until=pivot + timedelta(days=1),
    )
    assert window == [
        h
        for h in _sorted_chronologically(session_hands[30:])
        if pivot <= h.timestamp_utc < pivot + timedelta(days=1)
    ]


def test_save_hands_empty_input(conn: sqlite3.Connection) -> None:
    assert store.save_hands(conn, [], "x.txt") == (0, 0)
    assert store.count_hands(conn) == 0


def test_save_hands_rolls_back_when_a_later_hand_fails(
    conn: sqlite3.Connection,
) -> None:
    # A non-Hand has no hand_id, so the loop fails after the first hand is written.
    bad_batch = [_hand_001(), object()]

    with pytest.raises(AttributeError):
        store.save_hands(conn, bad_batch, "a.txt")  # type: ignore[arg-type]

    assert store.count_hands(conn) == 0


def test_connect_creates_parent_directory_and_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "dir" / "solver.db"

    with closing(store.connect(db_path)) as first:
        store.save_hands(first, [_hand_001()], "a.txt")
    with closing(store.connect(db_path)) as second:
        assert store.count_hands(second) == 1


def test_connect_allows_in_memory_db() -> None:
    with closing(store.connect(":memory:")) as memory_conn:
        assert store.count_hands(memory_conn) == 0


# --- preflop checks -----------------------------------------------------------------


def _full_check(hand_id: str = "1") -> DecisionCheck:
    return DecisionCheck(
        hand_id=hand_id,
        status=CheckStatus.DEVIATION,
        reason=None,
        hero_pos=Position.BB,
        node=Node.VS_OPEN_CALLED,
        opener_pos=Position.CO,
        n_limpers=1,
        n_callers=2,
        hand_class="A8o",
        expected_action=Move.FOLD,
        actual_action=Move.THREE_BET,
        deviation_kind=DeviationKind.SIZING,
        facing_size_bb=3.0,
        actual_size_bb=14.5,
        expected_size_bb=12.0,
        sizing_checked=True,
    )


def _stored_hands(conn: sqlite3.Connection) -> list[Hand]:
    start = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    hands = [
        make_hand(
            ["BTN fold"],
            hand_id=hand_id,
            timestamp=start + timedelta(days=day),
        )
        for hand_id, day in (("1", 0), ("2", 1), ("3", 2))
    ]
    store.save_hands(conn, hands[:2], "a.txt")
    store.save_hands(conn, hands[2:], "b.txt")
    return hands


def test_preflop_check_round_trip(conn: sqlite3.Connection) -> None:
    _stored_hands(conn)
    sparse = DecisionCheck(
        hand_id="2", status=CheckStatus.NO_DECISION, reason="no_hero_action"
    )
    checks = [_full_check("1"), sparse]

    assert store.replace_preflop_checks(conn, checks, "abc123abc123") == 2

    assert store.load_preflop_checks(conn) == checks


def test_replace_preflop_checks_replaces_everything(conn: sqlite3.Connection) -> None:
    _stored_hands(conn)
    store.replace_preflop_checks(conn, [_full_check("1"), _full_check("2")], "hash-1")

    count = store.replace_preflop_checks(conn, [_full_check("3")], "hash-2")

    assert count == 1
    assert [c.hand_id for c in store.load_preflop_checks(conn)] == ["3"]
    assert store.preflop_playbook_hash(conn) == "hash-2"


def test_preflop_playbook_hash_is_none_when_empty(conn: sqlite3.Connection) -> None:
    assert store.preflop_playbook_hash(conn) is None


def test_replace_preflop_checks_rolls_back_on_failure(conn: sqlite3.Connection) -> None:
    _stored_hands(conn)
    store.replace_preflop_checks(conn, [_full_check("1")], "hash-1")

    with pytest.raises(sqlite3.IntegrityError):
        store.replace_preflop_checks(
            conn, [_full_check("2"), _full_check("2")], "hash-2"
        )

    assert [c.hand_id for c in store.load_preflop_checks(conn)] == ["1"]
    assert store.preflop_playbook_hash(conn) == "hash-1"


def test_load_preflop_checks_filters(conn: sqlite3.Connection) -> None:
    hands = _stored_hands(conn)
    store.replace_preflop_checks(
        conn, [_full_check(h.hand_id) for h in reversed(hands)], "h"
    )

    def ids(**filters) -> list[str]:
        return [c.hand_id for c in store.load_preflop_checks(conn, **filters)]

    assert ids() == ["1", "2", "3"]
    assert ids(source_file="a.txt") == ["1", "2"]
    assert ids(since=hands[1].timestamp_utc) == ["2", "3"]
    assert ids(until=hands[1].timestamp_utc) == ["1"]
    assert ids(source_file="a.txt", since=hands[1].timestamp_utc) == ["2"]
