# E2024 raw shot ingest report

Measured on 2026-08-13 from the 330 archived E2024 `Points`, `PlaybyPlay`, and
`Boxscore` responses. The EuroLeague API was not contacted. The only external
connection was the private PostgreSQL connection required to load `raw_shot`
and measure its physical size.

## Population and exact join

The parser produced 51,193 `raw_shot` rows: 41,533 field goals and 9,660 made
free throws. Every game's parsed count equals the number of rows in its
archived `Points` response.

All 51,193 coordinate rows joined to exactly one play-by-play event on
`Points.NUM_ANOT = PlaybyPlay.NUMBEROFPLAY`: **51,193 of 51,193, 100.00%**.
For field goals alone the result is **41,533 of 41,533, 100.00%**. There are no
unjoined rows to list. After the exact-key join there are also zero action-code,
team-code, or player-ID disagreements. No clock, player, or nearest-event
fallback was attempted.

This proves coordinate rows can be attached to the intended source events. It
does not prove that each published coordinate is geometrically correct.

## Official box-score gate

For both teams in every game, the parsed field goals were counted separately as
two-point makes, two-point attempts, three-point makes, and three-point
attempts. All **2,640 values** across **660 team-games** equal the official
`Boxscore` totals. Mismatches: **0**.

This is the shipping gate. It can detect a parser that drops a field goal,
duplicates one, assigns it to the wrong team, or misreads its two/three and
made/missed action. It cannot detect a wrong coordinate when the action and team
remain correct.

## Geometry measurement

The `(-1,-1)` sentinel was excluded before calculating distance. The result
contradicts the one-game figures in `exploration/FINDINGS.md`:

- Longest valid-coordinate two-point attempt: **827.454 cm**, game 146, play
  572, at `(-382,734)`, zone H, missed.
- Shortest valid-coordinate three-point attempt: **83.630 cm**, game 222, play
  186, at `(37,75)`, zone C, missed.
- The single-game values of 530 cm and 680 cm therefore do **not** survive the
  season.
- The radial overlap band is 83.630 through 827.454 cm and contains **37,727
  field-goal rows**.

For the corner classification, a row is called a corner shot when its absolute
X coordinate is at least 660 cm and its Y coordinate lies within the straight
corner segment's intersection with the 675 cm arc. This is a measurement label,
not a correction or a new source field.

| Zone | 2P non-corner | 2P corner | 3P non-corner | 3P corner | Total |
|---|---:|---:|---:|---:|---:|
| A | 16 | 0 | 0 | 0 | 16 |
| B | 7,785 | 0 | 1 | 0 | 7,786 |
| C | 6,038 | 0 | 2 | 0 | 6,040 |
| D | 2,777 | 0 | 2 | 0 | 2,779 |
| E | 2,655 | 0 | 3 | 0 | 2,658 |
| F | 1,401 | 0 | 7 | 0 | 1,408 |
| G | 1,414 | 0 | 5 | 0 | 1,419 |
| H | 11 | 0 | 6,686 | 867 | 7,564 |
| I | 13 | 3 | 7,098 | 943 | 8,057 |
| **Total** | **22,110** | **3** | **13,804** | **1,810** | **37,727** |

The overlap is much larger than the unavoidable corner-versus-arc overlap
described in the work order. The extreme rows include published action/location
combinations that cannot be separated by a radial threshold. They remain source
facts in `raw_shot`; no coordinate or action was changed.

## Sentinel measurement in both directions

All **9,660 of 9,660** free throws in `Points` are exactly `(-1,-1)`.

The reverse statement is false: nine field goals also carry the sentinel. These
are source defects and remain loaded unchanged:

| Game | Play number | Action | Team | Player ID |
|---:|---:|---|---|---|
| 15 | 575 | 2FGA | MAD | P006540 |
| 28 | 410 | 2FGA | BER | P008062 |
| 69 | 205 | 3FGA | ASV | P002100 |
| 117 | 234 | 2FGA | BER | P013386 |
| 171 | 570 | 2FGA | MAD | P006540 |
| 193 | 47 | 2FGA | MAD | P006540 |
| 213 | 575 | 2FGA | VIR | P009549 |
| 250 | 402 | 2FGM | TEL | P012604 |
| 272 | 350 | 3FGA | ZAL | P007513 |

A chart must therefore exclude `(-1,-1)` by coordinate, not merely by checking
whether the action is a free throw.

## Load, idempotency, and storage

Before the load, E2024 had zero `raw_shot` rows. The empty relation occupied
24,576 bytes: 8,192 table bytes and 16,384 index bytes.

After loading all 51,193 rows twice:

| Measure | Bytes |
|---|---:|
| Table, including TOAST | 9,666,560 |
| Indexes | 3,923,968 |
| Total relation | 13,590,528 |
| Growth above the empty relation | **13,565,952** |

The second complete load produced the identical `raw_shot` content fingerprint.
Every other raw-table fingerprint was unchanged, and database row counts match
all 330 archived responses game by game.

A later final verification repeated both loads. PostgreSQL retained reusable
pages, so the operational relation then measured 10,682,368 table bytes,
4,005,888 index bytes, and 14,688,256 total bytes: **14,663,680 bytes above the
empty relation**. `VACUUM FULL` was not run because it would exclusively lock
the shared production table. The first figure is the measured cost immediately
after the required second load; the latter is the conservative current
operational cost after repeated validation.

Using the larger 44,435.3939 operational bytes per E2024 game, projecting the
same cost over Decision 20's 1,063-game three-season window spends approximately
**47,234,824 bytes** of its previously stated 122.768 MB headroom. Under that
explicit, unmeasured cross-season cost assumption, projected total usage becomes
about 424.467 MB and remaining headroom becomes about **75.533 MB (15.11%)**.
This must be re-measured after E2025 loads, as Decision 20 already requires.

## What one row means and how a chart uses it

One `raw_shot` row means that the archived `Points` response published one
coordinate-bearing scoring action with that play number, player, team, action,
score state, and coordinate. It is a source mirror, not a complete list of shot
attempts: `Points` omits missed free throws.

A safe shot chart starts with the desired field-goal events in `game_event`,
then left-joins `raw_shot` on season, game, and exact play number to attach X,
Y, and zone. It excludes `(-1,-1)` before plotting. X is left/right relative to
the attacking basket, not a fixed arena side; Y runs away from the basket. Any
query that includes free throws must still start from `game_event`, because
`raw_shot` cannot supply the missed ones.
