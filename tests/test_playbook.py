import itertools
from collections import Counter
from pathlib import Path

import pytest

from solver import playbook
from solver.models import Move, Node, Position

RANKS = playbook.RANKS


@pytest.mark.parametrize(
    ("text", "expected_count"),
    [
        ("77+", 8),
        ("QQ-JJ", 2),
        ("A2s+", 12),
        ("AQs-A2s", 11),
        ("AK", 2),
        ("77", 1),
        ("AKs", 1),
    ],
)
def test_expand_range_counts(text, expected_count):
    assert len(playbook.expand_range(text)) == expected_count


def test_expand_range_contents():
    assert playbook.expand_range("KJo+") == {"KJo", "KQo"}
    assert playbook.expand_range("AK") == {"AKs", "AKo"}
    assert playbook.expand_range("QQ-JJ") == {"QQ", "JJ"}
    assert playbook.expand_range("77+") == {r * 2 for r in "789TJQKA"}
    assert playbook.expand_range("A2s+") == {f"A{r}s" for r in RANKS[1:]}


def test_expand_range_tolerates_whitespace():
    assert playbook.expand_range(" 77+ ,\tAK , KJo+ ") == playbook.expand_range(
        "77+,AK,KJo+"
    )


def test_expand_range_unions_overlapping_tokens():
    assert playbook.expand_range("AKs, AK") == {"AKs", "AKo"}


@pytest.mark.parametrize(
    "token", ["A1s", "AKx", "KAs", "AQs-K2s", "AQs-A2o", "22-77", "", "77,", "AAs"]
)
def test_expand_range_rejects_invalid(token):
    with pytest.raises(playbook.PlaybookError):
        playbook.expand_range(token)


@pytest.mark.parametrize("token", ["A2+", "AQ-A2", "A2s-AQs"])
def test_expand_range_rejects_ungrammatical_forms(token):
    with pytest.raises(playbook.PlaybookError):
        playbook.expand_range(token)


@pytest.mark.parametrize(
    ("cards", "expected"),
    [
        (("Kh", "6h"), "K6s"),
        (("6h", "Kd"), "K6o"),
        (("Td", "Tc"), "TT"),
        (("2s", "As"), "A2s"),
    ],
)
def test_hand_class(cards, expected):
    assert playbook.hand_class(cards) == expected


def test_hand_class_covers_all_1326_combos_in_169_classes():
    deck = [r + s for r in RANKS for s in "shdc"]
    counts = Counter(
        playbook.hand_class(pair) for pair in itertools.combinations(deck, 2)
    )
    assert len(counts) == 169
    for cls, n in counts.items():
        expected = 6 if len(cls) == 2 else 4 if cls.endswith("s") else 12
        assert n == expected, cls


# --- parse / validate -----------------------------------------------------------

REAL_PLAYBOOK = Path(__file__).parent.parent / "data" / "playbook.md"
PLAYBOOK_MIN = Path(__file__).parent / "fixtures" / "playbook_min.md"
FIXTURE_TEXT = PLAYBOOK_MIN.read_text(encoding="utf-8")

_BASE = """
[sizing]
standard_open_bb = 3.0
open_tolerance_bb = 0.5
size_tolerance_bb = 1.0

[limits]
hero_min_stack_bb = 25.0
short_allin_max_bb = 25.0
"""
_SIZING_ONLY = _BASE.split("[limits]")[0]
_LIMITS_ONLY = "[limits]" + _BASE.split("[limits]")[1]


def doc(*blocks: str, base: str | None = _BASE) -> str:
    """A playbook document: the base block (sizing + limits) plus given blocks."""
    parts = ([base] if base is not None else []) + list(blocks)
    return "\n".join(f"```toml\n{part}\n```" for part in parts)


def test_real_playbook_parses():
    assert playbook.load_playbook(REAL_PLAYBOOK).hash


def test_fixture_parses(min_playbook):
    assert len(min_playbook.hash) == 12
    assert min_playbook.sizing.standard_open_bb == 3.0
    assert min_playbook.limits.hero_min_stack_bb == 25.0


