# Possession Residual Investigation — Order 9 Report

**Session date:** 2026-08-25
**Seasons measured:** E2024 (330 games) and E2025 (402 games), both complete.
E2025 was not on this machine and was **restored out of the immutable archive**,
not re-fetched from the source API.

---

## Summary

The residual is no longer unexplained. Every unit of every game's
possession-count difference is now located in the event stream and named, in
both seasons, and the arithmetic that proves the list complete is a test rather
than a claim.

Three results, in order of how much they change what we believe:

1. **A third of the failing games contain no defect at all.** 11 of the 31
   failing games — 6 in E2024, 5 in E2025 — have zero anomalous sites. Their
   entire difference comes from period structure, the first-and-last-possession
   parity, and possessions a team legitimately retained. They fail a symmetry
   assumption that basketball does not obey.
2. **One real counting defect was found and fixed.** An and-one bonus taken by a
   substitute was counted as a separate possession. The fix removes 3 phantom
   possessions across 732 games and moves 2 E2024 games inside the gate, with
   no game regressing in either season.
3. **The remaining anomalies are 30 individually located sites**, each with the
   event indices needed to reopen the source rows — not a population estimate.

The gate was not weakened, no quarantined game was included, and no threshold
was touched.

---

## The instrument

Real possessions alternate: A, then B, then A. So in the counted sequence of
endings, **two consecutive endings by the same team mark exactly one unit of
difference, at a nameable place in the event stream**.

This is not a sample of the difference — it is all of it. Any sequence of
endings decomposes into alternating runs, and the count difference is the
surplus of repeated endings plus one unit of parity for whoever ended first and
last. `src/euroleague/possession_diagnostics.py` returns both parts, and the
identity

```
difference == sum(signed_contribution over located sites) + parity_term
```

is asserted per game over both complete seasons in
`test_every_unit_of_every_game_difference_is_located`. It holds in all 732
games. **A decomposition that explained only part of the difference would fail
that test**, which is what stops this report from quietly describing a subset.

Each site is categorised from the rows between the two endings, in source order.
No event array is sorted anywhere in the diagnostic.

| Category | What it means |
|---|---|
| `period_boundary` | The two endings sit in different periods. A period end closes whatever is open for both teams, and the next period's first possession is decided by the alternating-possession arrow, not by who last had the ball. |
| `retained_after_excluded_free_throw` | The team's next possession opened on its own rebound of a free throw that ends no possession — an and-one bonus or a technical award. The ball never reached the other team. |
| `starved_team_had_the_ball` | The other team touched the ball between the two endings and no ending was ever recorded for it. This is the shape a genuinely missing ending takes. |
| `no_intervening_ball_event` | The other team never touched the ball. The stream shows no reason the ball changed hands. |

**What the instrument cannot do:** it does not say which side of a break is
wrong. A break says the endings stopped alternating there; whether that is a
missing ending for one team or an invented one for the other still needs a human
reading the rows. That is why every site carries its indices.

---

## What the decomposition found

Both tables count located sites in failing games against passing games, and the
right-hand column signs each site toward the team that is ahead — so it sums to
the residual itself.

### E2024 — 14 failing games, 47 units of difference

| Category | Sites in failing games | Per game | Sites in passing games | Per game | Net toward the leader |
|---|---:|---:|---:|---:|---:|
| `period_boundary` | 23 | 1.64 | 469 | 1.48 | **+19** |
| `retained_after_excluded_free_throw` | 12 | 0.86 | 41 | 0.13 | **+10** |
| `starved_team_had_the_ball` | 6 | 0.43 | 34 | 0.11 | **+6** |
| `no_intervening_ball_event` | 6 | 0.43 | 48 | 0.15 | **+6** |
| parity term | | | | | **+6** |
| **Total** | | | | | **47** |

### E2025 — 17 failing games, 54 units of difference

| Category | Sites in failing games | Per game | Sites in passing games | Per game | Net toward the leader |
|---|---:|---:|---:|---:|---:|
| `period_boundary` | 20 | 1.18 | 559 | 1.45 | **+20** |
| `retained_after_excluded_free_throw` | 7 | 0.41 | 52 | 0.14 | **+7** |
| `starved_team_had_the_ball` | 7 | 0.41 | 36 | 0.09 | **+7** |
| `no_intervening_ball_event` | 11 | 0.65 | 78 | 0.20 | **+11** |
| parity term | | | | | **+9** |
| **Total** | | | | | **54** |

