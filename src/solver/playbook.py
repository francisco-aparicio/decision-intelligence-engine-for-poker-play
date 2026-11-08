"""Playbook: range expansion, hand classes, parsing, validation and lookup."""

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from solver.models import (
    PREFLOP_ORDER,
    Limits,
    Move,
    Node,
    Position,
    SizingRules,
)

DEFAULT_PLAYBOOK_PATH = Path("data/playbook.md")

RANKS = "AKQJT98765432"

_RANK = f"[{RANKS}]"
_PAIR_RE = re.compile(rf"^({_RANK})\1(\+?)$")
_PAIR_DASH_RE = re.compile(rf"^({_RANK})\1-({_RANK})\2$")
_HAND_RE = re.compile(rf"^({_RANK})({_RANK})([so]?)(\+?)$")
_HAND_DASH_RE = re.compile(rf"^({_RANK})({_RANK})([so])-\1({_RANK})\3$")


class PlaybookError(Exception):
    """Invalid playbook. Message locates the problem (block, node, entry, token)."""


def _rank_index(rank: str) -> int:
    return RANKS.index(rank)


def _suffixes(suffix: str) -> tuple[str, ...]:
    return (suffix,) if suffix else ("s", "o")


def expand_range(text: str) -> frozenset[str]:
    """Expand a comma-separated range string into its hand classes.

    Raises:
        PlaybookError: On any token outside the range grammar.
    """
    classes: set[str] = set()
    for token in "".join(text.split()).split(","):
        classes |= _expand_token(token)
    return frozenset(classes)


def _expand_token(token: str) -> set[str]:
    if match := _PAIR_RE.match(token):
        low = _rank_index(match[1])
        stop = 0 if match[2] else low
        return {RANKS[i] * 2 for i in range(stop, low + 1)}

    if match := _PAIR_DASH_RE.match(token):
        high, low = _rank_index(match[1]), _rank_index(match[2])
        if high > low:
            raise PlaybookError(f"range {token!r}: write pair ranges high first")
        return {RANKS[i] * 2 for i in range(high, low + 1)}

    if match := _HAND_RE.match(token):
        high, kicker = _rank_index(match[1]), _rank_index(match[2])
        if high >= kicker:
            raise PlaybookError(f"range {token!r}: high card must come first")
        if match[4] and not match[3]:
            raise PlaybookError(f"range {token!r}: '+' needs an s/o suffix")
        stop = high + 1 if match[4] else kicker
        return {
            f"{RANKS[high]}{RANKS[i]}{suffix}"
            for i in range(stop, kicker + 1)
            for suffix in _suffixes(match[3])
        }

    if match := _HAND_DASH_RE.match(token):
        high = _rank_index(match[1])
        top, bottom = _rank_index(match[2]), _rank_index(match[4])
        if not high < top <= bottom:
            raise PlaybookError(f"range {token!r}: write kicker ranges high first")
        return {f"{RANKS[high]}{RANKS[i]}{match[3]}" for i in range(top, bottom + 1)}

    raise PlaybookError(f"invalid range token {token!r}")


def hand_class(cards: tuple[str, str]) -> str:
    """Map two cards like ("Kh", "6d") to a hand class like "K6o"."""
    (rank_a, suit_a), (rank_b, suit_b) = cards
    if rank_a == rank_b:
        return rank_a + rank_b
    high, low = sorted((rank_a, rank_b), key=_rank_index)
    return f"{high}{low}{'s' if suit_a == suit_b else 'o'}"


_TOML_BLOCK_RE = re.compile(
    r"^```toml[ \t]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL
)

_RFI_REF = "@rfi"

# TOML action key -> Move
_ACTION_MOVES = {
    "raise": Move.RAISE,
    "limp": Move.LIMP,
    "overlimp": Move.OVERLIMP,
    "call": Move.CALL,
    "three_bet": Move.THREE_BET,
}
_SIZE_KEYS = (
    "size_bb",
    "iso_base_bb",
    "iso_per_limper_bb",
    "three_bet_bb",
    "per_caller_bb",
    "max_bb",
)


@dataclass(frozen=True)
class _NodeSpec:
    heroes: tuple[Position, ...] | None  # None: the node has no `hero` key
    actions: tuple[str, ...]
    required_sizes: tuple[str, ...] = ()
    optional_sizes: tuple[str, ...] = ()
    needs_opener: bool = False


_NOT_UTG = PREFLOP_ORDER[1:]

