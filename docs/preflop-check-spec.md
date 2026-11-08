# Preflop Check — Implementation Spec

## Status
- **Depends on:** Part A (parser) and Part B (ingest + SQLite). Both are done and must stay green.
- **This spec (Part C):** a deterministic check of hero's **first voluntary preflop decision** in every stored hand against `data/playbook.md`. Results go into a queryable table and a CLI report.
- **Existing code:** `pokerstars.py`, `ingest.py` and the existing models in `models.py` are **not modified**. `models.py` gets new types only (additive). `store.py` and `cli.py` are extended.

## Goal
```
solver preflop [--playbook PATH] [--db PATH] [--session FILE] [--since YYYY-MM-DD] [--until YYYY-MM-DD]
```
1. Load and validate the playbook. Any error aborts the run.
2. Load **all** hands via `store.load_hands(conn)`.
3. Run `check_preflop(hand, playbook)` on each hand. This yields exactly one `DecisionCheck` per hand.
4. **Replace** the whole `preflop_checks` table with the new results in one transaction, stamped with the playbook hash.
5. Print a report for the filtered subset (session or date range). Without filters, the report covers all hands.

The full rebuild on every run is deliberate. It's cheap, and it guarantees the table always matches one playbook version.

## Decisions (agreed — do not relitigate)
- **Scope is hero's first voluntary preflop action only.** Everything later (facing a 3-bet after opening, limp-then-raise, ...) belongs to the coach, not this module.
- **Playbook format** is Markdown containing ```` ```toml ```` blocks. Only those blocks are parsed; prose is ignored. Ranges expand to the 169 hand classes, not combos.
- **A hand not listed in any action of an entry gets the default action**: `fold`, or `check` when hero can check for free.
- **Sizes are absolute bb.** 3-bet sizing is checked only when the open hero faces is close to the standard open (see Sizing).
- **Extra BB posters** (players posting a blind outside the BB position) count as limpers.
- **Hero posting a non-positional blind** keeps their actual position label. When hero can check for free, the default action is `check`.
- **Heads-up** (exactly 2 players dealt in) has its own nodes.
- **`check_preflop` is pure**: no file or DB access, never raises for bad poker data. Anomalies become `unsupported` or `no_decision` with a reason.
- **One row per hand**, including `no_decision` rows, so denominators are correct.
- **The table stores plain columns** (no JSON blob), because it exists to be queried.

## File layout
```
src/solver/
├── models.py        # + new enums and DecisionCheck (additive)
├── playbook.py      # NEW — range expansion, hand class, parse/validate/lookup
├── preflop.py       # NEW — positions, node classification, check_preflop
├── report.py        # NEW — summarize + format_report (pure)
├── store.py         # + preflop_checks table, view, save/load
└── cli.py           # + `preflop` subcommand
data/
└── playbook.md      # committed; the user's strategy (source of truth)
tests/
├── fixtures/playbook_min.md   # NEW — small, stable playbook for tests
├── helpers.py                 # NEW — make_hand() builder for synthetic hands
├── test_playbook.py           # NEW
├── test_preflop.py            # NEW
├── test_report.py             # NEW
├── test_store.py              # + preflop tests
└── test_cli.py                # + preflop tests
```
**Tests must not depend on the ranges in `data/playbook.md`.** The user will keep editing them. Use `tests/fixtures/playbook_min.md`. The only test that touches the real playbook asserts that it parses.

## New types — `src/solver/models.py` (additive)

```python
class Position(str, Enum):
    UTG = "UTG"; HJ = "HJ"; CO = "CO"; BTN = "BTN"; SB = "SB"; BB = "BB"

PREFLOP_ORDER = (Position.UTG, Position.HJ, Position.CO, Position.BTN, Position.SB, Position.BB)