@pytest.mark.parametrize(
    ("text", "message"),
    [
        # 1. TOML syntax
        (doc("[[rfi]\nhero = 'UTG'"), "block 2.*syntax"),
        # 2. unknown top-level key / node not an array of tables
        (doc("[extra]\nx = 1"), "unknown top-level key 'extra'"),
        (
            doc("[rfi]\nhero = 'UTG'\nraise = 'AA'\nsize_bb = 3.0"),
            "array of tables",
        ),
        # 3. unknown / missing / ill-typed keys, invalid positions
        (
            doc("[[rfi]]\nhero = 'UTG'\nraise = 'AA'\nsize_bb = 3.0\nsize_bbb = 1.0"),
            r"block 2, \[\[rfi\]\] entry 1.*size_bbb",
        ),
        (
            doc("[[rfi]]\nhero = 'UTG'\nraise = 'AA'\nsize_bb = 3.0\ncall = 'KK'"),
            "'call' not allowed",
        ),
        (
            doc("[[rfi]]\nhero = 'UTG'\nraise = 'AA'"),
            "missing required key 'size_bb'",
        ),
        (
            doc("[[rfi]]\nhero = 'UTG'\nraise = 'AA'\nsize_bb = '3'"),
            "size_bb",
        ),
        (
            doc("[[rfi]]\nhero = 'XX'\nraise = 'AA'\nsize_bb = 3.0"),
            "invalid position 'XX'",
        ),
        (
            doc("[[rfi]]\nhero = 'BB'\nraise = 'AA'\nsize_bb = 3.0"),
            "hero 'BB' not allowed",
        ),
        (
            doc(
                "[[vs_open]]\nhero = 'HJ'\nopener = 'CO'\nthree_bet = 'AA'\n"
                "three_bet_bb = 9.0"
            ),
            "does not precede",
        ),
        (doc("[[vs_shove]]\nmax_bb = 30\ncall = 'AA'"), "exceeds"),
        # 4. invalid range token
        (
            doc("[[rfi]]\nhero = 'UTG'\nraise = 'AA, A1s'\nsize_bb = 3.0"),
            "entry 1.*'A1s'",
        ),
        # 5. overlapping actions
        (
            doc("[[rfi]]\nhero = 'SB'\nraise = '55+'\nlimp = '66-22'\nsize_bb = 4.0"),
            "overlap on 55, 66",
        ),
        # 6. duplicates
        (
            doc(
                "[[rfi]]\nhero = ['UTG', 'HJ']\nraise = 'AA'\nsize_bb = 3.0\n"
                "[[rfi]]\nhero = 'HJ'\nraise = 'KK'\nsize_bb = 3.0"
            ),
            "block 2.*entry 2.*duplicate",
        ),
        (
            doc(
                "[[vs_open]]\nhero = 'BB'\nopener = ['UTG', 'CO']\n"
                "three_bet = 'AA'\nthree_bet_bb = 9.0\n"
                "[[vs_open]]\nhero = 'BB'\nopener = 'CO'\n"
                "three_bet = 'KK'\nthree_bet_bb = 9.0"
            ),
            "duplicate.*opener CO",
        ),
        (
            doc(
                "[[vs_shove]]\nmax_bb = 12\ncall = 'AA'\n"
                "[[vs_shove]]\nmax_bb = 12\ncall = 'KK'"
            ),
            "duplicate vs_shove max_bb",
        ),
        # 7. @rfi unresolvable
        (
            doc(
                "[[vs_limp]]\nhero = 'CO'\nraise = '@rfi'\niso_base_bb = 4.0\n"
                "iso_per_limper_bb = 1.0"
            ),
            "'@rfi' unresolvable",
        ),
        (
            doc("[[rfi]]\nhero = 'UTG'\nraise = '@rfi'\nsize_bb = 3.0"),
            "'@rfi' unresolvable",
        ),
        # 8. missing sizing / limits
        (doc(base=_LIMITS_ONLY), r"\[sizing\]"),
        (doc(base=_SIZING_ONLY), r"\[limits\]"),
    ],
)
def test_validation_rules(text, message):
    with pytest.raises(playbook.PlaybookError, match=message):
        playbook.parse_playbook(text)


def test_prose_and_non_toml_fences_are_ignored():
    text = (
        "# Title\n\nwords [[rfi]] ```toml inline```\n\n```python\nx = [\n```\n" + doc()
    )
    assert playbook.parse_playbook(text).sizing.standard_open_bb == 3.0


def test_rfi_reference_resolves_to_hero_rfi_raise_set(min_playbook):
    rfi = min_playbook.lookup(Node.RFI, Position.BTN)
    vs_limp = min_playbook.lookup(Node.VS_LIMP, Position.BTN)
    assert rfi is not None and vs_limp is not None
    assert vs_limp.actions[Move.RAISE] == rfi.actions[Move.RAISE]
    assert "K9s" in vs_limp.actions[Move.RAISE]


