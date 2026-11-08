"""Builders for synthetic hands."""

from datetime import UTC, datetime

from solver.models import Action, ActionType, Hand, Seat, Street

# Seat numbers 1-6, button on seat 4: the names double as position labels.
SIX_MAX = [(1, "UTG"), (2, "HJ"), (3, "CO"), (4, "BTN"), (5, "SB"), (6, "BB")]
SIX_MAX_BLINDS = ["SB sb", "BB bb"]

_VERBS = {
    "sb": ActionType.POST_SB,
    "bb": ActionType.POST_BB,
    "fold": ActionType.FOLD,
    "check": ActionType.CHECK,
    "call": ActionType.CALL,
    "bet": ActionType.BET,
    "raise": ActionType.RAISE,
}


def _action(text: str, stakes: tuple[float, float]) -> Action:
    """Parse "NAME VERB [BB_AMOUNT] [allin]", e.g. "BTN raise 3" or "CO raise 20 allin"."""
    player, verb, *rest = text.split()
    all_in = "allin" in rest
    amounts = [r for r in rest if r != "allin"]
    amount = float(amounts[0]) * stakes[1] if amounts else None
    if verb == "sb":
        amount = stakes[0]
    elif verb == "bb":
        amount = stakes[1]
    return Action(
        player=player,
        street=Street.PREFLOP,
        action=_VERBS[verb],
        amount=amount,
        all_in=all_in,
    )


def make_hand(
    actions: list[str],
    *,
    hero: str = "BTN",
    cards: tuple[str, str] | None = ("Ah", "Kd"),
    seats: list[tuple[int, str] | tuple[int, str, float]] = SIX_MAX,
    button: int = 4,
    stakes: tuple[float, float] = (0.01, 0.02),
    hand_id: str = "1",
    timestamp: datetime = datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
) -> Hand:
    """Build a valid `Hand` from compact inputs.

    Args:
        actions: Ordered preflop actions as "NAME VERB [BB_AMOUNT] [allin]".
            Verbs: sb, bb, fold, check, call, bet, raise. A raise amount is the
            raise-to total in bb. Blind posts ignore any amount.
        hero: Hero's name. A name not in `seats` means hero is not seated.
        cards: Hero's hole cards, or None for "not dealt".
        seats: (seat_number, name) or (seat_number, name, stack_bb); the default
            stack is 100bb.
        button: Button seat number.
        stakes: (small_blind, big_blind).
        timestamp: Hand timestamp; tz-aware UTC like the parser's.
    """
    return Hand(
        hand_id=hand_id,
        stakes=stakes,
        currency="EUR",
        timestamp_utc=timestamp,
        table_name="synthetic",
        table_size=6,
        button_seat=button,
        seats=[
            Seat(
                seat_number=seat[0],
                player=seat[1],
                starting_stack=(seat[2] if len(seat) == 3 else 100.0) * stakes[1],
                hole_cards=cards if seat[1] == hero else None,
            )
            for seat in seats
        ],
        hero_name=hero,
        actions=[_action(text, stakes) for text in actions],
        board_by_street=[],
        pot_results=[],
        total_pot=0.0,
        rake=0.0,
    )


def folds(*names: str) -> list[str]:
    return [f"{name} fold" for name in names]