class Node(str, Enum):
    RFI = "rfi"; VS_LIMP = "vs_limp"; VS_OPEN = "vs_open"
    VS_OPEN_CALLED = "vs_open_called"; VS_RERAISE = "vs_reraise"; VS_SHOVE = "vs_shove"
    HU_RFI = "hu_rfi"; HU_VS_OPEN = "hu_vs_open"; HU_VS_LIMP = "hu_vs_limp"

class Move(str, Enum):
    FOLD = "fold"; CHECK = "check"; LIMP = "limp"; OVERLIMP = "overlimp"
    CALL = "call"; RAISE = "raise"; THREE_BET = "three_bet"

PASSIVE_MOVES = frozenset({Move.FOLD, Move.CHECK})

class CheckStatus(str, Enum):
    OK = "ok"; DEVIATION = "deviation"; NOT_COVERED = "not_covered"
    UNSUPPORTED = "unsupported"; NO_DECISION = "no_decision"

class DeviationKind(str, Enum):
    TOO_LOOSE = "too_loose"; TOO_TIGHT = "too_tight"
    WRONG_ACTION = "wrong_action"; SIZING = "sizing"

class DecisionCheck(BaseModel):
    hand_id: str
    status: CheckStatus
    reason: str | None = None              # set for unsupported / no_decision / errors
    hero_pos: Position | None = None
    node: Node | None = None
    opener_pos: Position | None = None     # vs_open / vs_open_called / vs_reraise (first raiser)
    n_limpers: int = 0
    n_callers: int = 0
    hand_class: str | None = None          # e.g. "K6s", "AKo", "TT"
    expected_action: Move | None = None
    actual_action: Move | None = None
    deviation_kind: DeviationKind | None = None
    facing_size_bb: float | None = None    # size of the raise relevant to the node (see Sizing)
    actual_size_bb: float | None = None    # hero's raise-to, in bb
    expected_size_bb: float | None = None
    sizing_checked: bool = False
```
Fill every field that is known even when the status is `not_covered`, `unsupported` or `no_decision`; for example `hero_pos` and `hand_class` when available. bb values are rounded to 2 decimals.

## `src/solver/playbook.py`

### Public API
```python
DEFAULT_PLAYBOOK_PATH = Path("data/playbook.md")

class PlaybookError(Exception):
    """Invalid playbook. Message must locate the problem (block #, node, entry index, token)."""

def expand_range(text: str) -> frozenset[str]: ...
def hand_class(cards: tuple[str, str]) -> str: ...
def parse_playbook(markdown: str) -> Playbook: ...
def load_playbook(path: Path | str = DEFAULT_PLAYBOOK_PATH) -> Playbook: ...   # utf-8, then parse

class Playbook:                       # implementer's choice: pydantic model or frozen dataclass
    sizing: SizingRules               # standard_open_bb, open_tolerance_bb, size_tolerance_bb
    limits: Limits                    # hero_min_stack_bb, short_allin_max_bb
    hash: str                         # see "Playbook hash"
    def lookup(self, node: Node, hero: Position | None,
               opener: Position | None = None, shove_bb: float | None = None) -> Entry | None: ...

class Entry:                          # one resolved (node, hero, opener) combination
    node: Node
    actions: dict[Move, frozenset[str]]   # hand classes per action; @rfi already resolved
    size_bb: float | None
    iso_base_bb: float | None
    iso_per_limper_bb: float | None
    three_bet_bb: float | None
    per_caller_bb: float | None
    max_bb: float | None              # vs_shove only
    def expected(self, hand_class: str, default: Move) -> Move: ...
