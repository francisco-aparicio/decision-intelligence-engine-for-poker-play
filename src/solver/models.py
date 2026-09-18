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
    amount: float | None = None  # for raises: the "to" total, not the increment
    all_in: bool = False


class StreetCards(BaseModel):
    street: Street
    board: tuple[str, ...]  # cumulative board as of end of this street


class Seat(BaseModel):
    seat_number: int
    player: str
    starting_stack: float
    hole_cards: tuple[str, str] | None = (
        None  # populated for hero always; villains only if revealed
    )


class ShowdownResult(BaseModel):
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
    showdown: list[ShowdownResult]
    total_pot: float
    rake: float
