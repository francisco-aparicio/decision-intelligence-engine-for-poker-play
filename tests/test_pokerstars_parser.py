from pathlib import Path
from datetime import UTC, datetime

from solver.models import ActionType, Street
from solver.parser.pokerstars import parse_hand, split_into_hands

HAND_001_PATH = Path(__file__).parent.parent / "data" / "sample_hands" / "hand_001.txt"
HERO_NAME = "osorio211"


def test_parse_hand_001_preflop() -> None:
    raw_text = HAND_001_PATH.read_text(encoding="utf-8")
    raw_hand = split_into_hands(raw_text)[0]

    hand = parse_hand(raw_hand, hero_name=HERO_NAME)

    assert hand.hand_id == "261900159976"
    assert hand.stakes == (0.01, 0.02)
    assert hand.currency == "EUR"
    assert hand.timestamp_utc == datetime(2026, 8, 28, 22, 45, 1).replace(tzinfo=UTC)
    assert hand.table_name == "Vicia V"
    assert hand.table_size == 6
    assert hand.button_seat == 2

    seats_by_number = {seat.seat_number: seat for seat in hand.seats}
    assert set(seats_by_number) == {1, 2, 3, 4, 5, 6}
    assert seats_by_number[1].player == "gunariki"
    assert seats_by_number[1].starting_stack == 1.50
    assert seats_by_number[2].player == "Fisgas"
    assert seats_by_number[2].starting_stack == 4.16
    assert seats_by_number[3].player == "Armas1989"
    assert seats_by_number[3].starting_stack == 0.78
    assert seats_by_number[4].player == "Xicoazul87"
    assert seats_by_number[4].starting_stack == 2.15
    assert seats_by_number[5].player == "osorio211"
    assert seats_by_number[5].starting_stack == 2.25
    assert seats_by_number[6].player == "dparentee"
    assert seats_by_number[6].starting_stack == 0.78

    assert seats_by_number[5].hole_cards == ("Jc", "8h")
    for seat_number, seat in seats_by_number.items():
        if seat_number != 5:
            assert seat.hole_cards is None

    assert hand.hero_name == HERO_NAME

    expected_actions = [
        ("Armas1989", ActionType.POST_SB, 0.01),
        ("Xicoazul87", ActionType.POST_BB, 0.02),
        ("osorio211", ActionType.FOLD, None),
        ("dparentee", ActionType.CALL, 0.02),
        ("gunariki", ActionType.CALL, 0.02),
        ("Fisgas", ActionType.FOLD, None),
        ("Armas1989", ActionType.FOLD, None),
        ("Xicoazul87", ActionType.CHECK, None),
    ]
    assert len(hand.actions) == len(expected_actions)
    for action, (player, action_type, amount) in zip(hand.actions, expected_actions):
        assert action.player == player
        assert action.action == action_type
        assert action.amount == amount
        assert action.street == Street.PREFLOP
        assert action.all_in is False