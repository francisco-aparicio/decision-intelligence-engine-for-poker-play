"""Check hero's first voluntary preflop action against the playbook.

Pure: no file or DB access, and bad poker data never raises. Anomalies become
`unsupported` or `no_decision` rows with a reason.
"""

from dataclasses import dataclass

from solver.models import (
    PASSIVE_MOVES,
    Action,
    ActionType,
    CheckStatus,
    DecisionCheck,
    DeviationKind,
    Hand,
    Limits,
    Move,
    Node,
    Position,
    Street,
)
from solver.playbook import Entry, Playbook, hand_class

_NON_BLIND_LABELS = (
    Position.BTN,
    Position.CO,
    Position.HJ,
    Position.UTG,
)  # from the end
_RAISE_MOVES = (Move.RAISE, Move.THREE_BET)
_OPEN_NODES = (Node.VS_OPEN, Node.VS_OPEN_CALLED, Node.HU_VS_OPEN)
_OPENER_NODES = (Node.VS_OPEN, Node.VS_OPEN_CALLED, Node.VS_RERAISE)


@dataclass(frozen=True)
class _Spot:
    """A classified decision point."""

    node: Node
    opener_pos: Position | None
    n_limpers: int
    n_callers: int
    facing_bb: float | None  # raise size relevant to the node
    open_bb: float | None  # first raise, gates 3-bet sizing checks
    shove_bb: float | None


def _preflop(hand: Hand) -> list[Action]:
    return [a for a in hand.actions if a.street is Street.PREFLOP]


def _is_raise(action: Action) -> bool:
    return action.action in (ActionType.RAISE, ActionType.BET)


def _bb(amount: float | None, big_blind: float) -> float | None:
    return None if amount is None else round(amount / big_blind, 2)


def _active_players(hand: Hand) -> list[str]:
    """Players with a preflop action, in clockwise order after the button."""
    seat_of = {seat.player: seat.seat_number for seat in hand.seats}
    acted = {a.player for a in _preflop(hand)}
    return sorted(
        (p for p in acted if p in seat_of),
        key=lambda p: (seat_of[p] <= hand.button_seat, seat_of[p]),
    )


def _assign_positions(hand: Hand, active: list[str]) -> dict[str, Position] | None:
    """Label active players, or None when the layout is ambiguous."""
    seat_of = {seat.player: seat.seat_number for seat in hand.seats}
    preflop = _preflop(hand)

    if len(active) == 2:
        on_button = [p for p in active if seat_of[p] == hand.button_seat]
        if not on_button:
            return None
        other = next(p for p in active if p != on_button[0])
        return {on_button[0]: Position.BTN, other: Position.BB}

    posted_bb = {a.player for a in preflop if a.action is ActionType.POST_BB}
    posted_sb = {a.player for a in preflop if a.action is ActionType.POST_SB}
    big_blind = next((p for p in active if p in posted_bb), None)
    if big_blind is None:
        return None

    bb_index = active.index(big_blind)
    positions = {big_blind: Position.BB}
    before_bb = active[bb_index - 1]
    if before_bb in posted_sb:
        positions[before_bb] = Position.SB
    non_blind = [
        p for p in active[bb_index + 1 :] + active[:bb_index] if p not in positions
    ]
    if len(non_blind) > len(_NON_BLIND_LABELS):
        return None
    for player, label in zip(reversed(non_blind), _NON_BLIND_LABELS, strict=False):
        positions[player] = label
    button_players = [p for p, pos in positions.items() if pos is Position.BTN]
    if not button_players or seat_of[button_players[0]] != hand.button_seat:
        return None
    return positions


def _hero_first_action(preflop: list[Action], hero: str) -> int | None:
    """Index of hero's first action that is not a blind post."""
    blind_posts = (ActionType.POST_SB, ActionType.POST_BB)
    return next(
        (
            i
            for i, a in enumerate(preflop)
            if a.player == hero and a.action not in blind_posts
        ),
        None,
    )


