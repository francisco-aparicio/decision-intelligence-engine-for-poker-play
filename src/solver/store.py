"""SQLite persistence for parsed hands.

The session files are the source of truth; the DB is a rebuildable cache. Each
`Hand` is stored as one JSON blob plus a few promoted columns for filtering.
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from solver.models import Hand

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
"""

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
