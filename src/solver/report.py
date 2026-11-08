"""Summarize preflop checks and format the CLI report. Pure: no file or DB access."""

from collections import Counter
from dataclasses import dataclass

from solver.models import (
    CheckStatus,
    DecisionCheck,
    DeviationKind,
    Node,
    Position,
)

_KIND_ORDER = (
    DeviationKind.TOO_LOOSE,
    DeviationKind.TOO_TIGHT,
    DeviationKind.WRONG_ACTION,
    DeviationKind.SIZING,
)


@dataclass(frozen=True)
class SpotRow:
    """Assessed hands (ok + deviation) for one `node.hero_pos`."""

    spot: str
    n: int
    dev: int
    loose: int
    tight: int
    wrong: int
    sizing: int


@dataclass(frozen=True)
class Gap:
    node: Node | None
    hero_pos: Position | None
    opener_pos: Position | None
    count: int


@dataclass(frozen=True)
class PreflopSummary:
    total: int
    status_counts: dict[CheckStatus, int]
    kind_counts: dict[DeviationKind, int]
    spots: list[SpotRow]
    deviations: list[DecisionCheck]
    gaps: list[Gap]
    skipped: dict[str, int]  # unsupported / no_decision, by reason

    @property
    def ok(self) -> int:
        return self.status_counts[CheckStatus.OK]

    @property
    def assessed(self) -> int:
        return self.ok + self.status_counts[CheckStatus.DEVIATION]

    @property
    def adherence(self) -> float | None:
        return self.ok / self.assessed if self.assessed else None


def summarize(checks: list[DecisionCheck]) -> PreflopSummary:
    counts = Counter(c.status for c in checks)
    deviations = [c for c in checks if c.status is CheckStatus.DEVIATION]
    assessed = [
        c for c in checks if c.status in (CheckStatus.OK, CheckStatus.DEVIATION)
    ]

    by_spot: dict[str, list[DecisionCheck]] = {}
    for check in assessed:
        by_spot.setdefault(_spot_name(check), []).append(check)
    spots = [_spot_row(name, group) for name, group in by_spot.items()]
    spots.sort(key=lambda row: (-row.dev, -row.n, row.spot))

    gap_counts = Counter(
        (c.node, c.hero_pos, c.opener_pos)
        for c in checks
        if c.status is CheckStatus.NOT_COVERED
    )
    gaps = [Gap(*key, count) for key, count in gap_counts.items()]
    gaps.sort(key=lambda g: (-g.count, _gap_name(g)))

    skipped = Counter(
        c.reason or "unknown"
        for c in checks
        if c.status in (CheckStatus.UNSUPPORTED, CheckStatus.NO_DECISION)
    )
    return PreflopSummary(
        total=len(checks),
        status_counts={status: counts[status] for status in CheckStatus},
        kind_counts={
            kind: sum(1 for c in deviations if c.deviation_kind is kind)
            for kind in _KIND_ORDER
        },
        spots=spots,
        deviations=deviations,
        gaps=gaps,
        skipped=dict(sorted(skipped.items(), key=lambda kv: (-kv[1], kv[0]))),
    )


def _spot_name(check: DecisionCheck) -> str:
    node = check.node.value if check.node else "?"
    hero = check.hero_pos.value if check.hero_pos else "?"
    return f"{node}.{hero}"


def _spot_row(name: str, group: list[DecisionCheck]) -> SpotRow:
    def of_kind(kind: DeviationKind) -> int:
        return sum(1 for c in group if c.deviation_kind is kind)

    return SpotRow(
        spot=name,
        n=len(group),
        dev=sum(1 for c in group if c.status is CheckStatus.DEVIATION),
        loose=of_kind(DeviationKind.TOO_LOOSE),
        tight=of_kind(DeviationKind.TOO_TIGHT),
        wrong=of_kind(DeviationKind.WRONG_ACTION),
        sizing=of_kind(DeviationKind.SIZING),
    )


def _gap_name(gap: Gap) -> str:
    node = gap.node.value if gap.node else "?"
    hero = gap.hero_pos.value if gap.hero_pos else "?"
    opener = f" (opener {gap.opener_pos.value})" if gap.opener_pos else ""
    return f"{node}.{hero}{opener}"


def _move_text(move: str | None, size: float | None, with_size: bool) -> str:
    text = move or "-"
    return f"{text} {size:.1f}" if with_size and size is not None else text


def _deviation_line(check: DecisionCheck) -> str:
    sized = check.deviation_kind is DeviationKind.SIZING
    expected = _move_text(
        check.expected_action.value if check.expected_action else None,
        check.expected_size_bb,
        sized,
    )
    actual = _move_text(
        check.actual_action.value if check.actual_action else None,
        check.actual_size_bb,
        sized,
    )
    return (
        f"  {check.hand_id}  {check.hero_pos.value if check.hero_pos else '?':<3}  "
        f"{check.hand_class or '?':<3}  {check.node.value if check.node else '?':<15}  "
        f"{'expected ' + expected:<20}{'actual ' + actual:<18}"
        f"{check.deviation_kind.value if check.deviation_kind else ''}"
    )


def format_report(
    summary: PreflopSummary, *, scope: str, playbook_hash: str, db_path: str
) -> str:
    counts = summary.status_counts
    lines = [
        f"Preflop check — scope: {scope} | playbook {playbook_hash} | DB {db_path}",
        (
            f"Hands: {summary.total} | assessed {summary.assessed} | "
            f"no_decision {counts[CheckStatus.NO_DECISION]} | "
            f"not_covered {counts[CheckStatus.NOT_COVERED]} | "
            f"unsupported {counts[CheckStatus.UNSUPPORTED]}"
        ),
    ]
    if summary.adherence is None:
        lines.append("Adherence: n/a")
    else:
        kinds = " | ".join(
            f"{kind.value} {summary.kind_counts[kind]}" for kind in _KIND_ORDER
        )
        lines.append(
            f"Adherence: {summary.ok}/{summary.assessed} "
            f"({summary.adherence:.1%}) | {kinds}"
        )

    # Names like vs_open_called.BB outgrow the 16-column layout; widen to fit.
    width = max([16, *(len(row.spot) + 2 for row in summary.spots)])
    lines += ["", f"{'Spot':<{width}}{'n':>2}  dev  loose  tight  wrong  sizing"]
    lines += [
        f"{row.spot:<{width}}{row.n:>2}  {row.dev:>3}  {row.loose:>5}  {row.tight:>5}  "
        f"{row.wrong:>5}  {row.sizing:>6}"
        for row in summary.spots
    ]

    lines += ["", "Deviations"]
    lines += [_deviation_line(c) for c in summary.deviations] or ["  none"]

    lines.append("Playbook gaps (not_covered)")
    lines += [f"  {_gap_name(g)}  {g.count}" for g in summary.gaps] or ["  none"]

    lines.append("Unsupported / no decision")
    lines.append(
        "  "
        + (
            " | ".join(f"{reason}  {n}" for reason, n in summary.skipped.items())
            or "none"
        )
    )
    return "\n".join(lines)