Two things in these tables matter more than the totals.

**Period-boundary sites are not enriched in failing games at all** — 1.64 against
1.48 per game in E2024, and *lower* in E2025 failures than in its passes, 1.18
against 1.45. They are the largest single component of the residual (39 of 101
units across both seasons) and they are ordinary. What separates a failing game
is not having them, it is having them fall the same way twice.

**Retention after an excluded free throw is enriched 6.6× in E2024 and 2.9× in
E2025**, and it is not a defect either. The project already decided that a team
rebounding its own missed and-one begins a new possession — it is pinned by
`test_offensive_rebound_of_a_missed_and_one_starts_a_new_possession`, which
predates this session. A team that draws more and-ones therefore legitimately
records more possessions than its opponent.

---

## The finding that changes what the gate means

Adding up the categories that are structural or legitimate — period boundary,
parity, retention — against the two anomalous ones gives this:

| | E2024 | E2025 | Both |
|---|---:|---:|---:|
| Failing games | 14 | 17 | 31 |
| **Failing games with zero anomalous sites** | **6** | **5** | **11** |

Those eleven games are: E2024 3, 18, 45, 75, 156, 296 and E2025 124, 140, 167,
230, 337. Their differences run from 3 to 4. Every unit is a period boundary, a
parity term, or a possession one team lawfully retained.

**There is nothing in the event stream to fix in those games.** The gate asserts
that two independently counted team totals must agree within two, and basketball
does not require them to: the possession arrow decides who opens each period, a
game has a first and last possession, and an and-one miss can be rebounded by
the shooting team. Each is worth one possession, and they do not cancel.

This is stated as a measurement, not as a proposal. **The gate is unchanged, the
tolerance is unchanged, and all 31 games remain quarantined.** Whether to model
the three structural components — for instance by comparing counts after
removing period-boundary and retention units — is a decision with a real
trade-off, and it is the owner's:

- *Modelling them* would stop quarantining games that carry no defect, recovering
  data that is currently excluded by default.
- *Not modelling them* keeps the gate maximally conservative: it never admits a
  game on the strength of a rule that itself needs to be right.

The second is the status quo and costs 11 games of coverage. Nothing in this
report justifies changing it without a separate decision.

---

## The one defect found and fixed

**The and-one bonus can be taken by a different player than the one who scored**,
when the fouled scorer leaves the court before the free throw — an injury
substitution. The rule recognised an and-one by matching the free-throw shooter
against the scorer, so those bonuses looked like an ordinary trip and closed a
second possession for a team that had only had one.

The `RV` row names who received the foul. That is explicit data, in the same
family as the `PLAYTYPE` foul codes `CLAUDE.md` requires be read rather than
inferred. The rule now accepts a bonus when *either* the shooter is the scorer
*or* the scorer received a foul between the basket and the trip's first shot.
The window is bounded by those two events, so a foul belonging to the next
possession cannot reach into it.

Measured, on both complete seasons:

| | E2024 | E2025 |
|---|---:|---:|
| Games passing the gate, before | 314 | 385 |
| Games passing the gate, after | **316** | **385** |
| Games that moved inside the gate | 29, 270 | none |
| Games that regressed | **0** | **0** |
| Games whose difference changed at all | 2 | 1 (344, +1 → 0) |
| Possessions before | 47,831 | 59,483 |
| Possessions after | **47,829** | **59,482** |
| Point-exhaustiveness identity | 330/330 | 402/402 |

Three phantom possessions across 732 games. The point identity — possession
points plus off-possession points equal the official final score — still holds
in every game of both seasons, which is the check that would catch the bonus
point being dropped rather than re-credited.

The E2024 possession-gate quarantine set is therefore 14 games, not 16:
3, 18, 45, 75, 156, 177, 190, 200, 238, 239, 262, 290, 296, 323.

**Written test-first.** `test_and_one_bonus_taken_by_a_substitute_still_belongs_to_the_closed_possession`
was observed RED against a literal fixture built from E2024 game 270 before the
rule changed. Its guard,
`test_a_foul_on_a_different_player_after_a_basket_is_not_a_bonus`, was green
before and after: a foul on someone *other* than the scorer is an ordinary next
possession and must still close one.

