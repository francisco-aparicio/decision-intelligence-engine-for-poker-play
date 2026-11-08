# Minimal test playbook

Small and stable on purpose: tests must not depend on `data/playbook.md`.
This prose is ignored by the parser, and a prose-only edit must not change the hash.

```toml
[sizing]
standard_open_bb = 3.0
open_tolerance_bb = 0.5
size_tolerance_bb = 1.0

[limits]
hero_min_stack_bb = 25.0
short_allin_max_bb = 25.0
```

## RFI

```toml
[[rfi]]
hero = "UTG"
raise = "77+, AJs+, AQo+"
size_bb = 3.0

# Multi-hero entry.
[[rfi]]
hero = ["HJ", "CO"]
raise = "66+, ATs+, AJo+, KQo"
size_bb = 3.0

[[rfi]]
hero = "BTN"
raise = "22+, A2s+, K9s+, QTs+, JTs, ATo+, KJo+"
size_bb = 3.0

[[rfi]]
hero = "SB"
raise = "55+, A2s+, KTs+, ATo+"
limp = "44-22"
size_bb = 4.0
```

## vs_limp

```toml
[[vs_limp]]
hero = ["UTG", "HJ", "CO", "BTN"]
raise = "@rfi"
iso_base_bb = 4.0
iso_per_limper_bb = 1.0

[[vs_limp]]
hero = "SB"
raise = "@rfi"
overlimp = "44-22"
iso_base_bb = 5.0
iso_per_limper_bb = 1.0

[[vs_limp]]
hero = "BB"
raise = "99+, AJs+, AQo+"
iso_base_bb = 5.0
iso_per_limper_bb = 1.0
```

## vs_open

```toml
# Multi-hero entry.
[[vs_open]]
hero = ["HJ", "CO", "BTN"]
opener = "UTG"
three_bet = "QQ+, AKs"
call = "JJ-TT, AQs"
three_bet_bb = 9.0

# Multi-opener entry.
[[vs_open]]
hero = "BTN"
opener = ["HJ", "CO"]
three_bet = "QQ+, AKs"
call = "JJ-77, AQs-AJs"
three_bet_bb = 9.0

[[vs_open]]
hero = "SB"
opener = "BTN"
three_bet = "99+, ATs+"
three_bet_bb = 12.0

[[vs_open]]
hero = "BB"
opener = "BTN"
three_bet = "TT+, AQs+"
call = "99-22, ATs-A2s, KTs+"
three_bet_bb = 12.0

[[vs_open]]
hero = "BB"
opener = "SB"
three_bet = "99+"
call = "88-22"
three_bet_bb = 9.0
```

## vs_open_called

```toml
[[vs_open_called]]
hero = ["CO", "BTN"]
three_bet = "QQ+, AKs"
call = "JJ-22, AQs"
three_bet_bb = 9.0
per_caller_bb = 3.0

[[vs_open_called]]
hero = "BB"
three_bet = "QQ+, AKs"
call = "JJ-22"
three_bet_bb = 12.0
per_caller_bb = 3.0
```

## vs_reraise

```toml
[[vs_reraise]]
hero = ["HJ", "CO", "BTN", "SB", "BB"]
raise = "KK+, AKs"
call = "QQ-JJ, AKo"
```

## vs_shove

Written out of order on purpose: the 12 bucket must still win for small shoves.

```toml
[[vs_shove]]
max_bb = 25
call = "77+, A9s+, AJo+"

[[vs_shove]]
max_bb = 12
call = "22+, A2s+, K9s+, A7o+"
```

## Heads-up

```toml
[[hu_rfi]]
hero = "BTN"
raise = "22+, A2s+, K2s+, A2o+, K5o+"
size_bb = 2.5

[[hu_vs_open]]
hero = "BB"
three_bet = "88+, ATs+"
call = "77-22, A9s-A2s"
three_bet_bb = 12.0

[[hu_vs_limp]]
hero = "BB"
raise = "77+, A8s+"
iso_base_bb = 4.0
```
