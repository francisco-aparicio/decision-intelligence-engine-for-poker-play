from pathlib import Path

import pytest
from helpers import SIX_MAX, folds, make_hand

from solver import playbook, preflop
from solver.models import (
    ActionType,
    CheckStatus,
    DecisionCheck,
    DeviationKind,
    Hand,
    Move,
    Node,
    Position,
)
from solver.parser.pokerstars import parse_session

BLINDS = ["SB sb", "BB bb"]
ALL = ("UTG", "HJ", "CO", "BTN", "SB", "BB")

SAMPLE_SESSION = (
    Path(__file__).parent.parent / "data" / "sample_hands" / "session_2026-08-28.txt"
)

AK = ("Ah", "Kd")  # AKo
AKS = ("Ah", "Kh")
AA = ("Ah", "Ad")
JJ = ("Jh", "Jd")
TRASH = ("7h", "2d")  # 72o


def check(pb: playbook.Playbook, actions: list[str], **kwargs: object) -> DecisionCheck:
    return preflop.check_preflop(make_hand(actions, **kwargs), pb)  # type: ignore[arg-type]


def positions_of(hand: Hand) -> dict[str, Position] | None:
    return preflop._assign_positions(hand, preflop._active_players(hand))


# --- positions -------------------------------------------------------------------


def test_positions_six_handed():
    hand = make_hand(
        BLINDS + folds("UTG", "HJ", "CO") + ["BTN raise 3"] + folds("SB", "BB")
    )
    assert positions_of(hand) == {n: Position(n) for n in ALL}


def test_positions_five_handed_has_no_utg():
    seats = [(1, "HJ"), (2, "CO"), (3, "BTN"), (4, "SB"), (5, "BB")]
    hand = make_hand(
        BLINDS + folds("HJ", "CO", "BTN", "SB", "BB"), seats=seats, button=3
    )
    assert positions_of(hand) == {n: Position(n) for n in ALL[1:]}


def test_positions_four_handed():
    seats = [(1, "CO"), (2, "BTN"), (3, "SB"), (4, "BB")]
    hand = make_hand(BLINDS + folds("CO", "BTN", "SB", "BB"), seats=seats, button=2)
    assert positions_of(hand) == {n: Position(n) for n in ALL[2:]}


def test_positions_three_handed_is_btn_sb_bb():
    seats = [(1, "BTN"), (2, "SB"), (3, "BB")]
    hand = make_hand(BLINDS + folds("BTN", "SB", "BB"), seats=seats, button=1)
    assert positions_of(hand) == {n: Position(n) for n in ("BTN", "SB", "BB")}


def test_positions_with_non_contiguous_seats():
    seats = [(2, "SB"), (3, "BB"), (5, "UTG"), (6, "HJ"), (8, "CO"), (9, "BTN")]
    hand = make_hand(
        BLINDS + folds("UTG", "HJ", "CO", "BTN", "SB", "BB"), seats=seats, button=9
    )
    assert positions_of(hand) == {n: Position(n) for n in ALL}


def test_positions_when_button_wraps_past_the_last_seat():
    seats = [(1, "SB"), (2, "BB"), (3, "UTG"), (4, "HJ"), (5, "CO"), (6, "BTN")]
    hand = make_hand(
        BLINDS + folds("UTG", "HJ", "CO", "BTN", "SB", "BB"), seats=seats, button=6
    )
    assert positions_of(hand) == {n: Position(n) for n in ALL}


def test_positions_exclude_a_seated_player_with_no_actions():
    hand = make_hand(BLINDS + folds("HJ", "CO", "BTN", "SB", "BB"))  # UTG sits out
    positions = positions_of(hand)
    assert positions == {n: Position(n) for n in ALL[1:]}


def test_positions_heads_up_is_btn_and_bb():
    seats = [(1, "BTN"), (2, "BB")]
    hand = make_hand(
        ["BTN sb", "BB bb", "BTN raise 2.5", "BB fold"], seats=seats, button=1
    )
    assert positions_of(hand) == {"BTN": Position.BTN, "BB": Position.BB}