_NODE_SPECS = {
    Node.RFI: _NodeSpec(PREFLOP_ORDER[:5], ("raise", "limp"), ("size_bb",)),
    Node.VS_LIMP: _NodeSpec(
        PREFLOP_ORDER, ("raise", "overlimp"), ("iso_base_bb", "iso_per_limper_bb")
    ),
    Node.VS_OPEN: _NodeSpec(
        _NOT_UTG, ("three_bet", "call"), ("three_bet_bb",), needs_opener=True
    ),
    Node.VS_OPEN_CALLED: _NodeSpec(
        _NOT_UTG, ("three_bet", "call"), ("three_bet_bb", "per_caller_bb")
    ),
    Node.VS_RERAISE: _NodeSpec(PREFLOP_ORDER, ("raise", "call")),
    Node.VS_SHOVE: _NodeSpec(None, ("call",), ("max_bb",)),
    Node.HU_RFI: _NodeSpec((Position.BTN,), ("raise", "limp"), ("size_bb",)),
    Node.HU_VS_OPEN: _NodeSpec(
        (Position.BB,), ("three_bet", "call"), ("three_bet_bb",)
    ),
    Node.HU_VS_LIMP: _NodeSpec(
        (Position.BB,), ("raise",), ("iso_base_bb",), ("iso_per_limper_bb",)
    ),
}


class _RawEntry(BaseModel):
    """One `[[node]]` table as written. Per-node key rules are checked separately."""

    model_config = ConfigDict(extra="forbid", strict=True)

    hero: str | list[str] | None = None
    opener: str | list[str] | None = None
    raise_: str | None = Field(default=None, alias="raise")
    limp: str | None = None
    overlimp: str | None = None
    call: str | None = None
    three_bet: str | None = None
    size_bb: float | None = None
    iso_base_bb: float | None = None
    iso_per_limper_bb: float | None = None
    three_bet_bb: float | None = None
    per_caller_bb: float | None = None
    max_bb: float | None = None


@dataclass(frozen=True)
class Entry:
    """One resolved (node, hero, opener) combination."""

    node: Node
    actions: dict[Move, frozenset[str]]  # `@rfi` already resolved
    size_bb: float | None = None
    iso_base_bb: float | None = None
    iso_per_limper_bb: float | None = None
    three_bet_bb: float | None = None
    per_caller_bb: float | None = None
    max_bb: float | None = None  # vs_shove only

    def expected(self, hand_class: str, default: Move) -> Move:
        """Move the playbook prescribes for `hand_class`, else `default`."""
        for move, classes in self.actions.items():
            if hand_class in classes:
                return move
        return default


_EntryKey = tuple[Node, Position | None, Position | None]


@dataclass(frozen=True)
class Playbook:
    sizing: SizingRules
    limits: Limits
    hash: str
    _entries: dict[_EntryKey, Entry] = field(repr=False)
    _shoves: tuple[Entry, ...] = field(repr=False)  # ascending max_bb

    def lookup(
        self,
        node: Node,
        hero: Position | None,
        opener: Position | None = None,
        shove_bb: float | None = None,
    ) -> Entry | None:
        if node is Node.VS_SHOVE:
            if shove_bb is None:
                return None
            return next(
                (
                    e
                    for e in self._shoves
                    if e.max_bb is not None and e.max_bb >= shove_bb
                ),
                None,
            )
        if hero is None:
            return None
        # Only vs_open is keyed by opener; other nodes ignore it.
        key_opener = opener if node is Node.VS_OPEN else None
        return self._entries.get((node, hero, key_opener))


def load_playbook(path: Path | str = DEFAULT_PLAYBOOK_PATH) -> Playbook:
    return parse_playbook(Path(path).read_text(encoding="utf-8"))


@dataclass
class _Located:
    """A raw table with enough context to word an error."""

    node: Node
    block: int
    index: int  # 1-based within its node, across blocks
    raw: dict[str, object]

    @property
    def where(self) -> str:
        return f"block {self.block}, [[{self.node.value}]] entry {self.index}"


@dataclass
class _Validated:
    loc: _Located
    heroes: list[Position | None]
    openers: list[Position | None]
    ranges: dict[Move, str]  # raw range text, possibly "@rfi"
    sizes: dict[str, float]


