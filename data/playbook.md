# NL2 6-max Preflop Playbook

Scope: hero's **first voluntary preflop decision** only, ~100bb effective.
Everything after it (facing a 3-bet after opening, limp-then-raise, etc.) goes to the coach.

## Format rules (for the parser)

- Only ```` ```toml ```` blocks are parsed. Prose is ignored by the parser (may be sent to the LLM as context).
- Range notation: `77+`, `QQ-JJ`, `A2s+`, `AQs-A2s`, `KJo+`, `AK` (= `AKs, AKo`). Expands to the 169 hand classes.
- A hand not listed in any action of a node = **fold** (or **check**, when checking is free).
- Within one entry, action ranges must be disjoint. A `(hero, opener)` pair may appear in only one entry per node.
- Positions are labelled from the button backwards: `BTN, CO, HJ, UTG`, plus `SB, BB`.
- `"@rfi"` as a range = the hero's RFI range.
- Sizing: see "Sizing rules" below.

## Sizing rules

- **All sizes are absolute, in bb.**
  - `size_bb`: open-to size.
  - `iso_base_bb` + `iso_per_limper_bb`: isolation size.
  - `three_bet_bb` (+ `per_caller_bb`): 3-bet-to size.
- **3-bet sizes assume a standard open.** The baseline is set in the `[sizing]` block. 3-bet sizing is checked only when the open hero faces is within `standard_open_bb ± open_tolerance_bb`. Otherwise sizing is not checked, and the actual size and the open size are passed to the coach as facts.
- **Hero's own size is accepted** within `size_tolerance_bb` of the expected size.
- **`vs_reraise` and `vs_shove` have no sizing check.**

```toml
[sizing]
standard_open_bb = 3.0
open_tolerance_bb = 0.5
size_tolerance_bb = 1.0
```

Limits: hands where hero starts with less than `hero_min_stack_bb` are not assessed. An all-in raise of at most `short_allin_max_bb` counts as a shove.

```toml
[limits]
hero_min_stack_bb = 25.0
short_allin_max_bb = 25.0
```

## Population assumptions (NL2)

- Players limp and cold-call too much, rarely 3-bet light, and rarely fold to a single bet postflop.
- Their 3-bets and 4-bets are strong; respect them.

Consequences:

- **3-bets are value-heavy (linear), with few or no bluffs.** Bluff 3-bets get called by worse-but-sticky hands, so they lose their value.
- **Isolate limpers wide in position, with larger sizes.** Fish call too wide preflop and keep calling after the flop.
- **Set-mine small pairs** and **flat suited hands in position**, because implied odds against stations are high.
- **Fold more to aggression than theory suggests.**

---

## RFI: folded to hero

Open-or-fold, no limping (including the SB).

```toml
[[rfi]]
hero = "UTG"
raise = "77+, AJs+, KJs+, AQo+"
size_bb = 3.0

[[rfi]]
hero = "HJ"
raise = "55+, ATs+, KJs+, QJs, JTs, AJo+, KQo"
size_bb = 3.0

[[rfi]]
hero = "CO"
raise = "22+, A2s+, K9s+, Q9s+, JTs, T9s, 98s, 87s, 76s, 65s, ATo+, KJo+, QJo, JTo"
size_bb = 3.0

[[rfi]]
hero = "BTN"
raise = "22+, A2s+, K4s+, Q4s+, J8s+, T8s+, 97s+, 86s+, 75s+, 65s, 54s, A2o+, K7o+, Q8o+, J8o+, T8o+"
size_bb = 3.0

[[rfi]]
hero = "SB"
raise = "22+, A2s+, K2s+, Q2s+, J7s+, T7s+, 97s+, 86s+, 75s+, 65s, 54s, A2o+, K7o+, Q8o+, J8o+, T8o+"
size_bb = 4.0
```

## vs_limp: one or more limpers, no raise

Same range as RFI from that position, sized up: open size + 1bb + 1bb per limper.
`"@rfi"` = the hero's RFI range (single source of truth). From the BB, unlisted hands check.

```toml
[[vs_limp]]
hero = ["UTG", "HJ", "CO", "BTN"]
raise = "@rfi"
iso_base_bb = 4.0
iso_per_limper_bb = 1.0

[[vs_limp]]
hero = "SB"
raise = "@rfi"
iso_base_bb = 5.0
iso_per_limper_bb = 1.0

[[vs_limp]]
hero = "BB"
raise = "99+, AJs+, KQs, AQo+"
iso_base_bb = 5.0
iso_per_limper_bb = 1.0
```

## vs_open: one raise, no callers

Ranges depend on the opener's position.
- **HJ, CO, BTN** use your 3-bet and call ranges.
- **SB** plays 3-bet or fold: it uses the same 3-bet ranges, never flats.
- **BB** defends wide because of the price it gets.

3-bet sizes assume a standard 3bb open (see Sizing rules).

```toml
# --- UTG opens ---
[[vs_open]]
hero = ["HJ", "CO", "BTN"]
opener = "UTG"
three_bet = "QQ+, AKs, AKo"
call = "JJ-TT, AQs, KQs"
three_bet_bb = 9.0

# --- HJ opens ---
[[vs_open]]
hero = ["CO", "BTN"]
opener = "HJ"
three_bet = "QQ+, AKs, AKo"
call = "JJ-88, AQs, AJs, KQs, KJs, QJs, JTs"
three_bet_bb = 9.0

