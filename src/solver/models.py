from datetime import datetime
from enum import Enum

from pydantic import BaseModel


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