def parse_playbook(markdown: str) -> Playbook:
    """Parse and validate the toml blocks of a playbook document.

    Raises:
        PlaybookError: On any syntax, schema or consistency problem.
    """
    sizing_raw, limits_raw, located = _collect_blocks(markdown)
    if sizing_raw is None:
        raise PlaybookError("missing required [sizing] table")
    if limits_raw is None:
        raise PlaybookError("missing required [limits] table")
    try:
        sizing = SizingRules.model_validate(sizing_raw)
    except ValidationError as exc:
        raise PlaybookError(f"[sizing]: {_describe(exc)}") from exc
    try:
        limits = Limits.model_validate(limits_raw)
    except ValidationError as exc:
        raise PlaybookError(f"[limits]: {_describe(exc)}") from exc

    entries = [_validate_entry(item, limits) for item in located]
    resolved, shoves = _resolve(entries)
    return Playbook(
        sizing=sizing,
        limits=limits,
        hash=_hash(sizing, limits, resolved, shoves),
        _entries=resolved,
        _shoves=shoves,
    )


def _describe(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc']) or 'value'}: {err['msg']}"
        for err in exc.errors()
    )


def _collect_blocks(
    markdown: str,
) -> tuple[dict[str, object] | None, dict[str, object] | None, list[_Located]]:
    tables: dict[str, dict[str, object]] = {}
    located: list[_Located] = []
    counts: dict[Node, int] = {}
    nodes = {n.value: n for n in Node}

    for number, match in enumerate(_TOML_BLOCK_RE.finditer(markdown), start=1):
        try:
            data = tomllib.loads(match[1])
        except tomllib.TOMLDecodeError as exc:
            raise PlaybookError(f"block {number}: TOML syntax error: {exc}") from exc
        for key, value in data.items():
            if key in ("sizing", "limits"):
                if not isinstance(value, dict):
                    raise PlaybookError(f"block {number}: [{key}] must be a table")
                if key in tables:
                    raise PlaybookError(f"block {number}: [{key}] defined twice")
                tables[key] = value
            elif key in nodes:
                node = nodes[key]
                if not (
                    isinstance(value, list) and all(isinstance(v, dict) for v in value)
                ):
                    raise PlaybookError(
                        f"block {number}: {key!r} must be an array of tables "
                        f"([[{key}]]), not [{key}]"
                    )
                for raw in value:
                    counts[node] = counts.get(node, 0) + 1
                    located.append(_Located(node, number, counts[node], raw))
            else:
                raise PlaybookError(f"block {number}: unknown top-level key {key!r}")
    return tables.get("sizing"), tables.get("limits"), located


