from datetime import UTC, datetime
from pathlib import Path

import pytest

from solver.models import (
    ActionType,
    Hand,
    HandParseError,
    ParseResult,
    PotResult,
    Street,
    StreetCards,
)
from solver.parser.pokerstars import (
    _parse_boards,
    parse_hand,
    parse_session,
    split_into_hands,
)

SAMPLE_HANDS_DIR = Path(__file__).parent.parent / "data" / "sample_hands"
SESSION_FILE = "session_2026-08-28.txt"
HERO_NAME = "osorio211"


def _read_sample(filename: str) -> str:
    return (SAMPLE_HANDS_DIR / filename).read_text(encoding="utf-8")


def _parse_hand_file(filename: str) -> Hand:
    raw_text = _read_sample(filename)
    return parse_hand(split_into_hands(raw_text)[0], hero_name=HERO_NAME)


def _postflop_actions(hand: Hand) -> list[tuple[Street, str, ActionType, float | None]]:
    return [
        (a.street, a.player, a.action, a.amount)
        for a in hand.actions
        if a.street != Street.PREFLOP
    ]


def _revealed_hole_cards(hand: Hand) -> dict[str, tuple[str, str]]:
    return {s.player: s.hole_cards for s in hand.seats if s.hole_cards is not None}


def test_parse_hand_001_preflop() -> None:
    hand = _parse_hand_file("hand_001.txt")

    assert hand.hand_id == "261900159976"
    assert hand.stakes == (0.01, 0.02)
    assert hand.currency == "EUR"
    assert hand.timestamp_utc == datetime(2026, 8, 28, 22, 45, 1, tzinfo=UTC)
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

    # Seats 1 and 6 are revealed later, in the summary (see the summary test).
    assert seats_by_number[5].hole_cards == ("Jc", "8h")
    for seat_number in (2, 3, 4):
        assert seats_by_number[seat_number].hole_cards is None

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
    preflop_actions = [a for a in hand.actions if a.street == Street.PREFLOP]
    assert len(preflop_actions) == len(expected_actions)
    for action, (player, action_type, amount) in zip(preflop_actions, expected_actions):
        assert action.player == player
        assert action.action == action_type
        assert action.amount == amount
        assert action.street == Street.PREFLOP
        assert action.all_in is False


def test_parse_hand_001_flop() -> None:
    hand = _parse_hand_file("hand_001.txt")

    assert hand.board_by_street == [
        StreetCards(street=Street.FLOP, board=("5c", "Ks", "4d")),
        StreetCards(street=Street.TURN, board=("5c", "Ks", "4d", "9d")),
        StreetCards(street=Street.RIVER, board=("5c", "Ks", "4d", "9d", "8s")),
    ]

    # (player, action, amount, all_in); raises carry the "to" total.
    expected_flop_actions = [
        ("Xicoazul87", ActionType.CHECK, None, False),
        ("dparentee", ActionType.BET, 0.07, False),
        ("gunariki", ActionType.RAISE, 0.28, False),
        ("Xicoazul87", ActionType.FOLD, None, False),
        ("dparentee", ActionType.RAISE, 0.76, True),
        ("gunariki", ActionType.CALL, 0.48, False),
    ]
    flop_actions = [a for a in hand.actions if a.street == Street.FLOP]
    assert len(flop_actions) == len(expected_flop_actions)
    for action, (player, action_type, amount, all_in) in zip(
        flop_actions, expected_flop_actions
    ):
        assert action.player == player
        assert action.action == action_type
        assert action.amount == amount
        assert action.all_in is all_in

    # All-in on the flop, so turn and river deal cards but have no actions.
    streets_in_order = [a.street for a in hand.actions]
    assert streets_in_order == sorted(streets_in_order, key=list(Street).index)
    assert len(hand.actions) == 8 + len(expected_flop_actions)


def test_parse_boards_hand_001_all_streets() -> None:
    raw_text = _read_sample("hand_001.txt")
    raw_hand = split_into_hands(raw_text)[0]

    boards = _parse_boards(raw_hand.splitlines())

    assert boards == [
        StreetCards(street=Street.FLOP, board=("5c", "Ks", "4d")),
        StreetCards(street=Street.TURN, board=("5c", "Ks", "4d", "9d")),
        StreetCards(street=Street.RIVER, board=("5c", "Ks", "4d", "9d", "8s")),
    ]