```

### Range grammar
- Tokens are comma-separated; whitespace is ignored. Ranks are uppercase `AKQJT98765432`; suitedness is lowercase `s`/`o`.

| Token | Meaning | Example → classes |
|---|---|---|
| `77` | one pair | `77` |
| `77+` | pair and all higher | `77..AA` (8) |
| `QQ-JJ` | pairs, inclusive, high first | 2 |
| `AKs` / `AKo` | one class | 1 |
| `AK` | both suited and offsuit | `AKs, AKo` |
| `A2s+` | same high card; kicker from given up to one below high card | `A2s..AKs` (12) |
| `KJo+` | as above | `KJo, KQo` |
| `AQs-A2s` | same high card and suitedness, kicker range inclusive, high first | 11 |

- Reject with `PlaybookError`:
  - unknown ranks or suffixes (`A1s`, `AKx`);
  - low card first (`KAs`);
  - dash ranges mixing high cards or suitedness (`AQs-K2s`, `AQs-A2o`);
  - dash ranges written low-to-high (`22-77`).
- `"@rfi"` (the whole value) is a reference to hero's `rfi` raise range. It is resolved per hero at parse time. It is an error if that hero has no `rfi` entry.

### `hand_class`
Higher rank first. A pair gives `"TT"`; otherwise suffix `s` if the suits match, else `o`. Card strings are like `"Kh"` and `"Td"`, as produced by the parser.

### Schema (validated, `extra="forbid"`)
Every node is an array of tables (`[[node]]`). `sizing` and `limits` are single tables and both are required. `hero` and `opener` accept a string or a list of strings.

| Node | `hero` allowed | `opener` | Action keys (all optional) | Size keys (required unless noted) |
|---|---|---|---|---|
| `rfi` | UTG, HJ, CO, BTN, SB | — | `raise`, `limp` | `size_bb` |
| `vs_limp` | any | — | `raise`, `overlimp` | `iso_base_bb`, `iso_per_limper_bb` |
| `vs_open` | any but UTG | required; must precede hero in `PREFLOP_ORDER` | `three_bet`, `call` | `three_bet_bb` |
| `vs_open_called` | any but UTG | — | `three_bet`, `call` | `three_bet_bb`, `per_caller_bb` |
| `vs_reraise` | any | — | `raise`, `call` | none |
| `vs_shove` | no `hero` key | — | `call` | `max_bb` (≤ `limits.short_allin_max_bb`, unique) |
| `hu_rfi` | BTN | — | `raise`, `limp` | `size_bb` |
| `hu_vs_open` | BB | — | `three_bet`, `call` | `three_bet_bb` |
| `hu_vs_limp` | BB | — | `raise` | `iso_base_bb` (`iso_per_limper_bb` optional, default 0) |

Action key → `Move`: `raise→RAISE`, `limp→LIMP`, `overlimp→OVERLIMP`, `call→CALL`, `three_bet→THREE_BET`.

### Validation rules
Each rule raises `PlaybookError` with the location of the problem.
1. TOML syntax error in any block (report the block number).
2. Unknown top-level key, or a node not written as an array of tables.
3. Unknown, missing or ill-typed keys per the schema; invalid positions.
4. Invalid range token.
5. Within one entry, action ranges overlap (report the overlapping classes).
6. A `(node, hero, opener)` combination defined by more than one entry. For `vs_shove`, duplicate `max_bb`.
7. `@rfi` unresolvable.
8. Missing `sizing` or `limits`.

### Lookup
- At parse time, expand multi-hero and multi-opener entries into a dict keyed by `(node, hero, opener | None)` → `Entry`. Lookup is then a plain dict get.
- `vs_shove`: return the entry with the smallest `max_bb ≥ shove_bb`, or `None`.
- No entry → `None`. The caller turns that into `not_covered`.

### Playbook hash
First 12 hex characters of the SHA-256 of a canonical JSON dump of the **parsed** playbook (sorted keys, ranges as sorted lists). Editing prose must not change the hash; editing a range or size must.

## `src/solver/preflop.py`

```python
def check_preflop(hand: Hand, playbook: Playbook) -> DecisionCheck: ...
```
Internal helpers, each separately testable: `_active_players`, `_assign_positions`, `_hero_first_action`, `_classify`, `_actual_move`, `_expected_size`.

All amounts in bb are `amount / hand.stakes[1]`. `Action.amount` for raises is the raise-to total.

### Evaluation order (first match wins)
| # | Condition | Result |
|---|---|---|
| 1 | Hero has no seat, or no hole cards | `no_decision`, reason `hero_not_dealt` |
| 2 | Positions cannot be assigned (rules below) | `unsupported`, reason `position_ambiguous` |
| 3 | Hero has no preflop action other than blind posts (e.g. a walk) | `no_decision`, reason `no_hero_action` |
| 4 | Hero `starting_stack / bb < limits.hero_min_stack_bb` | `unsupported`, reason `hero_short_stack` |
| 5 | Node cannot be classified (rules below) | `unsupported`, reason `unclassified` |
| 6 | `playbook.lookup(...)` returns `None` | `not_covered` |
| 7 | Otherwise | compare expected vs actual → `ok` / `deviation` |

### Positions
1. **Active players** are players with at least one preflop `Action` (posts included). Every player dealt in either posts a blind or acts preflop, so seated players who are sitting out are excluded.
2. **Clockwise order:** sort active players by seat number, rotated to start at the first seat after `button_seat` (wrap around). Seat numbers can be non-contiguous.
3. **Heads-up** (exactly 2 active players):
   - the player on `button_seat` is `BTN`, the other is `BB`;
   - if neither is on `button_seat`, the result is `position_ambiguous`.
4. **3 or more active players:**
   - **True BB** = the first `POST_BB` poster in clockwise order. If nobody posted the BB, the result is `position_ambiguous`.
   - **SB** = the active player immediately before the true BB in clockwise order, if they posted `POST_SB`.
   - **Non-blind players** = everyone else, in clockwise order starting after the BB. Label them from the end backwards: `BTN, CO, HJ, UTG`.
   - With more than 4 non-blind players, or if the player labelled `BTN` is not on `button_seat`, the result is `position_ambiguous`.
5. **Extra posters** are any `POST_BB` other than the true BB's. They keep their non-blind label, and their post counts as a **limp**. A `POST_SB` by a non-SB player is dead money and is ignored. A combined "small & big blinds" post reaches this module as one `POST_SB` plus one `POST_BB` for that player, so these rules cover it.

### Node classification
- **Prior actions** are the preflop actions before hero's first voluntary action, excluding all `POST_SB` actions and the true BB's `POST_BB`.
- **`n_limpers`** = `CALL`s before the first `RAISE`, plus extra `POST_BB`s by players other than hero.
- **`n_callers`** = `CALL`s after the first `RAISE`.
- **`opener_pos`** = the position of the first raiser.
- **Short all-in:** a `RAISE` with `all_in=True` and `amount_bb ≤ limits.short_allin_max_bb`.

**Heads-up:**
- Hero `BTN`: `hu_rfi` if there are no prior actions; otherwise `unclassified`.
- Hero `BB`:
  - if the BTN's only prior action is a short all-in → `vs_shove`;
  - one `RAISE` → `hu_vs_open`;
  - one `CALL` → `hu_vs_limp`;
  - anything else → `unclassified`.

**3 or more players** (first match wins):
1. The last prior `RAISE` is a short all-in → `vs_shove` (`shove_bb` = its size).
2. Two or more prior `RAISE`s → `vs_reraise`.
3. One `RAISE` and `n_callers ≥ 1` → `vs_open_called`.
4. One `RAISE` → `vs_open`.
5. `n_limpers ≥ 1` → `vs_limp`.
6. Otherwise → `rfi`.

### Free check
Hero can check for free when there is no prior `RAISE` and hero has posted a live BB (true BB or extra poster). The **default move** for the lookup is then `CHECK`; otherwise it is `FOLD`.

### Actual move (hero's first voluntary action → `Move`)
| ActionType | rfi / hu_rfi | vs_limp / hu_vs_limp | vs_open / vs_open_called / hu_vs_open | vs_reraise / vs_shove |
|---|---|---|---|---|
| FOLD | FOLD | FOLD | FOLD | FOLD |
| CHECK | CHECK | CHECK | — | — |
| CALL | LIMP | OVERLIMP | CALL | CALL |
| RAISE (or BET) | RAISE | RAISE | THREE_BET | RAISE |

Any combination marked `—` → `unsupported`, reason `unexpected_action`.

### Comparison
`expected = entry.expected(hand_class, default)`.

| Condition | Result |
|---|---|
| `expected == actual` | `ok`, unless the sizing check fails → `deviation` / `sizing` |
| expected is passive (FOLD, CHECK), actual is not | `too_loose` |
| expected is not passive, actual is passive | `too_tight` |
| both non-passive and different | `wrong_action` |

### Sizing
Sizing is evaluated only when `expected == actual` and the move is a raise-type move (`RAISE` or `THREE_BET`).

| Node | `expected_size_bb` | Checked when | `facing_size_bb` |
|---|---|---|---|
| `rfi`, `hu_rfi` | `size_bb` | always | `None` |
| `vs_limp`, `hu_vs_limp` | `iso_base_bb + iso_per_limper_bb × n_limpers` | always | `None` |
| `vs_open`, `hu_vs_open` | `three_bet_bb` | `abs(open_bb − standard_open_bb) ≤ open_tolerance_bb` | open size |
| `vs_open_called` | `three_bet_bb + per_caller_bb × n_callers` | same gate | open size |
| `vs_reraise` | `None` | never | last raise size |
| `vs_shove` | `None` | never | shove size |

- `actual_size_bb` = hero's raise-to in bb (set whenever hero raises).
- When checked, a deviation is `abs(actual − expected) > size_tolerance_bb`.
- `sizing_checked` records whether the check ran.

## `src/solver/report.py` (pure)
```python
def summarize(checks: list[DecisionCheck]) -> PreflopSummary: ...
def format_report(summary: PreflopSummary, *, scope: str, playbook_hash: str, db_path: str) -> str: ...
```

**Summary contents:**
- counts per status;
- adherence = `ok / (ok + deviation)`;
- counts per deviation kind;
- a by-spot table keyed by `node.hero_pos`, with columns n (ok + deviation), dev, loose, tight, wrong, sizing, sorted by dev descending then n descending;
- the deviations list;
- not-covered spots grouped by `(node, hero_pos, opener_pos)` with counts;
- unsupported and no-decision hands grouped by reason with counts.

**Output shape:**
```
Preflop check — scope: session_2026-08-28.txt | playbook a1b2c3d4e5f6 | DB data/solver.db
Hands: 75 | assessed 61 | no_decision 9 | not_covered 3 | unsupported 2
Adherence: 52/61 (85.2%) | too_loose 5 | too_tight 2 | wrong_action 1 | sizing 1

