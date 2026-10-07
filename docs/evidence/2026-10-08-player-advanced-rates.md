# Player advanced rates evidence

## Definitions

The source formulas for effective field-goal percentage and true shooting come
from the [NBA Stats glossary](https://www.nba.com/stats/help/glossary):

- `effective_fg_pct = (FGM + 0.5 * 3PM) / FGA`
- `true_shooting_pct = points / (2 * (FGA + 0.44 * FTA))`

The 0.44 factor is the standard free-throw estimate. It is not an event-exact
denominator. The same glossary defines standard usage percentage with
possession-ending free-throw attempts. This implementation publishes
`usage_event_rate` instead: `(field-goal attempt events + distinct inferred
free-throw trips + turnover events) / exact offensive possessions credited to
the player's possession-start lineup`. Every inferred trip is included,
including and-ones, so this custom event rate may exceed 1 and is not standard
USG%.

The event rates use only events whose `game_event.possession_index` matches a
reconstructed possession and whose player belongs to that possession's starting
lineup. A possession that crosses a substitution is credited wholly to that
starting lineup (Decision 5). Suspect player attribution rows do not enter
player numerators.

- `assist_rate` is player assist events divided by teammate made field goals in
  the same offensive possession-start lineup population. The player's own made
  field goals are excluded from the denominator.
- `turnover_rate` is player turnover events divided by exact offensive
  possession starts with that player in the lineup.
- `offensive_rebound_rate` is player offensive rebound events divided by the
  same player's team's offensive rebounds plus the opponent's defensive
  rebounds in those possession starts.
- `defensive_rebound_rate` uses the player's team's defensive rebounds plus the
  opponent's offensive rebounds in the player's defensive possession starts.
  Team-only rebound events remain in both opportunity denominators.

The response returns each rate as a fraction, along with its numerator and
denominator. Multiply by 100 for percentage display. Advanced support counts
remain season totals when `per_game` is enabled; the existing box-score counting
columns retain their prior `per_game` behavior.

## Validation observed

On 2026-10-08, the advanced view and test fixture were run against the disposable
local PostgreSQL database (`euroleague_test`, port 5433). No production database
was queried or changed.

- The independent PostgreSQL fixture passed. It returned a `usage_event_rate`
  of 1.5 from three counted events over two exact offensive possession starts,
  an assist rate of 1/1, offensive and defensive rebound rates of 1/3, and null
  ratios for a DNP with undefined denominators. Team-only rebounds were included
  in the opportunity denominators.
- Fifty cached E2024 games were checked against their official cached Boxscore
  responses. Every player row and its points, 2P/3P makes and attempts, and free
  throw makes and attempts matched `raw_boxscore_player`. The SQL TS and eFG
  calculations matched values recomputed from those cached official fields.
- E2024 and E2025 season aggregates had zero cases of assists exceeding
  teammate made field goals, turnovers exceeding the player's exact offensive
  possession starts, or player offensive/defensive rebounds exceeding their
  event-defined opportunities.
- The served `get_player_stats(advanced=true)` handler took 982.2 ms for one
  E2025 player and 3,090.4 ms for a 100-row E2025 league page. The latter had
  335 players available. These are local single-run timings, not a latency
  distribution.
- Ruff checks and formatting passed. The focused unit, independent fixture and
  50-game validation tests passed.

## Limits

The official box-score checks validate the shooting inputs and formulas, not the
play-by-play-derived rates. Free-throw trips are inferred and remain unsplit
when multiple awards share a group (Decision 77). The custom usage numerator
counts all FGA events, distinct inferred trips and turnovers, including and-one
trips. Rebound opportunities count recorded rebound outcomes; the feed has no
tracking-based rebound chances or closest-player data. Every possession-based
response includes the season-specific observed substitution-straddle count and
rate for its quarantine population.