def test_parse_hand_001_summary() -> None:
    hand = _parse_hand_file("hand_001.txt")

    # Shown-won and shown-lost; the four folded seats have no entry.
    assert hand.pot_results == [
        PotResult(
            player="gunariki",
            hand_description="dois pares, Reis e Noves",
            amount_won=1.51,
        ),
        PotResult(
            player="dparentee",
            hand_description="dois pares, Reis e Oitos",
            amount_won=0.0,
        ),
    ]
    assert hand.total_pot == 1.59
    assert hand.rake == 0.08
    assert _revealed_hole_cards(hand) == {
        "osorio211": ("Jc", "8h"),
        "gunariki": ("Kh", "9c"),
        "dparentee": ("Kc", "8d"),
    }


def test_parse_hand_005_mucked_cards() -> None:
    hand = _parse_hand_file("hand_005.txt")

    # SHOW DOWN only says "esconde a mão"; the mucked cards are in the summary.
    assert hand.pot_results == [
        PotResult(
            player="RealHurley101",
            hand_description="dois pares, Cincos e Quatros",
            amount_won=0.55,
        ),
        PotResult(player="ValeraGiraff"),
    ]
    assert hand.total_pot == 0.58
    assert hand.rake == 0.03
    assert _revealed_hole_cards(hand) == {
        "osorio211": ("6d", "2c"),
        "RealHurley101": ("4s", "Ah"),
        "ValeraGiraff": ("Kh", "Jd"),
    }

    assert hand.board_by_street == [
        StreetCards(street=Street.FLOP, board=("4h", "5d", "3h")),
        StreetCards(street=Street.TURN, board=("4h", "5d", "3h", "5h")),
        StreetCards(street=Street.RIVER, board=("4h", "5d", "3h", "5h", "9s")),
    ]
    assert _postflop_actions(hand) == [
        (Street.FLOP, "RealHurley101", ActionType.CHECK, None),
        (Street.FLOP, "jffbarros", ActionType.FOLD, None),
        (Street.FLOP, "ValeraGiraff", ActionType.CHECK, None),
        (Street.TURN, "RealHurley101", ActionType.CHECK, None),
        (Street.TURN, "ValeraGiraff", ActionType.BET, 0.19),
        (Street.TURN, "RealHurley101", ActionType.CALL, 0.19),
        (Street.RIVER, "RealHurley101", ActionType.CHECK, None),
        (Street.RIVER, "ValeraGiraff", ActionType.CHECK, None),
    ]


def test_parse_hand_024_split_pot() -> None:
    hand = _parse_hand_file("hand_024.txt")

    assert hand.pot_results == [
        PotResult(
            player="micax82",
            hand_description="dois pares, Ases e Valetes",
            amount_won=1.19,
        ),
        PotResult(
            player="ValeraGiraff",
            hand_description="dois pares, Ases e Valetes",
            amount_won=1.19,
        ),
    ]
    assert hand.total_pot == 2.50
    assert hand.rake == 0.12
    assert _revealed_hole_cards(hand) == {
        "osorio211": ("2d", "Kd"),
        "micax82": ("3c", "Ah"),
        "ValeraGiraff": ("7d", "Ac"),
    }

    assert hand.board_by_street == [
        StreetCards(street=Street.FLOP, board=("As", "Js", "Jd")),
        StreetCards(street=Street.TURN, board=("As", "Js", "Jd", "4h")),
        StreetCards(street=Street.RIVER, board=("As", "Js", "Jd", "4h", "7s")),
    ]
    assert _postflop_actions(hand) == [
        (Street.FLOP, "ValeraGiraff", ActionType.BET, 0.17),
        (Street.FLOP, "micax82", ActionType.CALL, 0.17),
        (Street.TURN, "ValeraGiraff", ActionType.BET, 0.49),
        (Street.TURN, "micax82", ActionType.CALL, 0.49),
        (Street.RIVER, "ValeraGiraff", ActionType.BET, 0.50),
        (Street.RIVER, "micax82", ActionType.CALL, 0.50),
    ]


