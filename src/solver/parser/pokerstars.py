"""Parser for Portuguese-localized PokerStars (.pt) hand histories."""

import re
from datetime import UTC, datetime
from itertools import pairwise

from solver.models import Action, ActionType, Hand, Seat, Street

_NOISE_PATTERNS = (
    "junta-se à mesa no lugar #",
    "abandona a mesa",
    "está sem ligação",
    "gastou o tempo",
    "poderá jogar depois do botão",
)

_HAND_BOUNDARY_RE = re.compile(r"^Mão #\d+ da PokerStars:")

_HEADER_RE = re.compile(
    r"^Mão #(?P<hand_id>\d+) da PokerStars:.*?"
    r"\((?P<sb>[\d.]+)\s*€/(?P<bb>[\d.]+)\s*€\s+(?P<currency>\w+)\)\s+-\s+"
    r"(?P<date>\d{4}/\d{2}/\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2})\s+UTC"
)

_TABLE_RE = re.compile(
    r"^Mesa '(?P<table_name>.+)' (?P<table_size>\d+)-max "
    r"Lugar #(?P<button_seat>\d+) é o botão"
)

_SEAT_RE = re.compile(
    r"^Lugar (?P<seat_number>\d+): (?P<player>.+?) \((?P<stack>[\d.]+)\s*€ em fichas\)"
)

_BLIND_RE = re.compile(
    r"^(?P<player>.+?): é (?P<kind>small|big) blind (?P<amount>[\d.]+)\s*€"
)

_HOLE_CARDS_RE = re.compile(r"^(?P<player>\S+) recebe \[(?P<c1>\w+) (?P<c2>\w+)\]")

_STREET_MARKER_RE = re.compile(r"^\*\*\* (?P<marker>[^*]+?) \*\*\*")

_MARKER_TO_STREET = {
    "CARTAS HOLE": Street.PREFLOP,
    "FLOP": Street.FLOP,
    "TURN": Street.TURN,
    "RIVER": Street.RIVER,
}

_ACTION_LINE_RE = re.compile(r"^(?P<player>.+?): (?P<verb>.+)$")
_AMOUNT_RE = re.compile(r"([\d.]+)\s*€")
_ALL_IN_SUFFIX = " e está all-in"
_NON_STREET_MARKERS = {"SHOW DOWN", "SUMÁRIO"}

class HandParseError(Exception):
    """Raised when a raw hand-text block fails to parse into a Hand."""

    def __init__(self, message: str, raw_text: str) -> None:
        super().__init__(message)
        self.raw_text = raw_text


def split_into_hands(raw_text: str) -> list[str]:
    """Split a raw multi-hand text blob into individual raw hand-text blocks.

    Boundary = start of each line matching r'^Mão #\\d+ da PokerStars:'
    — NOT the '*** # N ***' banner line, which may be absent.
    """
    lines = raw_text.splitlines()
    boundaries = [i for i, line in enumerate(lines) if _HAND_BOUNDARY_RE.match(line)]
    if not boundaries:
        return []
    boundaries.append(len(lines))
    return ["\n".join(lines[start:end]).strip() for start, end in pairwise(boundaries)]


def parse_hand(raw_hand_text: str, hero_name: str) -> Hand:
    """Parse one raw hand-text block into a validated Hand.

    Step 1: only preflop is parsed. Later streets, showdown, and summary
    are left at their empty/zero defaults.
    """
    try:
        lines = _filter_noise_lines(raw_hand_text.splitlines())

        header = _parse_header(lines[0])
        table = _parse_table_line(lines[1])
        blind_actions = _parse_blind_posts(lines)

        streets = _split_by_street(lines)
        preflop_lines = streets.get(Street.PREFLOP, [])

        hole_cards = _parse_hole_cards(preflop_lines)
        seats = _parse_seats(lines, hole_cards)

        preflop_actions = _parse_street_actions(preflop_lines, Street.PREFLOP)

        return Hand(
            hand_id=header["hand_id"],
            stakes=header["stakes"],
            currency=header["currency"],
            timestamp_utc=header["timestamp_utc"],
            table_name=table["table_name"],
            table_size=table["table_size"],
            button_seat=table["button_seat"],
            seats=seats,
            hero_name=hero_name,
            actions=blind_actions + preflop_actions,
            board_by_street=[],
            showdown=[],
            total_pot=0.0,
            rake=0.0,
        )
    except HandParseError:
        raise
    except Exception as exc:
        raise HandParseError(str(exc), raw_hand_text) from exc


def _filter_noise_lines(lines: list[str]) -> list[str]:
    """Strip lines that describe table events rather than player decisions."""
    return [
        line
        for line in lines
        if not any(pattern in line for pattern in _NOISE_PATTERNS)
    ]