Spot             n  dev  loose  tight  wrong  sizing
rfi.BTN         12    3      3      0      0       0
vs_open.BB       9    2      0      2      0       0
...

Deviations
  261900159976  BTN  K6s  rfi              expected fold       actual raise      too_loose
  261900160011  CO   AJo  rfi              expected raise 3.0  actual raise 5.0  sizing
  ...
Playbook gaps (not_covered)
  vs_open_called.SB (opener CO)  2
Unsupported / no decision
  hero_short_stack  1 | position_ambiguous  1 | no_hero_action  7 | hero_not_dealt  2
```
**Assessed** = ok + deviation. With zero assessed hands, print `Adherence: n/a`.

## `src/solver/store.py` (extend)

Add to the schema created by `connect()`:
```sql
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
    sizing_checked   INTEGER NOT NULL,      -- 0/1
    playbook_hash    TEXT NOT NULL,
    checked_at       TEXT NOT NULL          -- ISO 8601 UTC, one value per run
);
CREATE VIEW IF NOT EXISTS v_preflop AS
    SELECT h.source_file, h.timestamp_utc, p.*
    FROM preflop_checks p JOIN hands h USING (hand_id);
```
Foreign-key enforcement stays off (the default). Ingest upserts and never deletes hands, so references stay valid.

```python
def replace_preflop_checks(conn, checks: list[DecisionCheck], playbook_hash: str) -> int:
    """ONE transaction: DELETE all rows, INSERT all checks. Returns row count."""

