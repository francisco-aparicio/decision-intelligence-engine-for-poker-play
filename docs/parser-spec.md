# PokerStars Hand History Parser — Implementation Spec

## Status and parts

- **Part A — single-hand/session parsing** (raw text → validated `Hand`
  objects). **Implemented** (Milestone 0). Do not change its behaviour.
- **Part B — multi-file ingest + SQLite persistence** (see the section
  "Part B" at the end). **Current work.** Implement only Part B.
  `models.py` and `parser/pokerstars.py` are **not modified** by Part B.

---

# Part A — Parser (implemented)

## Goal
Parse Portuguese-localized PokerStars (.pt) hand history text — delivered as
the plain-text body of a "hand history request" email — into validated
`Hand` pydantic objects.

## Scope
Full single-hand parsing. **Implement and test incrementally**, not all at
once:
1. Preflop only (seats, hero cards, preflop actions) — get the golden test
   green first.
2. Extend one street at a time (flop → turn → river), re-running the golden
   test after each.
3. Summary last — per-pot results and total pot/rake. **`*** SHOW DOWN ***`
   is not parsed at all** — see "Known data quirks" #6 for why.

## Inputs
- Raw text of one email body. May contain 1–N hands.
- `hero_name: str` — the real PokerStars username the export belongs to.
  **Never hardcode a literal `"Hero"`** — in the current fixture, hero is
  `osorio211`.

## Data model (already finalized — do not modify without discussion)

```python
# src/solver/models.py
from pydantic import BaseModel
from datetime import datetime
from enum import Enum

class Street(str, Enum):
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"

class ActionType(str, Enum):
    POST_SB = "post_sb"
    POST_BB = "post_bb"
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    BET = "bet"
    RAISE = "raise"

class Action(BaseModel):
    player: str
    street: Street
    action: ActionType
    amount: float | None = None   # for raises: the "to" total, not the increment
    all_in: bool = False

class StreetCards(BaseModel):
    street: Street
    board: tuple[str, ...]        # cumulative board as of end of this street

class Seat(BaseModel):
    seat_number: int
    player: str
    starting_stack: float
    hole_cards: tuple[str, str] | None = None   # hero always; villains if revealed (preflop or summary)

class PotResult(BaseModel):
    """One seat's outcome for the hand, parsed from *** SUMÁRIO ***.
    Renamed from ShowdownResult: most hands end uncontested (nobody
    showed anything), so "showdown" was inaccurate — this list holds
    every seat that won, showed, or mucked, whether or not a real
    showdown occurred."""
    player: str
    hand_description: str | None = None
    amount_won: float = 0.0

class Hand(BaseModel):
    hand_id: str
    stakes: tuple[float, float]     # (small_blind, big_blind)
    currency: str
    timestamp_utc: datetime
    table_name: str
    table_size: int
    button_seat: int
    seats: list[Seat]
    hero_name: str
    actions: list[Action]
    board_by_street: list[StreetCards]
    pot_results: list[PotResult]    # renamed from showdown
    total_pot: float
    rake: float

class HandParseError(Exception):
    """Raised when a raw hand-text block fails to parse into a Hand."""
    def __init__(self, message: str, raw_text: str) -> None:
        super().__init__(message)
        self.raw_text = raw_text

class FailedHand(BaseModel):
    raw_text: str
    error: str

class ParseResult(BaseModel):
    hands: list[Hand]
    failed: list[FailedHand]
```

All types, including the error and result types above, live in
`models.py`; `pokerstars.py` defines no models or exceptions of its own.

## File layout