def _classify(
    prior: list[Action],
    positions: dict[str, Position],
    hero: str,
    limits: Limits,
    big_blind: float,
) -> _Spot | None:
    """Classify the spot from the actions before hero's first voluntary one.

    `prior` already excludes SB posts and the true BB's post.
    """
    raises = [a for a in prior if _is_raise(a)]
    first_raise = prior.index(raises[0]) if raises else len(prior)
    # An extra BB post is a limp; hero's own post is not.
    n_limpers = sum(
        1
        for i, a in enumerate(prior)
        if (a.action is ActionType.CALL and i < first_raise)
        or (a.action is ActionType.POST_BB and a.player != hero)
    )
    n_callers = sum(1 for a in prior[first_raise:] if a.action is ActionType.CALL)
    raise_bbs = [_bb(a.amount, big_blind) for a in raises]
    open_bb = raise_bbs[0] if raises else None
    last = raises[-1] if raises else None

    def spot(node: Node, **overrides: float | Position | None) -> _Spot:
        fields: dict[str, float | Position | int | None] = {
            "opener_pos": positions[raises[0].player]
            if raises and node in _OPENER_NODES
            else None,
            "n_limpers": n_limpers,
            "n_callers": n_callers,
            "facing_bb": None,
            "open_bb": open_bb,
            "shove_bb": None,
        }
        fields.update(overrides)
        return _Spot(node, **fields)  # type: ignore[arg-type]

    is_short_shove = (
        last is not None
        and last.all_in
        and (_bb(last.amount, big_blind) or 0) <= limits.short_allin_max_bb
    )

    if positions[hero] is Position.BTN and len(positions) == 2:
        return spot(Node.HU_RFI) if not prior else None
    if len(positions) == 2:  # hero is the heads-up BB
        if len(prior) != 1:
            return None
        only = prior[0]
        if is_short_shove:
            return spot(Node.VS_SHOVE, facing_bb=open_bb, shove_bb=open_bb)
        if _is_raise(only):
            return spot(Node.HU_VS_OPEN, facing_bb=open_bb)
        if only.action is ActionType.CALL:
            return spot(Node.HU_VS_LIMP)
        return None

    if is_short_shove:
        shove = raise_bbs[-1]
        return spot(Node.VS_SHOVE, facing_bb=shove, shove_bb=shove)
    if len(raises) >= 2:
        return spot(Node.VS_RERAISE, facing_bb=raise_bbs[-1])
    if len(raises) == 1:
        node = Node.VS_OPEN_CALLED if n_callers >= 1 else Node.VS_OPEN
        return spot(node, facing_bb=open_bb)
    if n_limpers >= 1:
        return spot(Node.VS_LIMP)
    return spot(Node.RFI)


_FIRST_IN = {
    ActionType.FOLD: Move.FOLD,
    ActionType.CHECK: Move.CHECK,
    ActionType.CALL: Move.LIMP,
    ActionType.RAISE: Move.RAISE,
    ActionType.BET: Move.RAISE,
}
_VS_LIMP = {**_FIRST_IN, ActionType.CALL: Move.OVERLIMP}
_VS_OPEN = {
    ActionType.FOLD: Move.FOLD,
    ActionType.CALL: Move.CALL,
    ActionType.RAISE: Move.THREE_BET,
    ActionType.BET: Move.THREE_BET,
}
_VS_RERAISE = {**_VS_OPEN, ActionType.RAISE: Move.RAISE, ActionType.BET: Move.RAISE}
_ACTUAL_MOVES = {
    Node.RFI: _FIRST_IN,
    Node.HU_RFI: _FIRST_IN,
    Node.VS_LIMP: _VS_LIMP,
    Node.HU_VS_LIMP: _VS_LIMP,
    Node.VS_OPEN: _VS_OPEN,
    Node.VS_OPEN_CALLED: _VS_OPEN,
    Node.HU_VS_OPEN: _VS_OPEN,
    Node.VS_RERAISE: _VS_RERAISE,
    Node.VS_SHOVE: _VS_RERAISE,
}


def _actual_move(node: Node, action: ActionType) -> Move | None:
    """Hero's action as a Move, or None for a combination that can't happen."""
    return _ACTUAL_MOVES[node].get(action)


def _expected_size(entry: Entry, spot: _Spot) -> float | None:
    node = spot.node
    if node in (Node.RFI, Node.HU_RFI):
        return entry.size_bb
    if node in (Node.VS_LIMP, Node.HU_VS_LIMP):
        if entry.iso_base_bb is None or entry.iso_per_limper_bb is None:
            return None
        return entry.iso_base_bb + entry.iso_per_limper_bb * spot.n_limpers
    if node in (Node.VS_OPEN, Node.HU_VS_OPEN):
        return entry.three_bet_bb
    if node is Node.VS_OPEN_CALLED:
        if entry.three_bet_bb is None or entry.per_caller_bb is None:
            return None
        return entry.three_bet_bb + entry.per_caller_bb * spot.n_callers
    return None