def test_positions_heads_up_without_a_player_on_the_button_is_ambiguous():
    seats = [(1, "BTN"), (2, "BB")]
    hand = make_hand(
        ["BTN sb", "BB bb", "BTN raise 2.5", "BB fold"], seats=seats, button=5
    )
    assert positions_of(hand) is None


def test_positions_extra_bb_poster_keeps_their_label():
    hand = make_hand(
        ["SB sb", "BB bb", "CO bb"] + folds("UTG", "HJ", "CO", "BTN", "SB", "BB")
    )
    assert positions_of(hand) == {n: Position(n) for n in ALL}


def test_positions_without_a_bb_post_are_ambiguous(min_playbook):
    result = check(min_playbook, ["SB sb"] + folds("UTG", "HJ", "CO", "BTN", "SB"))
    assert result.status is CheckStatus.UNSUPPORTED
    assert result.reason == "position_ambiguous"
    assert result.hand_class == "AKo"


def test_positions_where_btn_is_not_on_the_button_seat_are_ambiguous():
    hand = make_hand(BLINDS + folds("UTG", "HJ", "CO", "BTN", "SB", "BB"), button=3)
    assert positions_of(hand) is None


def test_positions_with_more_than_four_non_blind_players_are_ambiguous():
    seats = [(i, f"P{i}") for i in range(1, 8)]
    hand = make_hand(
        ["P6 sb", "P7 bb"] + folds(*(f"P{i}" for i in range(1, 8))),
        seats=seats,
        button=5,
        hero="P1",
    )
    assert positions_of(hand) is None


# --- node classification -----------------------------------------------------------


def test_node_rfi(min_playbook):
    result = check(
        min_playbook,
        BLINDS + ["UTG raise 3"] + folds("HJ", "CO", "BTN", "SB", "BB"),
        hero="UTG",
    )
    assert result.node is Node.RFI
    assert result.hero_pos is Position.UTG
    assert result.hand_class == "AKo"


def test_node_vs_limp_one_limper(min_playbook):
    result = check(
        min_playbook,
        BLINDS + folds("UTG", "HJ") + ["CO call", "BTN raise 5"] + folds("SB", "BB"),
    )
    assert result.node is Node.VS_LIMP
    assert result.n_limpers == 1
    assert result.status is CheckStatus.OK
    assert result.expected_size_bb == 5.0


def test_node_vs_limp_two_limpers(min_playbook):
    result = check(
        min_playbook,
        BLINDS
        + folds("UTG")
        + ["HJ call", "CO call", "BTN raise 6"]
        + folds("SB", "BB"),
    )
    assert result.node is Node.VS_LIMP
    assert result.n_limpers == 2
    assert result.expected_size_bb == 6.0


def test_node_vs_limp_counts_sb_completion_as_a_limper_for_bb(min_playbook):
    result = check(
        min_playbook,
        BLINDS + folds(*ALL[:4]) + ["SB call", "BB check"],
        hero="BB",
        cards=TRASH,
    )
    assert result.node is Node.VS_LIMP
    assert result.n_limpers == 1


def test_node_vs_limp_extra_bb_poster_counts_as_a_limper(min_playbook):
    result = check(
        min_playbook,
        ["SB sb", "BB bb", "CO bb"]
        + folds("UTG", "HJ")
        + ["CO check", "BTN raise 5"]
        + folds("SB", "BB"),
    )
    assert result.node is Node.VS_LIMP
    assert result.n_limpers == 1


def test_node_vs_open_records_the_opener(min_playbook):
    result = check(
        min_playbook,
        BLINDS + folds("UTG", "HJ") + ["CO raise 3", "BTN raise 9"] + folds("SB", "BB"),
        cards=("Qh", "Qd"),
    )
    assert result.node is Node.VS_OPEN
    assert result.opener_pos is Position.CO
    assert result.facing_size_bb == 3.0


