# PokerStars Hand History Parser — Implementation Spec

## Goal
Parse Portuguese-localized PokerStars (.pt) hand history text — delivered as
the plain-text body of a "hand history request" email — into validated
`Hand` pydantic objects.

## Scope
Full single-hand parsing (all streets + showdown + summary). **Implement and
test incrementally**, not all at once:
1. Preflop only (seats, hero cards, preflop actions) — get the golden test
   green first.
2. Extend one street at a time (flop → turn → river), re-running the golden
   test after each.
3. Showdown + summary last.

## Inputs
- Raw text of one email body. May contain 1–N hands.
- `hero_name: str` — the real PokerStars username the export belongs to.
  **Never hardcode a literal `"Hero"`** — in the current fixture, hero is
  `osorio211`.

## Model (already finalized — do not modify without discussion)

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
    hole_cards: tuple[str, str] | None = None   # populated for hero always; villains only if revealed

class ShowdownResult(BaseModel):
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
    showdown: list[ShowdownResult]
    total_pot: float
    rake: float
```

## File layout

```
src/solver/
├── __init__.py
├── models.py                  # the model above
└── parser/
    ├── __init__.py
    └── pokerstars.py          # everything below

tests/
└── test_pokerstars_parser.py

data/sample_hands/
├── hand_001.txt                    # single hand, hand #261900159976 — golden test fixture
└── session_2026-08-28.txt          # full 75-hand export — batch test fixture
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

class FailedHand(BaseModel):
    raw_text: str
    error: str

class ParseResult(BaseModel):
    hands: list[Hand]
    failed: list[FailedHand]

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
- `_parse_seats(lines) -> list[Seat]` — the "Lugar N: player (stack em
  fichas)" block, before blind posts
- `_parse_blind_posts(lines) -> list[Action]` — "X: é small/big blind Y €"
  (street=PREFLOP)
- `_split_by_street(lines) -> dict[Street, list[str]]` — split the hand body
  on the `*** X ***` markers
- `_parse_street_actions(lines, street) -> list[Action]`
- `_parse_board(street_marker_line) -> tuple[str, ...]` — extract cards from
  e.g. `*** FLOP *** [5c Ks 4d]`
- `_parse_showdown(lines) -> list[ShowdownResult]`
- `_parse_summary(lines) -> tuple[float, float]` — (total_pot, rake)

## Noise lines to filter
Confirmed present in the real fixture — filter before street-splitting and
action-parsing, since none of these are player decisions:

- `junta-se à mesa no lugar #N` — player joins mid-hand
- `abandona a mesa` — player leaves mid-hand
- `está sem ligação` — player disconnected
- `gastou o tempo` — player used time bank
- `poderá jogar depois do botão` — late entrant, will play after the button

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

## Test plan (write incrementally, matching implementation order)
1. `test_parse_hand_001_preflop` — hand_id, stakes, all 6 seats with correct
   stacks, hero's hole_cards via `seats`, full preflop action sequence.
2. Extend to `test_parse_hand_001_full` — board_by_street, showdown,
   total_pot, rake, once all streets are implemented.
3. `test_parse_session_batch` — `parse_session()` on the full 75-hand file
   returns `len(result.hands) == 75` and `len(result.failed) == 0`.

## Explicitly out of scope for this module
- Session/table reconstruction (join/leave tracking) — noise lines are
  discarded, not modeled.
- Any non-PokerStars-.pt format.
- Any statistics, leak-detection, or LLM-analysis logic — this module's
  only job is raw text → validated `Hand` objects.