def load_preflop_checks(conn, *, source_file: str | None = None,
                        since: datetime | None = None,
                        until: datetime | None = None) -> list[DecisionCheck]:
    """Query v_preflop; same filter semantics as load_hands; order (timestamp_utc, hand_id)."""

def preflop_playbook_hash(conn) -> str | None:
    """Distinct playbook_hash in the table, or None if empty."""
```
- Enums are stored as their string values. Loading rebuilds an equal `DecisionCheck` (round-trip guarantee).
- SQL is parameterized, as in Part B.

## `src/solver/cli.py` (extend)
New subcommand `preflop`:
- `--playbook`: defaults to `DEFAULT_PLAYBOOK_PATH`.
- `--db`: defaults to `DEFAULT_DB_PATH`.
- `--session`: an exact `source_file` basename.
- `--since` / `--until`: `YYYY-MM-DD`, converted to midnight with the same tz-awareness as stored `Hand.timestamp_utc`. `since` is inclusive, `until` exclusive.
- No `--hero`: `Hand.hero_name` already carries it.

**Flow:**
1. `load_playbook`.
2. `connect`.
3. `load_hands(conn)` (all hands).
4. Check each hand.
5. `replace_preflop_checks`.
6. `load_preflop_checks(filters)`.
7. `summarize` and `format_report`, then print.

**Error isolation:** wrap each `check_preflop` call. An unexpected exception becomes a `DecisionCheck(status=UNSUPPORTED, reason=f"error: {exc!r}")` and the run continues.

**Exit codes:**
- **0** — success.
- **1** — fatal:
  - `PlaybookError` (print the message);
  - playbook file missing;
  - DB has zero hands;
  - `--session` matches no hands.
- **2** — completed, but at least one hand hit an unexpected exception.

## Tests

### Fixtures and helpers
- `tests/fixtures/playbook_min.md`: a few small entries, enough to cover every node, `@rfi`, a multi-hero entry, a multi-opener entry, and two `vs_shove` buckets. It includes `sizing` and `limits` blocks with the same values as `data/playbook.md`.
- `tests/helpers.py::make_hand(...)`: builds a valid `Hand` from compact inputs (seats with stacks, button seat, hero name and cards, ordered preflop actions, stakes default `(0.01, 0.02)`). Synthetic hands are the main way to cover edge cases.

### `test_playbook.py`
1. **`expand_range`** (table-driven): `77+`→8, `QQ-JJ`→2, `A2s+`→12, `AQs-A2s`→11, `KJo+`→{KJo, KQo}, `AK`→2; whitespace tolerated. Invalid tokens (`A1s`, `AKx`, `KAs`, `AQs-K2s`, `AQs-A2o`, `22-77`) raise.
2. **`hand_class`:** `("Kh","6h")`→`K6s`, `("6h","Kd")`→`K6o`, `("Td","Tc")`→`TT`. Mapping all 1,326 combos gives exactly 169 classes, with combo counts 6, 4 and 12 for pairs, suited and offsuit.
3. **The real `data/playbook.md` parses.** No range assertions.
4. **One failing playbook per validation rule** (1–8), each raising `PlaybookError`.
5. **`@rfi`** in `vs_limp` resolves to that hero's `rfi` raise set.
6. **Lookup:** multi-hero and multi-opener keys resolve correctly. `vs_shove` buckets in the fixture: 10→12-bucket, 12→12, 13→25, 30→None.
7. **Hash:** unchanged by a prose edit, changed by a range edit.

### `test_preflop.py` (synthetic hands unless stated)
**Positions:**
- 6, 5, 4 and 3 active players: 5-handed has no UTG; 3-handed is BTN/SB/BB.
- Non-contiguous seats; button wrap-around.
- A seated player with no actions is excluded.
- Heads-up: BTN and BB.
- Extra BB poster keeps their label and counts as a limper.
- No BB post → `position_ambiguous`.

**Nodes:** one test each for:
- `rfi`;
- `vs_limp` with 1 and 2 limpers, including an SB completion;
- extra poster counted as a limper;
- `vs_open`, with `opener_pos`;
- `vs_open_called`, with `n_callers`;
- `vs_reraise`;
- `vs_shove` (short all-in), while a 40bb all-in open is `vs_open`;
- all three `hu_*` nodes.

**Statuses:**
- `ok`, `too_loose`, `too_tight`, `wrong_action`.
- `sizing` deviation in `rfi`.
- 3-bet facing a 2bb open → `sizing_checked=False`, no sizing deviation.
- `vs_open_called` expected size includes per-caller bb.
- `not_covered`.
- `hero_short_stack`.
- Walk → `no_decision` / `no_hero_action`.
- Hero not dealt → `hero_not_dealt`.
- BB checks a limped pot with a hand outside the raise range → `ok` (default `CHECK`).
- Hero is an extra poster and checks → `ok`.

**Real data:** `check_preflop` on every hand of `session_2026-08-28.txt` returns a `DecisionCheck` without raising. Every hand where hero has a voluntary action has `actual_action` set.

**User prediction (not automated):** before running, the user writes down the expected `hero_pos`, `node`, `hand_class`, `expected_action`, `actual_action` and `status` for `hand_001`, `hand_002`, `hand_005` and `hand_024`, then compares. Mismatches become new golden tests.

### `test_report.py`
- `summarize` on a hand-built list of checks: status counts, adherence, by-spot rows and ordering, gap grouping.
- Zero assessed hands → adherence is `n/a`.

### `test_store.py` (additions)
- Round-trip: a saved `DecisionCheck` is loaded back equal.
- `replace_preflop_checks` twice: the row count equals the second batch, and `preflop_playbook_hash` returns the second hash.
- The `source_file` / `since` / `until` filters work through `v_preflop`.

### `test_cli.py` (additions)
- Happy path → 0, and the output contains `Adherence`.
- Invalid playbook → 1.
- Empty DB → 1.
- Unknown `--session` → 1.
- `check_preflop` monkeypatched to raise for one hand → 2, and that row has a reason starting with `error:`.

## Implementation order (full suite green after each step)
1. `expand_range` and `hand_class` with their tests.
2. Playbook parse, validation, `@rfi`, lookup and hash, with tests (fixture plus real playbook).
3. Positions with tests.
4. Node classification with tests.
5. `check_preflop` (expected/actual, statuses, sizing) with tests.
6. Store table, view and functions with tests.
7. `report.py` and the CLI `preflop` subcommand with tests.

## Cheap learning checks (for the user, after implementation)
- Change the free-check default from `CHECK` to `FOLD` and predict which tests fail before running.
- Set `size_tolerance_bb = 0` in the fixture and predict the new sizing deviations.
- Remove the BTN-on-button check in position assignment and predict which test catches it.

## Explicitly out of scope
- Any decision after hero's first voluntary action (that's the coach).
- Postflop analysis, metrics (bb/100, VPIP, ...), the LLM and the coach.
- Mixed frequencies, ranges that depend on the opener's size, stack-depth adjustments beyond the hero threshold.
- CSV export, incremental assessment, keeping history of earlier checks.

## Downstream contract (informational, no code here)
The coach will select hands with:
```sql
SELECT hand_id FROM v_preflop
WHERE status = 'deviation' OR actual_action NOT IN ('fold', 'check')
```
Before using `preflop_checks`, it will compare `preflop_playbook_hash(conn)` with the current playbook hash, and rerun `solver preflop` if they differ.

## Definition of done
- `solver preflop` on the ingested sample session prints the report and exits 0. Running it a second time gives an identical table, apart from `checked_at`.
- Editing a range in `data/playbook.md` and rerunning changes `playbook_hash` and the affected rows.
- All test suites are green, and the existing models, `pokerstars.py` and `ingest.py` are unchanged.