def test_node_vs_open_called_counts_callers(min_playbook):
    result = check(
        min_playbook,
        BLINDS
        + ["UTG raise 3", "HJ call", "CO call", "BTN raise 15"]
        + folds("SB", "BB"),
        cards=AKS,
    )
    assert result.node is Node.VS_OPEN_CALLED
    assert result.n_callers == 2
    assert result.opener_pos is Position.UTG


def test_node_vs_reraise(min_playbook):
    result = check(
        min_playbook,
        BLINDS + ["UTG raise 3", "HJ raise 9", "CO raise 25"] + folds(*ALL[3:]),
        hero="CO",
        cards=AA,
    )
    assert result.node is Node.VS_RERAISE
    assert result.opener_pos is Position.UTG
    assert result.facing_size_bb == 9.0
    assert result.sizing_checked is False


def test_node_vs_shove_for_a_short_all_in(min_playbook):
    result = check(
        min_playbook,
        BLINDS + ["UTG raise 10 allin"] + folds("HJ", "CO") + ["BTN call"],
    )
    assert result.node is Node.VS_SHOVE
    assert result.facing_size_bb == 10.0
    assert result.opener_pos is None


def test_node_vs_open_for_a_deep_all_in_open(min_playbook):
    result = check(
        min_playbook,
        BLINDS + ["UTG raise 40 allin"] + folds("HJ", "CO") + ["BTN fold"],
    )
    assert result.node is Node.VS_OPEN
    assert result.facing_size_bb == 40.0


HU_SEATS = [(1, "BTN"), (2, "BB")]


def test_node_hu_rfi(min_playbook):
    result = check(
        min_playbook,
        ["BTN sb", "BB bb", "BTN raise 2.5", "BB fold"],
        seats=HU_SEATS,
        button=1,
    )
    assert result.node is Node.HU_RFI
    assert result.status is CheckStatus.OK


def test_node_hu_vs_open(min_playbook):
    result = check(
        min_playbook,
        ["BTN sb", "BB bb", "BTN raise 2.5", "BB raise 12", "BTN fold"],
        hero="BB",
        cards=AA,
        seats=HU_SEATS,
        button=1,
    )
    assert result.node is Node.HU_VS_OPEN
    assert result.hero_pos is Position.BB
    assert result.actual_action is Move.THREE_BET
    assert result.facing_size_bb == 2.5


def test_node_hu_vs_limp(min_playbook):
    result = check(
        min_playbook,
        ["BTN sb", "BB bb", "BTN call", "BB raise 4", "BTN fold"],
        hero="BB",
        cards=AA,
        seats=HU_SEATS,
        button=1,
    )
    assert result.node is Node.HU_VS_LIMP
    assert result.n_limpers == 1
    assert result.status is CheckStatus.OK


# --- statuses ----------------------------------------------------------------------


def rfi_utg(pb: playbook.Playbook, cards: tuple[str, str], move: str) -> DecisionCheck:
    return check(
        pb, BLINDS + [f"UTG {move}"] + folds("HJ", "CO", "BTN", "SB", "BB"),
        hero="UTG", cards=cards,
    )  # fmt: skip


def test_status_ok(min_playbook):
    result = rfi_utg(min_playbook, AK, "raise 3")
    assert result.status is CheckStatus.OK
    assert result.expected_action is Move.RAISE
    assert result.actual_action is Move.RAISE
    assert result.deviation_kind is None


def test_status_too_loose(min_playbook):
    result = rfi_utg(min_playbook, TRASH, "raise 3")
    assert result.status is CheckStatus.DEVIATION
    assert result.deviation_kind is DeviationKind.TOO_LOOSE
    assert result.expected_action is Move.FOLD