def _deviation_kind(expected: Move, actual: Move) -> DeviationKind | None:
    expected_passive = expected in PASSIVE_MOVES
    actual_passive = actual in PASSIVE_MOVES
    if expected_passive and not actual_passive:
        return DeviationKind.TOO_LOOSE
    if actual_passive and not expected_passive:
        return DeviationKind.TOO_TIGHT
    if not expected_passive and not actual_passive:
        return DeviationKind.WRONG_ACTION
    return None  # both passive but different, e.g. folding when a check was free


def check_preflop(hand: Hand, playbook: Playbook) -> DecisionCheck:
    """Check hero's first voluntary preflop decision. One result per hand."""
    hero = hand.hero_name
    big_blind = hand.stakes[1]
    hero_seat = next((s for s in hand.seats if s.player == hero), None)
    if hero_seat is None or hero_seat.hole_cards is None:
        return DecisionCheck(
            hand_id=hand.hand_id,
            status=CheckStatus.NO_DECISION,
            reason="hero_not_dealt",
        )
    cls = hand_class(hero_seat.hole_cards)

    def result(
        status: CheckStatus, reason: str | None = None, **known: object
    ) -> DecisionCheck:
        return DecisionCheck(
            hand_id=hand.hand_id,
            status=status,
            reason=reason,
            hand_class=cls,
            **known,  # type: ignore[arg-type]
        )

    positions = _assign_positions(hand, _active_players(hand))
    if positions is None:
        return result(CheckStatus.UNSUPPORTED, "position_ambiguous")

    preflop = _preflop(hand)
    index = _hero_first_action(preflop, hero)
    hero_pos = positions.get(hero)
    if index is None or hero_pos is None:
        return result(CheckStatus.NO_DECISION, "no_hero_action", hero_pos=hero_pos)

    if hero_seat.starting_stack / big_blind < playbook.limits.hero_min_stack_bb:
        return result(CheckStatus.UNSUPPORTED, "hero_short_stack", hero_pos=hero_pos)

    hero_action = preflop[index]
    true_bb = next(p for p, pos in positions.items() if pos is Position.BB)
    prior = [
        a
        for a in preflop[:index]
        if a.action is not ActionType.POST_SB
        and not (a.action is ActionType.POST_BB and a.player == true_bb)
    ]
    spot = _classify(prior, positions, hero, playbook.limits, big_blind)
    if spot is None:
        return result(CheckStatus.UNSUPPORTED, "unclassified", hero_pos=hero_pos)

    known = {
        "hero_pos": hero_pos,
        "node": spot.node,
        "opener_pos": spot.opener_pos,
        "n_limpers": spot.n_limpers,
        "n_callers": spot.n_callers,
        "facing_size_bb": spot.facing_bb,
        "actual_size_bb": _bb(hero_action.amount, big_blind)
        if _is_raise(hero_action)
        else None,
    }
    actual = _actual_move(spot.node, hero_action.action)
    if actual is None:
        return result(CheckStatus.UNSUPPORTED, "unexpected_action", **known)
    known["actual_action"] = actual

    entry = playbook.lookup(spot.node, hero_pos, spot.opener_pos, spot.shove_bb)
    if entry is None:
        return result(CheckStatus.NOT_COVERED, **known)

    can_check = not any(_is_raise(a) for a in prior) and any(
        a.action is ActionType.POST_BB and a.player == hero for a in preflop
    )
    expected = entry.expected(cls, Move.CHECK if can_check else Move.FOLD)
    known["expected_action"] = expected

    if expected != actual:
        kind = _deviation_kind(expected, actual)
        if kind is None:
            return result(CheckStatus.UNSUPPORTED, "unexpected_action", **known)
        return result(CheckStatus.DEVIATION, deviation_kind=kind, **known)

    if actual not in _RAISE_MOVES:
        return result(CheckStatus.OK, **known)

    expected_size = _expected_size(entry, spot)
    known["expected_size_bb"] = (
        None if expected_size is None else round(expected_size, 2)
    )
    gated_out = spot.node in _OPEN_NODES and (
        spot.open_bb is None
        or round(abs(spot.open_bb - playbook.sizing.standard_open_bb), 2)
        > playbook.sizing.open_tolerance_bb
    )
    if expected_size is None or gated_out:
        return result(CheckStatus.OK, **known)

    known["sizing_checked"] = True
    actual_size = known["actual_size_bb"]
    if (
        actual_size is not None
        and round(abs(actual_size - expected_size), 2)  # type: ignore[operator]
        > playbook.sizing.size_tolerance_bb
    ):
        return result(
            CheckStatus.DEVIATION, deviation_kind=DeviationKind.SIZING, **known
        )
    return result(CheckStatus.OK, **known)