```
src/solver/
├── __init__.py
├── __main__.py                # NEW (Part B) — `python -m solver`
├── cli.py                     # NEW (Part B)
├── ingest.py                  # NEW (Part B)
├── store.py                   # NEW (Part B)
├── models.py                  # the model above — unchanged by Part B
└── parser/
    ├── __init__.py
    └── pokerstars.py          # everything below — unchanged by Part B

tests/
├── test_pokerstars_parser.py
├── test_store.py              # NEW (Part B)
├── test_ingest.py             # NEW (Part B)
└── test_cli.py                # NEW (Part B)

data/
├── sample_hands/              # committed test fixtures
│   ├── hand_001.txt                # single hand, hand #261900159976 — golden test fixture
│   ├── hand_002.txt                # session hand #2 — uncontested win ("recebeu (...)")
│   ├── hand_005.txt                # session hand #5 — mucked cards ("escondeu as cartas")
│   ├── hand_024.txt                # session hand #24 — split pot (two "ganhou")
│   └── session_2026-08-28.txt      # full 75-hand export — batch test fixture
├── sessions/                  # NEW (Part B) — real session exports; gitignored
└── solver.db                  # NEW (Part B) — created by `solver ingest`; gitignored
```

## Function signatures — `src/solver/parser/pokerstars.py`

```python
def split_into_hands(raw_text: str) -> list[str]:
    """
    Split a raw multi-hand text blob into individual raw hand-text blocks.
    Boundary = start of each line matching r'^Mão #\\d+ da PokerStars:'
    — NOT the '*** # N ***' banner line. The banner may be absent (e.g. a
    single hand pasted without the surrounding email format), the 'Mão #'
    line is always present.
    """

def parse_hand(raw_hand_text: str, hero_name: str) -> Hand:
    """
    Parse one raw hand-text block into a validated Hand.
    Raises HandParseError (custom exception wrapping the underlying error
    + the raw text) on any failure. Never let a bare exception propagate.
    """

def parse_session(raw_text: str, hero_name: str) -> ParseResult:
    """
    Top-level entry point: split_into_hands() then parse_hand() on each
    block. A failure on one hand must NOT abort the batch — catch
    HandParseError per hand, collect into ParseResult.failed, continue.
    """
```

Internal (private, un-exported) helpers — exact signatures are the
implementer's judgment, but each must exist as a separable, independently
testable function:

- `_filter_noise_lines(lines) -> list[str]` — strip noise lines (see below).
  Run once, early, before any section parsing.
- `_parse_header(line) -> dict` — hand_id, stakes, currency, timestamp_utc
- `_parse_table_line(line) -> dict` — table_name, table_size, button_seat
- `_parse_seats(lines, hole_cards) -> list[Seat]` — the "Lugar N: player
  (stack em fichas)" block, before blind posts. Takes the merged
  hole-cards dict (preflop + summary reveals, see below) and builds each
  `Seat` fully validated the first time — no post-construction patching.
- `_parse_blind_posts(lines) -> list[Action]` — "X: é small/big blind Y €"
  (street=PREFLOP)
- `_split_by_street(lines) -> dict[Street, list[str]]` — split the hand body
  on the `*** X ***` markers
- `_parse_street_actions(lines, street) -> list[Action]`
- `_parse_board(street_marker_line) -> tuple[str, ...]` — extract cards from
  e.g. `*** FLOP *** [5c Ks 4d]`. **TURN/RIVER marker lines carry two
  bracket groups** (e.g. `*** TURN *** [5c Ks 4d] [9d]`) — the cumulative
  board is every card token across *all* bracket groups on the line, not
  just the last one. Extract via a card-token regex applied to the whole
  line, not by parsing individual brackets.