def test_status_too_tight(min_playbook):
    result = rfi_utg(min_playbook, AK, "fold")
    assert result.status is CheckStatus.DEVIATION
    assert result.deviation_kind is DeviationKind.TOO_TIGHT
    assert result.expected_action is Move.RAISE
    assert result.actual_action is Move.FOLD


def test_status_wrong_action(min_playbook):
    result = check(
        min_playbook,
        BLINDS + folds("UTG", "HJ") + ["CO raise 3", "BTN raise 9"] + folds("SB", "BB"),
        cards=JJ,  # the playbook calls JJ here
    )
    assert result.deviation_kind is DeviationKind.WRONG_ACTION
    assert result.expected_action is Move.CALL
    assert result.actual_action is Move.THREE_BET


def test_status_rfi_sizing_deviation(min_playbook):
    result = rfi_utg(min_playbook, AK, "raise 5")
    assert result.status is CheckStatus.DEVIATION
    assert result.deviation_kind is DeviationKind.SIZING
    assert result.expected_size_bb == 3.0
    assert result.actual_size_bb == 5.0
    assert result.sizing_checked is True


def test_status_rfi_sizing_within_tolerance_is_ok(min_playbook):
    result = rfi_utg(min_playbook, AK, "raise 4")
    assert result.status is CheckStatus.OK
    assert result.sizing_checked is True


def test_status_three_bet_facing_a_2bb_open_skips_the_sizing_check(min_playbook):
    result = check(
        min_playbook,
        BLINDS + folds(*ALL[:3]) + ["BTN raise 2", "SB fold", "BB raise 30"],
        hero="BB",
        cards=("Th", "Td"),
    )
    assert result.node is Node.VS_OPEN
    assert result.status is CheckStatus.OK
    assert result.sizing_checked is False
    assert result.facing_size_bb == 2.0
    assert result.actual_size_bb == 30.0


def test_status_three_bet_facing_a_standard_open_is_size_checked(min_playbook):
    result = check(
        min_playbook,
        BLINDS + folds(*ALL[:3]) + ["BTN raise 3", "SB fold", "BB raise 30"],
        hero="BB",
        cards=("Th", "Td"),
    )
    assert result.deviation_kind is DeviationKind.SIZING
    assert result.expected_size_bb == 12.0


def test_status_vs_open_called_expected_size_includes_per_caller_bb(min_playbook):
    actions = BLINDS + ["UTG raise 3", "HJ call", "CO call"]
    ok = check(min_playbook, actions + ["BTN raise 15"] + folds("SB", "BB"), cards=AKS)
    short = check(
        min_playbook, actions + ["BTN raise 9"] + folds("SB", "BB"), cards=AKS
    )
    assert ok.expected_size_bb == 15.0
    assert ok.status is CheckStatus.OK
    assert short.deviation_kind is DeviationKind.SIZING


def test_status_not_covered(min_playbook):
    result = check(
        min_playbook,
        BLINDS + ["UTG fold", "HJ raise 3", "CO call"] + folds("BTN", "SB", "BB"),
        hero="CO",
    )
    assert result.status is CheckStatus.NOT_COVERED
    assert result.node is Node.VS_OPEN
    assert result.opener_pos is Position.HJ
    assert result.hero_pos is Position.CO
    assert result.hand_class == "AKo"
    assert result.actual_action is Move.CALL


def test_status_hero_short_stack(min_playbook):
    seats = [(s, n, 20.0) if n == "BTN" else (s, n) for s, n in SIX_MAX]
    result = check(
        min_playbook,
        BLINDS + folds("UTG", "HJ", "CO") + ["BTN raise 3"] + folds("SB", "BB"),
        seats=seats,
    )
    assert result.status is CheckStatus.UNSUPPORTED
    assert result.reason == "hero_short_stack"
    assert result.hero_pos is Position.BTN