def _as_list(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    return [value] if isinstance(value, str) else value


def _parse_positions(loc: _Located, key: str, values: list[str]) -> list[Position]:
    out = []
    for value in values:
        try:
            out.append(Position(value))
        except ValueError:
            raise PlaybookError(
                f"{loc.where}: invalid position {value!r} in {key!r}"
            ) from None
    return out


def _validate_entry(loc: _Located, limits: Limits) -> _Validated:
    spec = _NODE_SPECS[loc.node]
    try:
        raw = _RawEntry.model_validate(loc.raw)
    except ValidationError as exc:
        raise PlaybookError(f"{loc.where}: {_describe(exc)}") from exc

    given = set(loc.raw)
    allowed = {*spec.actions, *spec.required_sizes, *spec.optional_sizes}
    required = set(spec.required_sizes)
    if spec.heroes is not None:
        allowed.add("hero")
        required.add("hero")
    if spec.needs_opener:
        allowed.add("opener")
        required.add("opener")
    for key in sorted(given - allowed):
        raise PlaybookError(f"{loc.where}: key {key!r} not allowed in this node")
    for key in sorted(required - given):
        raise PlaybookError(f"{loc.where}: missing required key {key!r}")

    heroes: list[Position | None] = [None]
    if spec.heroes is not None:
        parsed = _parse_positions(loc, "hero", _as_list(raw.hero))
        for hero in parsed:
            if hero not in spec.heroes:
                raise PlaybookError(
                    f"{loc.where}: hero {hero.value!r} not allowed in this node"
                )
        heroes = list(parsed)
    openers: list[Position | None] = [None]
    if spec.needs_opener:
        parsed_openers = _parse_positions(loc, "opener", _as_list(raw.opener))
        for hero in parsed:
            for opener in parsed_openers:
                if PREFLOP_ORDER.index(opener) >= PREFLOP_ORDER.index(hero):
                    raise PlaybookError(
                        f"{loc.where}: opener {opener.value} does not precede "
                        f"hero {hero.value}"
                    )
        openers = list(parsed_openers)

    ranges = {
        _ACTION_MOVES[key]: text
        for key in spec.actions
        if (text := getattr(raw, "raise_" if key == "raise" else key)) is not None
    }
    sizes = {
        key: float(value)
        for key in _SIZE_KEYS
        if (value := getattr(raw, key)) is not None
    }
    if loc.node is Node.HU_VS_LIMP:
        sizes.setdefault("iso_per_limper_bb", 0.0)
    if loc.node is Node.VS_SHOVE and sizes["max_bb"] > limits.short_allin_max_bb:
        raise PlaybookError(
            f"{loc.where}: max_bb {sizes['max_bb']} exceeds "
            f"limits.short_allin_max_bb {limits.short_allin_max_bb}"
        )
    return _Validated(loc, heroes, openers, ranges, sizes)


def _expand(item: _Validated, move: Move, text: str) -> frozenset[str]:
    try:
        return expand_range(text)
    except PlaybookError as exc:
        raise PlaybookError(f"{item.loc.where}, {move.value!r}: {exc}") from exc


def _resolve(
    entries: list[_Validated],
) -> tuple[dict[_EntryKey, Entry], tuple[Entry, ...]]:
    # Literal ranges first; "@rfi" refers to a hero's literal rfi raise range.
    literal = [
        {
            move: _expand(item, move, text)
            for move, text in item.ranges.items()
            if text != _RFI_REF
        }
        for item in entries
    ]
    rfi_raise: dict[Position, frozenset[str]] = {}
    for item, ranges in zip(entries, literal, strict=True):
        if item.loc.node is Node.RFI and Move.RAISE in ranges:
            for hero in item.heroes:
                if hero is not None:
                    rfi_raise.setdefault(hero, ranges[Move.RAISE])

    resolved: dict[_EntryKey, Entry] = {}
    shoves: dict[float, Entry] = {}
    for item, ranges in zip(entries, literal, strict=True):
        for hero in item.heroes:
            actions = dict(ranges)
            for move, text in item.ranges.items():
                if text != _RFI_REF:
                    continue
                if hero not in rfi_raise:
                    raise PlaybookError(
                        f"{item.loc.where}, {move.value!r}: '@rfi' unresolvable "
                        f"for hero {hero.value if hero else None} "
                        f"(no rfi raise range)"
                    )
                actions[move] = rfi_raise[hero]
            _check_disjoint(item, hero, actions)
            entry = Entry(item.loc.node, actions, **item.sizes)
            if item.loc.node is Node.VS_SHOVE:
                max_bb = item.sizes["max_bb"]
                if max_bb in shoves:
                    raise PlaybookError(
                        f"{item.loc.where}: duplicate vs_shove max_bb {max_bb}"
                    )
                shoves[max_bb] = entry
                continue
            for opener in item.openers:
                key = (item.loc.node, hero, opener)
                if key in resolved:
                    raise PlaybookError(
                        f"{item.loc.where}: duplicate entry for node "
                        f"{key[0].value}, hero {hero.value if hero else None}, "
                        f"opener {opener.value if opener else None}"
                    )
                resolved[key] = entry
    return resolved, tuple(shoves[k] for k in sorted(shoves))


def _check_disjoint(
    item: _Validated, hero: Position | None, actions: dict[Move, frozenset[str]]
) -> None:
    moves = list(actions)
    for i, first in enumerate(moves):
        for second in moves[i + 1 :]:
            overlap = actions[first] & actions[second]
            if overlap:
                who = f" (hero {hero.value})" if hero else ""
                raise PlaybookError(
                    f"{item.loc.where}{who}: {first.value!r} and "
                    f"{second.value!r} overlap on {', '.join(sorted(overlap))}"
                )


def _hash(
    sizing: SizingRules,
    limits: Limits,
    resolved: dict[_EntryKey, Entry],
    shoves: tuple[Entry, ...],
) -> str:
    """First 12 hex of SHA-256 over the parsed playbook, never over the prose."""

    def dump(key: str, entry: Entry) -> dict[str, object]:
        return {
            "key": key,
            "actions": {m.value: sorted(c) for m, c in entry.actions.items()},
            "sizes": {k: getattr(entry, k) for k in _SIZE_KEYS},
        }

    entries = [
        dump(
            f"{node.value}|{hero.value if hero else ''}|{opener.value if opener else ''}",
            entry,
        )
        for (node, hero, opener), entry in resolved.items()
    ]
    entries += [dump(f"vs_shove|{entry.max_bb}", entry) for entry in shoves]
    entries.sort(key=lambda d: str(d["key"]))
    canonical = json.dumps(
        {
            "sizing": sizing.model_dump(),
            "limits": limits.model_dump(),
            "entries": entries,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]