def test_parse_hand_002_uncontested_win() -> None:
    hand = _parse_hand_file("hand_002.txt")

    # Winner takes the pot without showing: amount only, no cards or description.
    # The trailing "não mostra a mão" line must not be read as an action.
    assert hand.pot_results == [PotResult(player="Fisgas", amount_won=0.17)]
    assert hand.total_pot == 0.18
    assert hand.rake == 0.01
    assert _revealed_hole_cards(hand) == {"osorio211": ("4d", "6s")}

    assert hand.board_by_street == [
        StreetCards(street=Street.FLOP, board=("3s", "7c", "5s")),
    ]
    assert _postflop_actions(hand) == [
        (Street.FLOP, "Fisgas", ActionType.BET, 0.13),
        (Street.FLOP, "dparentee", ActionType.FOLD, None),
    ]


def test_parse_session_batch() -> None:
    result = parse_session(_read_sample(SESSION_FILE), hero_name=HERO_NAME)

    assert len(result.hands) == 75
    assert result.failed == []
    assert len({hand.hand_id for hand in result.hands}) == 75


def test_parse_session_batch_invariants() -> None:
    result = parse_session(_read_sample(SESSION_FILE), hero_name=HERO_NAME)

    street_order = list(Street)
    for hand in result.hands:
        hero_seats = [seat for seat in hand.seats if seat.player == HERO_NAME]
        assert len(hero_seats) == 1, hand.hand_id
        assert hero_seats[0].hole_cards is not None, hand.hand_id

        # Everything won plus the rake accounts for the whole pot.
        won = sum(pot_result.amount_won for pot_result in hand.pot_results)
        assert won + hand.rake == pytest.approx(hand.total_pot, abs=0.005), hand.hand_id

        action_streets = [street_order.index(a.street) for a in hand.actions]
        assert action_streets == sorted(action_streets), hand.hand_id

        board_lengths = [len(cards.board) for cards in hand.board_by_street]
        assert board_lengths in ([], [3], [3, 4], [3, 4, 5]), hand.hand_id

        streets_with_board = {cards.street for cards in hand.board_by_street}
        postflop_streets = {a.street for a in hand.actions} - {Street.PREFLOP}
        assert postflop_streets <= streets_with_board, hand.hand_id


def test_parse_session_collects_failures() -> None:
    blocks = split_into_hands(_read_sample(SESSION_FILE))
    malformed = blocks[1].replace("desiste", "faz algo estranho", 1)
    assert malformed != blocks[1]

    raw_text = "\n".join([blocks[0], malformed, blocks[2]])
    result = parse_session(raw_text, hero_name=HERO_NAME)

    assert result.hands == [
        parse_hand(blocks[0], hero_name=HERO_NAME),
        parse_hand(blocks[2], hero_name=HERO_NAME),
    ]
    assert len(result.failed) == 1
    assert result.failed[0].raw_text == malformed
    assert "unrecognized action verb" in result.failed[0].error


def test_parse_session_no_hands() -> None:
    result = parse_session("nothing to see here\n", hero_name=HERO_NAME)

    assert result == ParseResult(hands=[], failed=[])


def test_side_pot_summary_fails_loudly() -> None:
    raw_hand = split_into_hands(_read_sample("hand_001.txt"))[0]
    # No real side-pot hand exists in the fixtures, so this pt wording is a guess.
    # What matters is that any total line off the plain shape is not read silently.
    side_pot_hand = raw_hand.replace(
        "Total pote 1.59 € | comissão 0.08 €",
        "Total pote 1.59 € Pote principal 1.00 €. Pote lateral 0.59 €. | comissão 0.08 €",
    )
    assert side_pot_hand != raw_hand

    with pytest.raises(HandParseError, match="no pot total line"):
        parse_hand(side_pot_hand, hero_name=HERO_NAME)

    result = parse_session(side_pot_hand, hero_name=HERO_NAME)
    assert result.hands == []
    assert [failed.raw_text for failed in result.failed] == [side_pot_hand]
