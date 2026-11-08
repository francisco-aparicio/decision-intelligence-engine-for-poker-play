"""SQLite persistence for parsed hands.

The session files are the source of truth; the DB is a rebuildable cache. Each
`Hand` is stored as one JSON blob plus a few promoted columns for filtering.
"""

import sqlite3
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from solver.models import DecisionCheck, Hand

DEFAULT_DB_PATH = Path("data/solver.db")

_MEMORY_DB = ":memory:"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS hands (
    hand_id       TEXT PRIMARY KEY,
    timestamp_utc TEXT NOT NULL,
    source_file   TEXT NOT NULL,
    ingested_at   TEXT NOT NULL,
    data          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hands_timestamp ON hands(timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_hands_source    ON hands(source_file);

CREATE TABLE IF NOT EXISTS preflop_checks (
    hand_id          TEXT PRIMARY KEY REFERENCES hands(hand_id),
    status           TEXT NOT NULL,
    reason           TEXT,
    hero_pos         TEXT,
    node             TEXT,
    opener_pos       TEXT,
    n_limpers        INTEGER NOT NULL,
    n_callers        INTEGER NOT NULL,
    hand_class       TEXT,
    expected_action  TEXT,
    actual_action    TEXT,
    deviation_kind   TEXT,
    facing_size_bb   REAL,
    actual_size_bb   REAL,
    expected_size_bb REAL,
    sizing_checked   INTEGER NOT NULL,
    playbook_hash    TEXT NOT NULL,
    checked_at       TEXT NOT NULL
);
CREATE VIEW IF NOT EXISTS v_preflop AS
    SELECT h.source_file, h.timestamp_utc, p.*
    FROM preflop_checks p JOIN hands h USING (hand_id);
"""

_PREFLOP_COLUMNS = (
    "hand_id, status, reason, hero_pos, node, opener_pos, n_limpers, n_callers, "
    "hand_class, expected_action, actual_action, deviation_kind, facing_size_bb, "
    "actual_size_bb, expected_size_bb, sizing_checked, playbook_hash, checked_at"
)
_PREFLOP_INSERT_SQL = (
    f"INSERT INTO preflop_checks ({_PREFLOP_COLUMNS}) "
    f"VALUES ({', '.join('?' * len(_PREFLOP_COLUMNS.split(',')))})"
)

_UPSERT_SQL = """
INSERT INTO hands (hand_id, timestamp_utc, source_file, ingested_at, data)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT(hand_id) DO UPDATE SET
    timestamp_utc = excluded.timestamp_utc,
    source_file   = excluded.source_file,
    ingested_at   = excluded.ingested_at,
    data          = excluded.data
"""


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open the DB, creating its directory, file and schema if missing.

    The caller closes the connection (use `contextlib.closing`).
    """
    if str(db_path) != _MEMORY_DB:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def save_hands(
    conn: sqlite3.Connection, hands: list[Hand], source_file: str
) -> tuple[int, int]:
    """Upsert hands by hand_id in one all-or-nothing transaction.

    Args:
        conn: Connection from `connect()`.
        hands: Hands to store. A stored hand_id is replaced, latest wins.
        source_file: Basename of the session file the hands came from.

    Returns:
        (inserted, updated). A hand_id repeated within `hands` counts its
        second occurrence as updated.
    """
    ingested_at = datetime.now(UTC).isoformat()
    inserted = 0
    updated = 0
    with conn:
        for hand in hands:
            exists = conn.execute(
                "SELECT 1 FROM hands WHERE hand_id = ?", (hand.hand_id,)
            ).fetchone()
            conn.execute(
                _UPSERT_SQL,
                (
                    hand.hand_id,
                    hand.timestamp_utc.isoformat(),
                    source_file,
                    ingested_at,
                    hand.model_dump_json(),
                ),
            )
            if exists:
                updated += 1
            else:
                inserted += 1
    return inserted, updated


def load_hands(
    conn: sqlite3.Connection,
    *,
    source_file: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[Hand]:
    """Return hands ordered by (timestamp_utc, hand_id).

    `since` is inclusive and `until` exclusive. They are compared as ISO
    strings, so pass datetimes with the same tz-awareness as
    `Hand.timestamp_utc`. A stored row that no longer validates raises
    `pydantic.ValidationError`; re-run `solver ingest` to refresh it.
    """
    conditions = []
    params: list[str] = []
    if source_file is not None:
        conditions.append("source_file = ?")
        params.append(source_file)
    if since is not None:
        conditions.append("timestamp_utc >= ?")
        params.append(since.isoformat())
    if until is not None:
        conditions.append("timestamp_utc < ?")
        params.append(until.isoformat())

    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"SELECT data FROM hands{where} ORDER BY timestamp_utc ASC, hand_id ASC",
        params,
    ).fetchall()
    return [Hand.model_validate_json(row["data"]) for row in rows]


def get_hand(conn: sqlite3.Connection, hand_id: str) -> Hand | None:
    row = conn.execute(
        "SELECT data FROM hands WHERE hand_id = ?", (hand_id,)
    ).fetchone()
    return Hand.model_validate_json(row["data"]) if row else None


def count_hands(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM hands").fetchone()[0]


def replace_preflop_checks(
    conn: sqlite3.Connection, checks: list[DecisionCheck], playbook_hash: str
) -> int:
    """Replace the whole preflop_checks table in one transaction.

    Returns the number of rows written. All rows share one `checked_at`.
    """
    checked_at = datetime.now(UTC).isoformat()
    rows = [
        (
            c.hand_id,
            c.status.value,
            c.reason,
            _value(c.hero_pos),
            _value(c.node),
            _value(c.opener_pos),
            c.n_limpers,
            c.n_callers,
            c.hand_class,
            _value(c.expected_action),
            _value(c.actual_action),
            _value(c.deviation_kind),
            c.facing_size_bb,
            c.actual_size_bb,
            c.expected_size_bb,
            int(c.sizing_checked),
            playbook_hash,
            checked_at,
        )
        for c in checks
    ]
    with conn:
        conn.execute("DELETE FROM preflop_checks")
        conn.executemany(_PREFLOP_INSERT_SQL, rows)
    return len(rows)


def _value(member: Enum | None) -> str | None:
    return None if member is None else member.value


def load_preflop_checks(
    conn: sqlite3.Connection,
    *,
    source_file: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[DecisionCheck]:
    """Return stored checks ordered by (timestamp_utc, hand_id).

    Filters match `load_hands`: `since` inclusive, `until` exclusive.
    """
    conditions = []
    params: list[str] = []
    if source_file is not None:
        conditions.append("source_file = ?")
        params.append(source_file)
    if since is not None:
        conditions.append("timestamp_utc >= ?")
        params.append(since.isoformat())
    if until is not None:
        conditions.append("timestamp_utc < ?")
        params.append(until.isoformat())

    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM v_preflop{where} ORDER BY timestamp_utc ASC, hand_id ASC",
        params,
    ).fetchall()
    return [
        DecisionCheck.model_validate(
            {name: row[name] for name in DecisionCheck.model_fields}
        )
        for row in rows
    ]


def preflop_playbook_hash(conn: sqlite3.Connection) -> str | None:
    """The playbook hash the table was built with, or None if it is empty."""
    row = conn.execute("SELECT DISTINCT playbook_hash FROM preflop_checks").fetchone()
    return None if row is None else row["playbook_hash"]