def test_rfi_reference_is_resolved_per_hero(min_playbook):
    utg = min_playbook.lookup(Node.VS_LIMP, Position.UTG)
    btn = min_playbook.lookup(Node.VS_LIMP, Position.BTN)
    assert utg is not None and btn is not None
    assert utg.actions[Move.RAISE] != btn.actions[Move.RAISE]


# --- lookup ---------------------------------------------------------------------


def test_lookup_multi_hero_keys(min_playbook):
    hj = min_playbook.lookup(Node.RFI, Position.HJ)
    co = min_playbook.lookup(Node.RFI, Position.CO)
    assert hj is not None and co is not None
    assert hj.actions == co.actions
    assert min_playbook.lookup(Node.RFI, Position.BB) is None


def test_lookup_multi_hero_and_multi_opener_keys(min_playbook):
    for hero in (Position.HJ, Position.CO, Position.BTN):
        assert min_playbook.lookup(Node.VS_OPEN, hero, Position.UTG) is not None
    for opener in (Position.HJ, Position.CO):
        assert min_playbook.lookup(Node.VS_OPEN, Position.BTN, opener) is not None
    assert min_playbook.lookup(Node.VS_OPEN, Position.CO, Position.HJ) is None


def test_lookup_vs_open_distinguishes_openers(min_playbook):
    vs_btn = min_playbook.lookup(Node.VS_OPEN, Position.BB, Position.BTN)
    vs_sb = min_playbook.lookup(Node.VS_OPEN, Position.BB, Position.SB)
    assert vs_btn is not None and vs_sb is not None
    assert vs_btn.three_bet_bb == 12.0
    assert vs_sb.three_bet_bb == 9.0


def test_lookup_ignores_opener_outside_vs_open(min_playbook):
    entry = min_playbook.lookup(Node.VS_OPEN_CALLED, Position.BB, Position.CO)
    assert entry is not None
    assert entry.per_caller_bb == 3.0


@pytest.mark.parametrize(
    ("shove_bb", "bucket"), [(10, 12.0), (12, 12.0), (13, 25.0), (30, None)]
)
def test_lookup_vs_shove_buckets(min_playbook, shove_bb, bucket):
    entry = min_playbook.lookup(Node.VS_SHOVE, None, shove_bb=shove_bb)
    assert (entry.max_bb if entry else None) == bucket


def test_lookup_vs_shove_without_size_is_none(min_playbook):
    assert min_playbook.lookup(Node.VS_SHOVE, None) is None


def test_hu_vs_limp_defaults_per_limper_to_zero(min_playbook):
    entry = min_playbook.lookup(Node.HU_VS_LIMP, Position.BB)
    assert entry is not None
    assert entry.iso_per_limper_bb == 0.0


def test_entry_expected_uses_default_for_unlisted_hands(min_playbook):
    entry = min_playbook.lookup(Node.RFI, Position.UTG)
    assert entry is not None
    assert entry.expected("AA", Move.FOLD) is Move.RAISE
    assert entry.expected("72o", Move.FOLD) is Move.FOLD
    assert entry.expected("72o", Move.CHECK) is Move.CHECK


# --- hash -----------------------------------------------------------------------


def test_hash_unchanged_by_prose_edit(min_playbook):
    edited = FIXTURE_TEXT.replace("Small and stable", "Tiny, stable, reworded")
    assert edited != FIXTURE_TEXT
    assert playbook.parse_playbook(edited).hash == min_playbook.hash


def test_hash_unchanged_by_token_order_within_a_range(min_playbook):
    edited = FIXTURE_TEXT.replace(
        'raise = "77+, AJs+, AQo+"', 'raise = "AQo+, AJs+, 77+"'
    )
    assert edited != FIXTURE_TEXT
    assert playbook.parse_playbook(edited).hash == min_playbook.hash


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('raise = "77+, AJs+, AQo+"', 'raise = "88+, AJs+, AQo+"'),
        ("size_bb = 2.5", "size_bb = 2.0"),
        ("size_tolerance_bb = 1.0", "size_tolerance_bb = 0.5"),
    ],
)
def test_hash_changed_by_range_or_size_edit(min_playbook, old, new):
    edited = FIXTURE_TEXT.replace(old, new)
    assert edited != FIXTURE_TEXT
    assert playbook.parse_playbook(edited).hash != min_playbook.hash
