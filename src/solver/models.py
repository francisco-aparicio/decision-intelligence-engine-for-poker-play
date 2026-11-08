from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


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
    # bets/calls: chips put in by this action; raises: the "to" total, not the increment
    amount: float | None = None
    all_in: bool = False


class StreetCards(BaseModel):
    street: Street
    board: tuple[str, ...]  # cumulative board as of end of this street


class Seat(BaseModel):
    seat_number: int
    player: str
    starting_stack: float
    # hero always; villains if revealed (preflop or summary)
    hole_cards: tuple[str, str] | None = None


class PotResult(BaseModel):
    """One seat's outcome from the summary: won, showed, or mucked.

    Not limited to real showdowns, since most hands end uncontested.
    """

    player: str
    hand_description: str | None = None
    amount_won: float = 0.0


class Hand(BaseModel):
    hand_id: str
    stakes: tuple[float, float]  # (small_blind, big_blind)
    currency: str
    timestamp_utc: datetime
    table_name: str
    table_size: int
    button_seat: int
    seats: list[Seat]
    hero_name: str
    actions: list[Action]
    board_by_street: list[StreetCards]
    pot_results: list[PotResult]
    total_pot: float
    rake: float


class FailedHand(BaseModel):
    raw_text: str
    error: str


class ParseResult(BaseModel):
    hands: list[Hand]
    failed: list[FailedHand]


class HandParseError(Exception):
    """Raised when a raw hand-text block fails to parse into a Hand."""

    def __init__(self, message: str, raw_text: str) -> None:
        super().__init__(message)
        self.raw_text = raw_text


class Position(str, Enum):
    UTG = "UTG"
    HJ = "HJ"
    CO = "CO"
    BTN = "BTN"
    SB = "SB"
    BB = "BB"


PREFLOP_ORDER = (
    Position.UTG,
    Position.HJ,
    Position.CO,
    Position.BTN,
    Position.SB,
    Position.BB,
)


class Node(str, Enum):
    RFI = "rfi"
    VS_LIMP = "vs_limp"
    VS_OPEN = "vs_open"
    VS_OPEN_CALLED = "vs_open_called"
    VS_RERAISE = "vs_reraise"
    VS_SHOVE = "vs_shove"
    HU_RFI = "hu_rfi"
    HU_VS_OPEN = "hu_vs_open"
    HU_VS_LIMP = "hu_vs_limp"


class Move(str, Enum):
    FOLD = "fold"
    CHECK = "check"
    LIMP = "limp"
    OVERLIMP = "overlimp"
    CALL = "call"
    RAISE = "raise"
    THREE_BET = "three_bet"


PASSIVE_MOVES = frozenset({Move.FOLD, Move.CHECK})


class CheckStatus(str, Enum):
    OK = "ok"
    DEVIATION = "deviation"
    NOT_COVERED = "not_covered"
    UNSUPPORTED = "unsupported"
    NO_DECISION = "no_decision"


class DeviationKind(str, Enum):
    TOO_LOOSE = "too_loose"
    TOO_TIGHT = "too_tight"
    WRONG_ACTION = "wrong_action"
    SIZING = "sizing"


class DecisionCheck(BaseModel):
    """Outcome of checking hero's first voluntary preflop action vs the playbook."""

    hand_id: str
    status: CheckStatus
    reason: str | None = None  # set for unsupported / no_decision / errors
    hero_pos: Position | None = None
    node: Node | None = None
    # vs_open / vs_open_called / vs_reraise (first raiser)
    opener_pos: Position | None = None
    n_limpers: int = 0
    n_callers: int = 0
    hand_class: str | None = None  # e.g. "K6s", "AKo", "TT"
    expected_action: Move | None = None
    actual_action: Move | None = None
    deviation_kind: DeviationKind | None = None
    facing_size_bb: float | None = None  # size of the raise relevant to the node
    actual_size_bb: float | None = None  # hero's raise-to, in bb
    expected_size_bb: float | None = None
    sizing_checked: bool = False


class SizingRules(BaseModel):
    """The playbook's `[sizing]` table. All sizes are absolute, in bb."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    standard_open_bb: float
    open_tolerance_bb: float
    size_tolerance_bb: float


class Limits(BaseModel):
    """The playbook's `[limits]` table."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    hero_min_stack_bb: float
    short_allin_max_bb: float
