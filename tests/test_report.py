from solver import report
from solver.models import (
    CheckStatus,
    DecisionCheck,
    DeviationKind,
    Move,
    Node,
    Position,
)


def ok(node: Node, hero: Position, n: int = 1) -> list[DecisionCheck]:
    return [
        DecisionCheck(
            hand_id=f"ok-{node.value}-{hero.value}-{i}",
            status=CheckStatus.OK,
            node=node,
            hero_pos=hero,
        )
        for i in range(n)
    ]


def deviation(
    node: Node, hero: Position, kind: DeviationKind, hand_id: str
) -> DecisionCheck:
    return DecisionCheck(
        hand_id=hand_id,
        status=CheckStatus.DEVIATION,
        node=node,
        hero_pos=hero,
        hand_class="K6s",
        expected_action=Move.FOLD,
        actual_action=Move.RAISE,
        deviation_kind=kind,
    )


def not_covered(opener: Position | None, hand_id: str) -> DecisionCheck:
    return DecisionCheck(
        hand_id=hand_id,
        status=CheckStatus.NOT_COVERED,
        node=Node.VS_OPEN_CALLED,
        hero_pos=Position.SB,
        opener_pos=opener,
    )


def skipped(status: CheckStatus, reason: str, hand_id: str) -> DecisionCheck:
    return DecisionCheck(hand_id=hand_id, status=status, reason=reason)


def sample_checks() -> list[DecisionCheck]:
    return [
        *ok(Node.RFI, Position.BTN, 3),
        *ok(Node.VS_OPEN, Position.BB, 4),
        deviation(Node.RFI, Position.BTN, DeviationKind.TOO_LOOSE, "d1"),
        deviation(Node.VS_OPEN, Position.BB, DeviationKind.TOO_TIGHT, "d2"),
        deviation(Node.VS_OPEN, Position.BB, DeviationKind.SIZING, "d3"),
        *ok(Node.RFI, Position.CO, 1),
        deviation(Node.RFI, Position.CO, DeviationKind.WRONG_ACTION, "d4"),
        not_covered(Position.CO, "g1"),
        not_covered(Position.CO, "g2"),
        not_covered(None, "g3"),
        skipped(CheckStatus.NO_DECISION, "no_hero_action", "n1"),
        skipped(CheckStatus.NO_DECISION, "no_hero_action", "n2"),
        skipped(CheckStatus.UNSUPPORTED, "hero_short_stack", "u1"),
    ]


def test_summarize_status_counts_and_adherence():
    summary = report.summarize(sample_checks())

    assert summary.total == 18
    assert summary.status_counts[CheckStatus.OK] == 8
    assert summary.status_counts[CheckStatus.DEVIATION] == 4
    assert summary.status_counts[CheckStatus.NOT_COVERED] == 3
    assert summary.status_counts[CheckStatus.NO_DECISION] == 2
    assert summary.status_counts[CheckStatus.UNSUPPORTED] == 1
    assert summary.assessed == 12
    assert summary.adherence == 8 / 12
    assert summary.kind_counts == {
        DeviationKind.TOO_LOOSE: 1,
        DeviationKind.TOO_TIGHT: 1,
        DeviationKind.WRONG_ACTION: 1,
        DeviationKind.SIZING: 1,
    }


def test_summarize_spot_rows_sorted_by_dev_then_n():
    rows = report.summarize(sample_checks()).spots

    assert [(r.spot, r.n, r.dev) for r in rows] == [
        ("vs_open.BB", 6, 2),
        ("rfi.BTN", 4, 1),
        ("rfi.CO", 2, 1),
    ]
    bb = rows[0]
    assert (bb.loose, bb.tight, bb.wrong, bb.sizing) == (0, 1, 0, 1)


def test_summarize_spot_ties_break_by_n_then_name():
    checks = [
        *ok(Node.RFI, Position.UTG, 2),
        *ok(Node.RFI, Position.HJ, 5),
        *ok(Node.RFI, Position.CO, 5),
    ]

    rows = report.summarize(checks).spots

    assert [r.spot for r in rows] == ["rfi.CO", "rfi.HJ", "rfi.UTG"]


def test_summarize_groups_gaps_and_skipped_hands():
    summary = report.summarize(sample_checks())

    assert [(g.opener_pos, g.count) for g in summary.gaps] == [
        (Position.CO, 2),
        (None, 1),
    ]
    assert summary.skipped == {"no_hero_action": 2, "hero_short_stack": 1}
    assert [d.hand_id for d in summary.deviations] == ["d1", "d2", "d3", "d4"]


def test_summarize_zero_assessed_hands_has_no_adherence():
    summary = report.summarize(
        [skipped(CheckStatus.NO_DECISION, "no_hero_action", "n1")]
    )

    assert summary.assessed == 0
    assert summary.adherence is None
    text = report.format_report(
        summary, scope="all hands", playbook_hash="h", db_path="d"
    )
    assert "Adherence: n/a" in text


def test_summarize_empty_list():
    summary = report.summarize([])

    assert summary.total == 0
    assert summary.spots == []
    assert summary.adherence is None


def test_format_report_layout():
    text = report.format_report(
        report.summarize(sample_checks()),
        scope="session_x.txt",
        playbook_hash="a1b2c3d4e5f6",
        db_path="data/solver.db",
    )
    lines = text.splitlines()

    assert lines[0] == (
        "Preflop check — scope: session_x.txt | playbook a1b2c3d4e5f6 "
        "| DB data/solver.db"
    )
    assert lines[1] == (
        "Hands: 18 | assessed 12 | no_decision 2 | not_covered 3 | unsupported 1"
    )
    assert lines[2] == (
        "Adherence: 8/12 (66.7%) | too_loose 1 | too_tight 1 | wrong_action 1 | sizing 1"
    )
    assert "vs_open.BB" in text
    assert "Playbook gaps (not_covered)" in lines
    assert "  vs_open_called.SB (opener CO)  2" in lines
    assert "  vs_open_called.SB  1" in lines
    assert "  no_hero_action  2 | hero_short_stack  1" in lines


def test_format_report_shows_sizes_only_for_sizing_deviations():
    sizing = DecisionCheck(
        hand_id="9",
        status=CheckStatus.DEVIATION,
        node=Node.RFI,
        hero_pos=Position.CO,
        hand_class="AJo",
        expected_action=Move.RAISE,
        actual_action=Move.RAISE,
        deviation_kind=DeviationKind.SIZING,
        actual_size_bb=5.0,
        expected_size_bb=3.0,
        sizing_checked=True,
    )
    loose = deviation(Node.RFI, Position.BTN, DeviationKind.TOO_LOOSE, "8")

    text = report.format_report(
        report.summarize([sizing, loose]), scope="s", playbook_hash="h", db_path="d"
    )

    assert "expected raise 3.0  actual raise 5.0  sizing" in text
    assert "expected fold" in text