- `_parse_boards(lines) -> list[StreetCards]` — scans the **raw line
  list** (not `_split_by_street`'s output, which discards marker lines)
  for every street marker present, calling `_parse_board` on each. Safe
  to implement fully (all streets) at once — it's uniform extraction, no
  street-specific risk the way action-sequencing has. The orchestrator
  decides how much of its output to actually use per implementation step
  (see "Implementation order" below).
- `_parse_hole_cards(preflop_lines) -> dict[str, tuple[str, str]]` — hero's
  (and occasionally a villain's) cards from `*** CARTAS HOLE ***`.
- `_parse_summary_hole_cards(lines) -> dict[str, tuple[str, str]]` — cards
  revealed in `*** SUMÁRIO ***` ("mostrou [...]" and "escondeu as cartas
  [...]" lines — see quirk #6). Merge with `_parse_hole_cards`'s result
  via `preflop_dict | summary_dict` before calling `_parse_seats` — on
  the rare chance a key appears in both, they describe the same cards for
  the same hand, so which side wins the union is immaterial.
- `_parse_pot_results(lines) -> list[PotResult]` — per-seat win/loss/amount
  outcomes from `*** SUMÁRIO ***`. Does not include cards — those come
  from `_parse_summary_hole_cards` instead (cards live on `Seat`, not
  duplicated onto `PotResult`).
- `_parse_pot_total(lines) -> tuple[float, float]` — (total_pot, rake) from
  the `Total pote X € | comissão Y €` line. Always present, every hand.

All four summary-related functions above scan the **raw line list**, same
reasoning as `_parse_boards`: `_split_by_street` resets to no-street-tracked
at `*** SUMÁRIO ***` and never retains anything after it.

## Noise lines to filter
Confirmed present in the real fixture — filter before street-splitting and
action-parsing, since none of these are player decisions:

- `junta-se à mesa no lugar #N` — player joins mid-hand
- `abandona a mesa` — player leaves mid-hand
- `está sem ligação` — player disconnected
- `gastou o tempo` — player used time bank
- `poderá jogar depois do botão` — late entrant, will play after the button
- `não mostra a mão` — uncontested winner declines to show; it sits at the end
  of the last street (there is no `SHOW DOWN` marker in that case), so it
  would otherwise be read as an unrecognized action

Not necessarily exhaustive — if a new noise pattern shows up in a future
export, add it here.

## Known data quirks (confirmed in the real fixture — not hypothetical)
1. **Seat numbers aren't contiguous.** Players who left leave gaps (e.g.
   seats 1, 3, 5, 6 with no 2 or 4 present). `_parse_seats` must not assume
   a contiguous range.
2. **`Mesa [board]` summary line is absent** when the hand ends preflop (no
   flop dealt). Board assembly must handle zero board cards.
3. **Occasional double blind posts** in one hand — two players both posting
   "big blind" (see hand #67, #75 in the fixture; likely a missed-blind /
   reentry situation). Do not assume exactly one SB + one BB action.
4. **Raise lines carry two numbers**: `sobe 0.21 € para 0.28 €` (raises 0.21
   to 0.28). Store only the **to-total** (0.28) in `Action.amount` — this is
   a deliberate modeling decision, not something to "fix."
5. **All-in is a line suffix** (`e está all-in`), not a separate action
   type — set `Action.all_in = True` on whatever action it modifies.
6. **`*** SUMÁRIO ***` per-seat lines take five distinct shapes** — every
   seat gets exactly one. Real examples from the fixture:

   | Shape | Example | `PotResult` entry? |
   |---|---|---|
   | Shown, won | `mostrou [Kh 9c] e ganhou (1.51 €) com dois pares, Reis e Noves` | yes — cards→`hole_cards`, desc, amount |
   | Shown, lost | `mostrou [Kc 8d] e perdeu com dois pares, Reis e Oitos` | yes — cards→`hole_cards`, desc, `amount_won=0.0` |
   | Won uncontested | `recebeu (0.17 €)` | yes — amount only, no cards/desc |
   | Folded | `desistiu antes Flop (não apostou)` | **no entry** |
   | Mucked | `escondeu as cartas [Kh Jd]` | yes — cards→`hole_cards` only, `amount_won=0.0` |

   A `(Botão)` / `(small blind)` / `(big blind)` parenthetical optionally
   follows the player name on any of these — skip it, it's redundant with
   `button_seat`/blind `Action`s already parsed elsewhere.

   **Do not parse `*** SHOW DOWN ***` at all.** It uses different verbs
   (present tense `mostra`/`esconde a mão`) for the same events `SUMÁRIO`
   already states (past tense `mostrou`/`escondeu`), and — confirmed in
   hand #5 — `SUMÁRIO` reveals mucked cards that `SHOW DOWN` doesn't
   (`ValeraGiraff: esconde a mão` in `SHOW DOWN` vs.
   `ValeraGiraff ... escondeu as cartas [Kh Jd]` in `SUMÁRIO`).
   `SUMÁRIO` is strictly more complete and is the only section present on
   every hand (fold-outs never get a `SHOW DOWN` block).
7. **Split pots are just multiple `PotResult` entries on one hand** —
   confirmed in hand #24, two players both `mostrou [...] e ganhou (...)`.
   No special-casing needed; the list already supports it.

## Implementation order — keep populated fields symmetric
Extend one street at a time, and populate both `actions` and
`board_by_street` for that street **together**. Never populate a street's
board while leaving its actions unparsed (or vice versa) — a `Hand` where
one field looks complete and the other doesn't is misleading to anything
consuming it. `_parse_street_actions`'s guard (`street not in (...)`)
should list exactly the streets currently wired up in `parse_hand`.

Same principle for the summary step: `pot_results`, the hole-cards merge,
and `total_pot`/`rake` are all sourced from `*** SUMÁRIO ***` and should
land together, not incrementally.

## Test plan (write incrementally, matching implementation order)
1. `test_parse_hand_001_preflop` — hand_id, stakes, all 6 seats with correct
   stacks, hero's hole_cards via `seats`, full preflop action sequence.
2. Extend through flop → turn → river as each is implemented.
3. `test_parse_hand_001_full` — `pot_results` (hand #1 has a real
   shown-won/shown-lost pair), `total_pot`, `rake`. **Hand #1 alone does
   not exercise the "mucked" or "split pot" shapes from quirk #6** — worth
   pulling a second single-hand fixture (hand #5 has a mucked case; hand
   #24 has a split pot) for explicit coverage, rather than relying on the
   batch test to catch a bug in either path silently.
4. `test_parse_session_batch` — `parse_session()` on the full 75-hand file
   returns `len(result.hands) == 75` and `len(result.failed) == 0`.

## Explicitly out of scope for this module
- Session/table reconstruction (join/leave tracking) — noise lines are
  discarded, not modeled.
- Any non-PokerStars-.pt format.
- Any statistics, leak-detection, or LLM-analysis logic — this module's
  only job is raw text → validated `Hand` objects.
- File I/O and persistence — `pokerstars.py` stays pure (text in, objects
  out). Reading files and storing hands live in `ingest.py` / `store.py`
  (Part B).

---

# Part B — Multi-file ingest & SQLite persistence

## Goal
`solver ingest <folder> --hero <name>` reads every session file in a
folder, parses each with the existing `parse_session()`, and persists all
hands into a local SQLite DB, deduped by `hand_id`. Downstream modules
(facts engine, coach) obtain hands **only** through `store.py` as
`list[Hand]` — never by querying the DB directly and never by re-parsing
text.

## Decisions (agreed — do not relitigate)
- **SQLite via stdlib `sqlite3`. No ORM, no new dependencies.** Rejected:
  JSON-file-per-hand, JSONL, CSV, fully normalized schema.
  Why SQLite: atomic upsert gives dedupe for free; provenance columns
  (`source_file`) without touching `Hand`; later tables (coach outputs,
  eval runs — keyed by `hand_id`) join naturally in the same DB.
- **`Hand` is stored as one JSON blob** (`Hand.model_dump_json()`), with a
  few promoted columns for filtering. Normalize into seats/actions tables
  only if a real query demands it — not now.
- **Session `.txt` files are the source of truth.** The DB is a rebuildable
  cache: if `Hand` ever changes shape, re-run `solver ingest`.
- **Dedupe key = `hand_id`** (globally unique on PokerStars). Duplicates
  are **upserted: replace the whole row, latest parse wins** — so
  re-ingesting after a parser fix refreshes stored hands.
- **Session = source file.** Stored as the file's basename in
  `source_file`. Consequence: a hand present in two overlapping files is
  attributed to the file processed last (files are processed in sorted
  filename order).
- **Failed hands are reported, not persisted.**
- `models.py` and `pokerstars.py` are not modified. Result/report types
  for ingest are plain `@dataclass`es in `ingest.py`.

## Paths and gitignore
- Input folder: any path passed on the CLI; convention is `data/sessions/`.
- Default DB path: `data/solver.db` (constant `DEFAULT_DB_PATH` in
  `store.py`, overridable via `--db`).
- Add to `.gitignore`: `data/sessions/` and `data/*.db*` (covers
  `-journal` / `-wal` side files). Real hand histories and the DB are
  personal data and must not be committed. `data/sample_hands/` stays
  committed.

## Schema
Created by `store.connect()` with `CREATE ... IF NOT EXISTS` (idempotent).

```sql
CREATE TABLE IF NOT EXISTS hands (
    hand_id       TEXT PRIMARY KEY,
    timestamp_utc TEXT NOT NULL,   -- Hand.timestamp_utc.isoformat()
    source_file   TEXT NOT NULL,   -- basename of the session file
    ingested_at   TEXT NOT NULL,   -- ISO 8601 UTC, set at save time
    data          TEXT NOT NULL    -- Hand.model_dump_json()
);
CREATE INDEX IF NOT EXISTS idx_hands_timestamp ON hands(timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_hands_source    ON hands(source_file);
```

Notes:
- All hands come from the same parser, so `timestamp_utc` strings share one
  format and sort chronologically as text.
- SQLite has no JSON column type; `data` is `TEXT`. Ad-hoc inspection via
  `sqlite3 data/solver.db "select json_extract(data,'$.stakes') from hands limit 5"`
  works on any modern SQLite build.

## `src/solver/store.py`

```python
DEFAULT_DB_PATH = Path("data/solver.db")

def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """
    Open the DB (creating the parent directory and file if missing), set
    row_factory = sqlite3.Row, ensure the schema exists, return the
    connection. ":memory:" is allowed (no directory creation). The caller
    closes it (use contextlib.closing).
    """

def save_hands(conn: sqlite3.Connection, hands: list[Hand],
               source_file: str) -> tuple[int, int]:
    """
    Upsert hands keyed by hand_id inside ONE transaction (all-or-nothing;
    use `with conn:`). Returns (inserted, updated). `source_file` is the
    basename. `ingested_at` = one UTC timestamp for the whole call.
    Empty list -> (0, 0), no error.
    """

def load_hands(conn: sqlite3.Connection, *, source_file: str | None = None,
               since: datetime | None = None,
               until: datetime | None = None) -> list[Hand]:
    """
    Return hands ordered by (timestamp_utc ASC, hand_id ASC). Optional
    filters: source_file exact match; since inclusive; until exclusive.
    `since`/`until` are compared as ISO strings, so callers must pass
    datetimes with the same tz-awareness as Hand.timestamp_utc.
    Rebuilds objects via Hand.model_validate_json(row["data"]).
    """

def get_hand(conn: sqlite3.Connection, hand_id: str) -> Hand | None: ...

def count_hands(conn: sqlite3.Connection) -> int: ...
```

Behaviour requirements:
- Upsert SQL (parameterized — never string-format values into SQL):
  ```sql
  INSERT INTO hands (hand_id, timestamp_utc, source_file, ingested_at, data)
  VALUES (?, ?, ?, ?, ?)
  ON CONFLICT(hand_id) DO UPDATE SET
      timestamp_utc = excluded.timestamp_utc,
      source_file   = excluded.source_file,
      ingested_at   = excluded.ingested_at,
      data          = excluded.data
  ```
- To split inserted vs updated, run `SELECT 1 FROM hands WHERE hand_id = ?`
  per hand before its upsert, inside the same transaction. (A hand_id
  repeated within one input list counts its second occurrence as updated.)
- `load_hands` / `get_hand` **do not catch** pydantic `ValidationError`. If
  stored JSON no longer matches `Hand`, the remedy is to re-run
  `solver ingest` — do not silently skip rows.
- Round-trip guarantee: `get_hand(conn, h.hand_id) == h` for every parsed
  `Hand` `h` (tuples, enums, datetimes survive the JSON round-trip).

## `src/solver/ingest.py`

```python
@dataclass
class FileIngestResult:
    source_file: str                 # basename
    parsed: int = 0                  # hands successfully parsed
    inserted: int = 0                # new hand_ids stored
    updated: int = 0                 # existing hand_ids replaced
    failed: list[FailedHand] = field(default_factory=list)
    read_error: str | None = None    # set if the file could not be read/decoded

def find_session_files(folder: Path, pattern: str = "session_*.txt") -> list[Path]:
    """Non-recursive glob; files only; sorted by name."""

def ingest_file(path: Path, hero_name: str,
                conn: sqlite3.Connection) -> FileIngestResult: ...

def ingest_folder(folder: Path, hero_name: str,
                  conn: sqlite3.Connection) -> list[FileIngestResult]:
    """
    Calls find_session_files() then ingest_file() on each, in order.
    Raises FileNotFoundError if `folder` doesn't exist. Returns [] if no
    file matches (the CLI treats that as a fatal error).
    """
```

Behaviour requirements:
- Pattern is `session_*.txt`, which matches both `session_2026-08-28.txt`
  and `session_20260828.txt`. Sorted-by-name order is chronological for
  either naming style as long as one style is used consistently.
- `ingest_file`: read with `encoding="utf-8-sig"` (Portuguese characters,
  tolerates a BOM) → `parse_session(text, hero_name)` →
  `save_hands(conn, result.hands, path.name)` → build the result.
  **One file = one transaction.**
- Catch `(OSError, UnicodeDecodeError)` on read: set `read_error`, persist
  nothing for that file, and **continue with the remaining files**.
- A file where `parsed == 0` and `failed` is empty (nothing recognizable as
  a hand) is not an error at this layer; the CLI warns about it.
- `hero_name` is passed through unchanged; never hardcode it.

## `src/solver/cli.py` and `__main__.py`

```
solver ingest FOLDER [--hero NAME] [--db PATH]
```

- Implemented with stdlib `argparse`, using subcommands
  (`add_subparsers(dest="command", required=True)`) since more commands
  (coach, etc.) will follow.
- `main(argv: list[str] | None = None) -> int` returns the exit code.
  `__main__.py`: `raise SystemExit(main())`. If a `pyproject.toml` exists,
  also register `[project.scripts] solver = "solver.cli:main"`.
- `--hero`: falls back to env var `SOLVER_HERO`; if neither is set, print
  an error and return 1.
- `--db`: defaults to `DEFAULT_DB_PATH`.
- Use `with contextlib.closing(store.connect(db)) as conn:`.

Output (one line per file, then failures, then totals):

```
session_2026-08-28.txt  parsed 75  new 75  updated 0   failed 0
session_2026-09-03.txt  parsed 80  new 62  updated 18  failed 1
  FAILED  session_2026-09-03.txt | Mão #123456789 da PokerStars: ... | <error message>
  WARNING session_x.txt | no hands found
  ERROR   session_y.txt | could not read file: <read_error>
---
Files: 2  Parsed: 155  New: 137  Updated: 18  Failed: 1
DB: data/solver.db (total hands: 137)
```

- FAILED line: source file, first line of `FailedHand.raw_text`, and
  `FailedHand.error` — one line each.
- Exit codes: **0** = every file read and every hand parsed; **1** = fatal
  (missing hero, folder missing/not a directory, no files matched the
  pattern); **2** = completed, but at least one hand failed to parse or one
  file could not be read.

## Implementation order (incremental — full suite green after each step)
1. `store.py` + `test_store.py`. Start with the round-trip test on
   `hand_001`; then upsert/dedupe/ordering/filter tests.
2. `ingest.py` + `test_ingest.py`.
3. `cli.py`, `__main__.py`, `.gitignore` entries + `test_cli.py`.

The existing parser tests must stay green throughout; Part B never edits
`models.py` or `pokerstars.py`.

## Test plan
Use pytest's `tmp_path` for all DBs and folders (never touch
`data/solver.db`). Hero is `osorio211`; fixtures come from
`data/sample_hands/`.

`test_store.py`
1. **Round-trip:** parse `hand_001` → `save_hands` → `get_hand` returns an
   object `==` to the original.
2. **Idempotent:** saving the same hands twice → `count_hands` unchanged;
   second call returns `(0, n)`.
3. **Upsert replaces:** save a copy with a changed field
   (`hand.model_copy(update={"rake": 9.99})`) and a different
   `source_file` → `get_hand` shows the new rake; `source_file` column
   updated; row count unchanged.
4. **Batch:** parse the 75-hand session → `save_hands` returns `(75, 0)`;
   `count_hands == 75`.
5. **`load_hands` ordering and filters:** result is sorted by timestamp;
   `source_file`, `since`, `until` filters behave as specified (`since`
   inclusive, `until` exclusive).
6. **Empty input:** `save_hands(conn, [], "x.txt") == (0, 0)`.
   `test_ingest.py`
7. **Multi-file:** folder with `session_a.txt`, `session_b.txt` and a
   non-matching `notes.txt` → only the two session files are processed, in
   sorted order.
8. **Overlapping sessions:** build two files from the 75-hand fixture via
   `split_into_hands` (e.g. hands 1–50 and 40–75, blocks joined with blank
   lines) → 75 unique hands stored; per-file results add up
   (`inserted` total 75, `updated` total 11).
9. **Re-ingest:** running `ingest_folder` twice → second run has
   `inserted == 0`, `updated == parsed` for every file.
10. **Failure isolation (hand level):** append a broken block
    (`"Mão #999 da PokerStars: garbage"`) to a session file → `failed` has
    1 entry; all valid hands still persisted.
11. **Failure isolation (file level):** a file containing invalid UTF-8
    bytes (e.g. `b"\xff\xfe\x00"`) → `read_error` set, other files still
    ingested. `test_cli.py` (use `capsys`, `monkeypatch`)
12. Happy path: `main(["ingest", str(folder), "--hero", "osorio211", "--db", str(db)]) == 0`;
    output contains the totals line.
13. No matching files → returns 1.
14. Missing hero (no `--hero`, `SOLVER_HERO` unset via `monkeypatch.delenv`)
    → returns 1.
15. Folder with a broken hand block → returns 2, output contains a
    `FAILED` line.

## Explicitly out of scope for Part B
- Tables for coach outputs, LLM judgments, eval labels/runs (added later,
  keyed by `hand_id`, in the same DB).
- Normalized seats/actions tables, migrations, ORM, WAL tuning.
- Persisting failed hands; deleting/purging hands; a separate `sessions`
  table.
- Recursive folder scan, folder watching / auto-ingest, other file
  patterns.
- Concurrent writers (single-user CLI).

## Definition of done (Part B)
- `solver ingest data/sample_hands --hero osorio211` stores all hands from
  the fixture session(s); running it a second time yields 0 new, all
  updated.
- Overlapping-sessions test passes (no duplicate `hand_id`s in the DB).
- `store.load_hands()` returns `Hand` objects equal to freshly parsed ones.
- Full test suite green (Part A + Part B); `models.py` and
  `pokerstars.py` unchanged.