def _parse_header(line: str) -> dict:
    match = _HEADER_RE.match(line)
    if not match:
        raise ValueError(f"unrecognized header line: {line!r}")
    timestamp = datetime.strptime(
        f"{match['date']} {match['time']}", "%Y/%m/%d %H:%M:%S"
    ).replace(tzinfo=UTC)
    return {
        "hand_id": match["hand_id"],
        "stakes": (float(match["sb"]), float(match["bb"])),
        "currency": match["currency"],
        "timestamp_utc": timestamp,
    }


def _parse_table_line(line: str) -> dict:
    match = _TABLE_RE.match(line)
    if not match:
        raise ValueError(f"unrecognized table line: {line!r}")
    return {
        "table_name": match["table_name"],
        "table_size": int(match["table_size"]),
        "button_seat": int(match["button_seat"]),
    }


def _parse_seats(
    lines: list[str], hole_cards: dict[str, tuple[str, str]]
) -> list[Seat]:
    seats = []
    for line in lines:
        match = _SEAT_RE.match(line)
        if match:
            seats.append(
                Seat(
                    seat_number=int(match["seat_number"]),
                    player=match["player"],
                    starting_stack=float(match["stack"]),
                    hole_cards=hole_cards.get(match["player"]),
                )
            )
    if not seats:
        raise ValueError("no seat lines found")
    return seats


def _parse_blind_posts(lines: list[str]) -> list[Action]:
    """Parse blind-post lines. May return more than one SB or BB (quirk: reentries)."""
    actions = []
    for line in lines:
        match = _BLIND_RE.match(line)
        if match:
            action_type = (
                ActionType.POST_SB if match["kind"] == "small" else ActionType.POST_BB
            )
            actions.append(
                Action(
                    player=match["player"],
                    street=Street.PREFLOP,
                    action=action_type,
                    amount=float(match["amount"]),
                )
            )
    return actions


def _parse_hole_cards(lines: list[str]) -> dict[str, tuple[str, str]]:
    hole_cards = {}
    for line in lines:
        match = _HOLE_CARDS_RE.match(line)
        if match:
            hole_cards[match["player"]] = (match["c1"], match["c2"])
    return hole_cards


def _split_by_street(lines: list[str]) -> dict[Street, list[str]]:
    streets: dict[Street, list[str]] = {}
    current_street: Street | None = None
    for line in lines:
        match = _STREET_MARKER_RE.match(line)
        if match:
            marker = match["marker"].strip()
            if marker in _MARKER_TO_STREET:
                current_street = _MARKER_TO_STREET[marker]
                streets.setdefault(current_street, [])
            elif marker in _NON_STREET_MARKERS:
                current_street = None
            else:
                raise ValueError(f"unrecognized section marker: {marker!r}")
            continue
        if current_street is not None:
            streets[current_street].append(line)
    if Street.PREFLOP not in streets:
        raise ValueError("no PREFLOP section found in hand body")
    return streets


def _parse_street_actions(lines: list[str], street: Street) -> list[Action]:
    if street != Street.PREFLOP:
        raise NotImplementedError(
            f"action parsing for street {street.value!r} is not implemented yet (Step 2)"
        )
    actions = []
    for line in lines:
        match = _ACTION_LINE_RE.match(line)
        if not match:
            continue
        actions.append(_parse_action_line(match["player"], match["verb"], street))
    return actions


def _parse_action_line(player: str, verb: str, street: Street) -> Action:
    all_in = verb.endswith(_ALL_IN_SUFFIX)
    if all_in:
        verb = verb[: -len(_ALL_IN_SUFFIX)]

    if verb == "desiste":
        return Action(
            player=player, street=street, action=ActionType.FOLD, all_in=all_in
        )
    if verb == "passa":
        return Action(
            player=player, street=street, action=ActionType.CHECK, all_in=all_in
        )
    if verb.startswith("iguala"):
        amount = float(_AMOUNT_RE.search(verb)[1])
        return Action(
            player=player,
            street=street,
            action=ActionType.CALL,
            amount=amount,
            all_in=all_in,
        )
    if verb.startswith("aposta"):
        amount = float(_AMOUNT_RE.search(verb)[1])
        return Action(
            player=player,
            street=street,
            action=ActionType.BET,
            amount=amount,
            all_in=all_in,
        )
    if verb.startswith("sobe"):
        amounts = _AMOUNT_RE.findall(verb)
        return Action(
            player=player,
            street=street,
            action=ActionType.RAISE,
            amount=float(amounts[-1]),
            all_in=all_in,
        )
    raise ValueError(f"unrecognized action verb: {verb!r}")