# --- CO opens ---
[[vs_open]]
hero = "BTN"
opener = "CO"
three_bet = "JJ+, AKs, AKo, AQs"
call = "TT-22, AJs, ATs, KQs, KJs, KTs, QJs, QTs, JTs, T9s, 98s"
three_bet_bb = 9.0

# --- SB: 3-bet or fold ---
[[vs_open]]
hero = "SB"
opener = ["UTG", "HJ"]
three_bet = "QQ+, AKs, AKo"
three_bet_bb = 12.0

[[vs_open]]
hero = "SB"
opener = "CO"
three_bet = "JJ+, AKs, AKo, AQs"
three_bet_bb = 12.0

[[vs_open]]
hero = "SB"
opener = "BTN"
three_bet = "88+, ATs+, KJs+, QJs, AJo+, KQo"
three_bet_bb = 12.0

# --- BB defence ---
[[vs_open]]
hero = "BB"
opener = ["UTG", "HJ"]
three_bet = "QQ+, AKs, AKo"
call = "JJ-22, AQs-A2s, KTs+, QTs+, J9s+, T9s, 98s, 87s, 76s, 65s, AQo, AJo, KQo"
three_bet_bb = 12.0

[[vs_open]]
hero = "BB"
opener = "CO"
three_bet = "TT+, AJs+, KQs, AQo+"
call = "99-22, ATs-A2s, KJs-K6s, Q8s+, J8s+, T8s+, 97s+, 86s+, 75s+, 65s, 54s, AJo-A9o, KTo+, QTo+, JTo"
three_bet_bb = 12.0

[[vs_open]]
hero = "BB"
opener = "BTN"
three_bet = "99+, ATs+, KJs+, QJs, AJo+, KQo"
call = "88-22, A9s-A2s, KTs-K2s, QTs-Q4s, J6s+, T6s+, 95s+, 85s+, 74s+, 64s+, 53s+, 43s, ATo-A2o, KJo-K8o, Q9o+, J9o+, T9o, 98o"
three_bet_bb = 12.0

[[vs_open]]
hero = "BB"
opener = "SB"
three_bet = "88+, ATs+, KTs+, QJs, ATo+, KJo+"
call = "77-22, A9s-A2s, K9s-K2s, QTs-Q2s, J5s+, T6s+, 95s+, 85s+, 74s+, 63s+, 53s+, 43s, A9o-A2o, KTo-K5o, Q8o+, J8o+, T8o+, 98o, 87o"
three_bet_bb = 9.0
```

## vs_open_called: open plus one or more callers (squeeze spot)

The dead money is real, but NL2 callers rarely fold. Squeeze for value only and size up for each caller. Flat with hands that play well multiway.

```toml
[[vs_open_called]]
hero = ["HJ", "CO", "BTN"]
three_bet = "QQ+, AKs, AKo"
call = "JJ-22, AQs, AJs, KQs, JTs, T9s, 98s"
three_bet_bb = 9.0
per_caller_bb = 3.0

[[vs_open_called]]
hero = "SB"
three_bet = "QQ+, AKs, AKo"
call = "JJ-55, AQs, AJs, KQs"
three_bet_bb = 12.0
per_caller_bb = 3.0

[[vs_open_called]]
hero = "BB"
three_bet = "QQ+, AKs, AKo"
call = "JJ-22, AQs-A2s, KTs+, QTs+, J9s+, T9s, 98s, 87s, 76s, 65s, 54s, AQo, AJo, KQo"
three_bet_bb = 12.0
per_caller_bb = 3.0
```

## vs_reraise: two or more raises before hero (cold 4-bet spot)

An open followed by a 3-bet at NL2 is very strong. Play only premium hands.

```toml
[[vs_reraise]]
hero = ["HJ", "CO", "BTN", "SB", "BB"]
raise = "KK+, AKs"
call = "QQ-JJ, AKo"
```

## vs_shove: facing an all-in of 25bb or less

Short stacks at NL2 shove wide. Call based on the size of the shove; the shover's position is ignored. The first matching bucket wins (smallest `max_bb` first).

```toml
[[vs_shove]]
max_bb = 12
call = "22+, A2s+, A7o+, K9s+, KJo+, QTs+, JTs"

[[vs_shove]]
max_bb = 25
call = "77+, A9s+, KJs+, AJo+, KQo"
```

## Heads-up (exactly 2 players dealt in)

The button is also the SB, acts first preflop and is in position postflop. Open very wide and don't limp. The BB defends very wide.

```toml
[[hu_rfi]]
hero = "BTN"
raise = "22+, A2s+, K2s+, Q2s+, J4s+, T6s+, 96s+, 85s+, 74s+, 64s+, 53s+, 43s, A2o+, K5o+, Q8o+, J8o+, T8o+, 98o"
size_bb = 2.5

[[hu_vs_open]]
hero = "BB"
three_bet = "88+, A9s+, KTs+, QJs, ATo+, KJo+"
call = "77-22, A8s-A2s, K9s-K2s, QTs-Q2s, J2s+, T5s+, 95s+, 84s+, 74s+, 63s+, 53s+, 43s, A9o-A2o, KTo-K2o, Q5o+, J7o+, T7o+, 97o+, 87o, 76o"
three_bet_bb = 12.0

[[hu_vs_limp]]
hero = "BB"
raise = "77+, A8s+, KTs+, QJs, ATo+, KJo+"
iso_base_bb = 4.0
```