def test_status_walk_is_no_hero_action(min_playbook):
    result = check(
        min_playbook,
        BLINDS + folds("UTG", "HJ", "CO", "BTN", "SB"),
        hero="BB",
    )
    assert result.status is CheckStatus.NO_DECISION
    assert result.reason == "no_hero_action"
    assert result.hero_pos is Position.BB
    assert result.hand_class == "AKo"


def test_status_hero_not_dealt_without_cards(min_playbook):
    result = check(min_playbook, BLINDS + folds(*ALL[:5]), cards=None)
    assert result.status is CheckStatus.NO_DECISION
    assert result.reason == "hero_not_dealt"


def test_status_hero_not_dealt_without_a_seat(min_playbook):
    result = check(min_playbook, BLINDS + folds(*ALL[:5]), hero="nobody")
    assert result.reason == "hero_not_dealt"


def test_bb_checking_a_limped_pot_with_a_weak_hand_is_ok(min_playbook):
    result = check(
        min_playbook,
        BLINDS + ["UTG call"] + folds("HJ", "CO", "BTN", "SB") + ["BB check"],
        hero="BB",
        cards=TRASH,
    )
    assert result.status is CheckStatus.OK
    assert result.expected_action is Move.CHECK
    assert result.actual_action is Move.CHECK


def test_extra_bb_poster_checking_is_ok(min_playbook):
    result = check(
        min_playbook,
        ["SB sb", "BB bb", "CO bb"]
        + folds("UTG", "HJ")
        + ["CO check"]
        + folds("BTN", "SB")
        + ["BB check"],
        hero="CO",
        cards=TRASH,
    )
    assert result.status is CheckStatus.OK
    assert result.hero_pos is Position.CO
    assert result.n_limpers == 0  # hero's own post is not a limper
    assert result.expected_action is Move.CHECK


def test_folding_when_a_check_was_free_is_unsupported_not_guessed(min_playbook):
    result = check(
        min_playbook,
        BLINDS + ["UTG call"] + folds("HJ", "CO", "BTN", "SB", "BB"),
        hero="BB",
        cards=TRASH,
    )
    assert result.status is CheckStatus.UNSUPPORTED
    assert result.reason == "unexpected_action"
    assert result.expected_action is Move.CHECK
    assert result.actual_action is Move.FOLD


# --- helpers -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("node", "action", "expected"),
    [
        (Node.RFI, ActionType.CALL, Move.LIMP),
        (Node.HU_RFI, ActionType.BET, Move.RAISE),
        (Node.VS_LIMP, ActionType.CALL, Move.OVERLIMP),
        (Node.HU_VS_LIMP, ActionType.CHECK, Move.CHECK),
        (Node.VS_OPEN, ActionType.RAISE, Move.THREE_BET),
        (Node.VS_OPEN_CALLED, ActionType.CALL, Move.CALL),
        (Node.HU_VS_OPEN, ActionType.RAISE, Move.THREE_BET),
        (Node.VS_RERAISE, ActionType.RAISE, Move.RAISE),
        (Node.VS_SHOVE, ActionType.FOLD, Move.FOLD),
        (Node.VS_OPEN, ActionType.CHECK, None),
        (Node.VS_SHOVE, ActionType.CHECK, None),
        (Node.RFI, ActionType.POST_BB, None),
    ],
)
def test_actual_move(node, action, expected):
    assert preflop._actual_move(node, action) is expected


# --- real data ---------------------------------------------------------------------


def test_real_session_never_raises_and_voluntary_actions_have_a_move(min_playbook):
    raw = SAMPLE_SESSION.read_text(encoding="utf-8-sig")
    hands = parse_session(raw, "osorio211").hands
    assert len(hands) == 75
    for hand in hands:
        result = preflop.check_preflop(hand, min_playbook)
        assert result.hand_id == hand.hand_id
        voluntary = any(
            a.player == hand.hero_name
            and a.action not in (ActionType.POST_SB, ActionType.POST_BB)
            for a in hand.actions
        )
        if voluntary:
            assert result.actual_action is not None, hand.hand_id