### Two near misses that the rule correctly leaves alone

E2024 games 88 and 290 have the same shape — scorer fouled, team-mate shoots —
but a coach technical (`C`) sits inside the trip. Those trips were already
excluded from ending a possession by the retaining-foul rule, so the new
condition changes nothing there. E2024 game 167 has a substituted shooter who
*missed*; a missed bonus closes no possession under either rule.

---

## What remains, and the next discriminating measurement

30 anomalous sites remain across both seasons — 13 `starved_team_had_the_ball`
and 17 `no_intervening_ball_event` inside failing games. They are located, not
estimated. The `starved` ones, which are the shape a missing ending actually
takes:

| Season | Game | Events | No ending recorded for |
|---|---:|---|---|
| E2024 | 323 | 157 → 176 | MCO |
| E2024 | 323 | 269 → 282 | MCO |
| E2024 | 323 | 489 → 496 | MCO |
| E2024 | 262 | 48 → 63 | MIL |
| E2024 | 238 | 52 → 64 | MAD |
| E2024 | 200 | 452 → 467 | ZAL |
| E2025 | 364 | 455 → 457 | PRS |
| E2025 | 312 | 370 → 375 | HTA |
| E2025 | 163 | 252 → 260 | HTA |
| E2025 | 162 | 408 → 418 | TEL |
| E2025 | 122 | 79 → 81 | HTA |
| E2025 | 106 | 323 → 327 | IST |
| E2025 | 67 | 617 → 621 | ULK |

E2024 game 323 carries three of the six E2024 sites on the same team, MCO. That
is the next discriminating measurement, and it is a specific one: **read those
thirteen windows in the archived payloads and ask whether the missing ending has
one shape or thirteen.** A single shared shape is a rule; thirteen different ones
mean the source stream simply omits events, which is a different conclusion with
different consequences.

That work needs no new instrument. This one produces the windows.

---

## Gate compliance

- **No approved invariant weakened.** The tolerance is still 2, the five ending
  definitions are unchanged, and no possession is derived from alternation —
  alternation is used to *describe* the counted result, never to produce it.
- **No quarantined game silently included.** The two games that moved (29, 270)
  moved because their counted totals changed, and the change is explained above.
- **No green game regressed** in either season.
- **Nothing depends on sorting, clock repair, numeric player IDs, or assumed
  alternation.** The diagnostic reads events in ingest order only, uses the clock
  for nothing, and treats player IDs as opaque strings.
- **The score-exhaustiveness check was not turned into ground truth.** It appears
  above only as a check that the fix did not drop a point.

---

## Production reconciliation status

The counter now produces 47,829 E2024 and 59,482 E2025 possessions; the
production tables held 47,831 and 59,483 when this investigation completed.
**Nothing in production was changed by the original Order 9 session.**

A read-only remeasurement on 2026-08-26 found that E2024 had since been
reconciled by another production path: it now holds 47,829 possessions, games
29 and 270 are no longer quarantined, and its six derived fingerprints match
the corrected complete-season build. E2025 remained at 59,483 possessions;
game 344 alone held 161 instead of 160. The owner approved a derived-only,
one-game E2025/344 replacement and separately approved the write immediately
before execution. The attended transaction completed on 2026-08-26: it
atomically replaced 638 `game_event` rows and 160 possession rows, taking E2025
to 59,482 possessions. Raw rows, E2024, lineup, lineup stints, player-game
minutes, and game quality retained their exact pre-write fingerprints. The two
expected E2025 fingerprints are now `23c2544836c9b427a7be8430a1ee702b`
(`game_event`) and `b0a2360f2504a1e4e33b03ec2d293ea4` (`possession`).

---

## Blind spots

- The diagnostic locates units of difference; it does not adjudicate them. A
  break tells you the endings stopped alternating, not which team was miscounted.
- The category boundaries are rules, not measurements. A site that opens on an
  offensive rebound of an excluded free throw is called retention because that is
  what the approved definition says it is; if that definition is ever revisited,
  the category moves with it.
- `no_intervening_ball_event` is the least informative category by construction:
  it says the stream contains nothing to explain the change of hands, which is
  consistent both with an omitted event and with a legal dead-ball change the API
  does not record.
- The 11 no-anomaly games are only as sound as the four categories. They contain
  no site this instrument recognises as anomalous; that is not the same as
  containing no defect of any kind.
