# PokerStars Hand History Parser — Implementation Spec

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
├── models.py                  # the model above
└── parser/
    ├── __init__.py
    └── pokerstars.py          # everything below

tests/
└── test_pokerstars_parser.py

data/sample_hands/
├── hand_001.txt                    # single hand, hand #261900159976 — golden test fixture
├── hand_002.txt                    # session hand #2 — uncontested win ("recebeu (...)")
├── hand_005.txt                    # session hand #5 — mucked cards ("escondeu as cartas")
├── hand_024.txt                    # session hand #24 — split pot (two "ganhou")
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