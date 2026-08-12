# Decision log

Decisions made on the schema proposal, with the reasoning behind each. This
file exists so that any agent picking up the project has the decision context
without needing the conversation it came from.

Format: the decision, then why, then any condition attached to it. A condition
is binding — the decision is only approved with it.

---

## Status

| # | Topic | Status |
|---|---|---|
| 1 | Layer split and the trimming trade-off | Approved as proposed |
| 2 | Offensive-foul inference (section 0b) | Approved — already applied |
| 3 | `corrected` as the default for minutes | Approved with two conditions |
| 4 | Matchup-bounded stints | Approved as proposed |
| 5 | Possession-straddling convention | Approved with one condition |
| 6 | Clutch splits | Approved, but **re-framed** — read below |
| 7 | Re-ingest policy | Approved — immutable versions and per-game rebuilds |
| 8 | Backfill scope and event text | Approved with a physical-size gate; season count amended 19 → 23 on 2026-08-10 |
| 9 | Where the immutable archive lives | Supabase Storage; Postgres holds no bodies |
| 10 | Migration tooling and the rollback gate | Plain SQL files applied through the Supabase MCP |
| 11 | EuroCup scope for the October launch | Schema-ready, not loaded |
| 12 | The Supabase project | Created — `euroleague-analytics`, eu-central-1 |
| 13 | Public repository, and what stays out of it | Public; `CONTEXT.md` untracked |
| 14 | How the test suite gets its data | Committed edge-case fixtures; full season on demand |
| 15 | How Python reaches Postgres | `psycopg` through the connection pooler |
| 16 | Dependency tooling | `pip` with pinned requirements files |
| 17 | `Points` is a coordinate source only | Approved with one condition |
| 18 | MCP aggregation in views | Approved with a measurement |

Items 7 and 8 were raised after the schema proposal. Phase 1 resolved them on
2026-08-09. The measurements and explicit estimate boundaries are in
`exploration/OPEN_ITEMS.md`.

Items 9 to 12 were raised at the start of Phase 2, also on 2026-08-09, because
each one changes what the migrations must contain.

Items 13 to 16 were raised at the start of Phase 2a, also on 2026-08-09,
because each one changes what the scaffolding must contain.

Item 17 was raised on 2026-08-09 when the production fetcher began archiving a
third endpoint, and approved on 2026-08-10.

Item 18 was raised and approved on 2026-08-12 while designing the Phase 7 MCP
query layer.

---

## 1. Layer split and trimming — approved as proposed

Trim IDs and team codes in the raw tables. Byte-level fidelity is carried by
`raw_api_response`, which stores the untouched payload plus a checksum.

**Why.** The padding is fixed-width formatting, not meaning. Its failure mode
is silent: joining `"BER       "` to `"BER"` returns an empty result rather
than an error. The archive layer guarantees fidelity and the table layer
guarantees usability, so neither has to be compromised.

---

## 2. Offensive-foul inference — approved, already applied

Foul type is read from `PLAYTYPE`. The "foul + turnover sharing a clock
reading" inference is deleted and banned.

**Why.** Measured at 77.7% precision — it would invent 340 turnovers a season.
The original rule was generalised from a single game that happened to contain
no offensive foul at all, and the example that motivated it turned out to be a
false positive under its own rule.

**Consequence to carry into possession logic.** Every offensive foul already
carries its own separate `TO` row. The risk is double-counting, not
under-counting. Count the `TO` row and ignore the `OF` row, or the season gains
1,185 phantom turnovers.

---

## 3. `corrected` as the default for minutes — approved with two conditions

The MCP layer serves corrected values for anything involving minutes or
per-minute rates. `raw` stays available alongside and is used for anything
positional.

**Why.** The lesson from the clamp experiment does not transfer. The clamp was a
blanket rewrite of every timestamp and broke 183 of 330 games. This is a narrow
mechanical rule firing on 32 rows, and it was *measured* to improve agreement
with the published box score: 36 mismatched player-rows down to 4. It has
external ground truth, so it satisfies the project's own standard for shipping
a derived value.

**Condition A — provenance travels with the number.** Any MCP response
containing a minutes value must state whether it is raw or corrected. Holding
it in a column is not enough. Same reasoning as the quarantine-disclosure rule:
a number without its provenance is a number that will be misquoted.

**Condition B — re-measure every season, never assume.** This rule was tuned on
E2024. It must be re-measured against each new season. Build a mechanical
safety belt: if the correction increases disagreement with the official box
score for any season, it auto-disables for that season and its test fails red.

---

## 4. Matchup-bounded stints — approved as proposed

A stint boundary is drawn when either team substitutes.

**Why.** Matchup stints aggregate up into team stints; team stints cannot be
split back down into matchups. Storing the finer grain keeps both questions
answerable. The row-count cost is trivial.

Also approved: the batch-boundary rule from section 6 — a batch spans from the
first substitution carrying a clock reading to the last one carrying it,
absorbing intruders — combined with the union tolerance window for attribution
checking. Measured at 0 on-court violations and 7 misattributed rows, the best
result of any combination tested.

---

## 5. Possession-straddling convention — approved with one condition

A possession is credited to the lineup on the floor when the possession
started.

**Why.** Simple, writable down, and it makes possession counts sum cleanly to
team totals, which is a required invariant. A consistent convention beats a
theoretically purer one that nobody can reason about.

**Condition — measure the magnitude.** Report the rate of possessions that
straddle a substitution, as a number, in the season sweep output. Nobody
currently knows whether this is 2% or 15% of possessions, and the two cases
warrant different treatment. A documented approximation without a measured
magnitude is not documented.

---

## 6. Clutch — critical, but re-framed

**Clutch matters. It is the single most important query shape this project
needs to support.** But the proposal framed it as a stint-splitting problem,
and that framing is wrong.

A stint is a coarse unit: it spans many possessions, straddles the moment a
game becomes clutch, and the score margin changes *within* it. A possession is
fine-grained: roughly fifteen seconds, one score margin, and by the convention
above, exactly one lineup.

**So clutch is a filter on possessions, not a split of stints.**

**Decision:** add two columns to the `possession` table —
`margin_at_start` and `seconds_remaining_at_start`.

**Why this is better than a pre-computed clutch table.**

- No threshold is ever baked in. Last 5 minutes within 5 points, last 2 minutes
  within 3 points, any other definition — all are queries, not rebuilds.
- EuroLeague is a 40-minute game. Importing the NBA's 48-minute clutch
  convention unexamined would be a mistake, and this defers that choice until
  it can be made against the data.
- It costs two integer columns instead of a whole table and its refresh logic.
- It does not violate the "no heavy computation at query time" rule, because
  filtering on two indexed integer columns is not heavy computation.

**What is given up.** Duration-based clutch metrics, such as clutch minutes
played. This is acceptable: nearly every clutch metric worth publishing is
per-possession — clutch offensive rating, clutch eFG%, clutch usage — and
possessions are the correct denominator for all of them.

---

## 7. Re-ingest policy — approved

Store API responses as immutable, checksum-addressed versions. Record each
fetch observation, but deduplicate an identical body rather than storing the
same bytes repeatedly. Keep an explicit pointer to the current version. Never
overwrite response history.

When a checksum changes, rebuild the parsed raw rows and every derived row for
that game in one transaction. Do not rebuild the whole season for a one-game
source revision. A wholesale rebuild is reserved for a schema or transformation
rule change that can affect every game.

**Why.** A 30-game sample spread across E2024 re-fetched both cached endpoints,
60 responses in total. Zero byte checksums and zero canonical-JSON checksums
changed. That does not prove revisions never happen: the first snapshots were
already 440–674 days after the games and the second snapshots followed only
1.3–2.8 hours later. Versioning preserves the audit trail at zero duplicate-body
cost when responses are identical, while per-game rebuilds match the natural
scope of a source revision.

**Condition — measure settlement prospectively.** For one future season,
re-check completed games at +6 hours, +24 hours, +72 hours, and +7 days. Reduce
that provisional cadence only after those observations establish when revisions
actually settle. The E2024 experiment cannot supply a near-game settlement
time.

## 8. Backfill scope and storage capacity — approved with a gate

Archive all 23 available seasons and target all 23 for the core `raw_event`
shape. Drop `player_name`, `dorsal`, and `playinfo` from `raw_event`; do not move
them to a one-to-one side table. Recover their exact source values from the
immutable archived payload when an audit needs them.

**Why.** Across all 176,483 E2024 events, the actual logical value payload is
82.434 bytes per row with those columns and 51.572 without them. The three
columns consume 5,446,579 bytes, 37.44% of the full logical payload, while none
is used for identity, ordering, lineup reconstruction, or possession
boundaries. Twenty-three E2024-sized core seasons extrapolate to 209,337,306
logical value bytes; keeping the three fields raises that estimate to
334,608,623.

**Amendment, 2026-08-10 — the season count was never measured, and it was
wrong.** This item said 19 available seasons from the day it was written, and
`ROADMAP.md` flagged that no document in the repository had measured it. It has
now been measured: one schedule request per candidate season code, at the
8-second safe cadence.

**E2003 through E2026 all answer.** E2003–E2025 are complete, which is **23
seasons, not 19**. E2026 is the 2026-27 season — 380 games scheduled, zero
played. Probing started at E2003, so codes below it were never tested and 23 is
a floor rather than a ceiling. Two seasons carry real-world cancellations:
E2019 played 252 of 306 and E2021 played 299 of 327. E2024 returned exactly 330
played games, matching the validated baseline, which is what makes the rest of
the table trustworthy.

**The second error is worse than the count.** Every projection here treats a
season as E2024-sized. **E2024 is 330 games; E2025 is 402**, because the league
expanded to 20 teams, and E2026 already lists 380 regular-season games. A
current season is about 22% larger than the unit these estimates are built on,
so per-season figures understate it. **Cost per game is the honest unit.**
Re-derive these projections that way once E2025 is loaded and measured; do not
reuse the E2024 per-season figure for a modern season.

The gate below is unaffected in direction. It failed at 19 seasons and fails by
a wider margin at 23.

This corrects the earlier unmeasured statement that 19 seasons cannot fit in
500 MB. The logical values fit; physical PostgreSQL storage is still unknown.

**Condition — physical-size gate before production backfill.** Once DDL is
approved, load one complete season into a dedicated staging table with its real
primary key and measure table plus indexes with `pg_total_relation_size`.
Project the whole warehouse, not `raw_event` alone. If it exceeds 500 MB, keep
all 23 seasons in the immutable archive and reduce only the hot PostgreSQL
window. Do not invent that window size before the other tables and database
overhead are measured.

---

## 9. Where the immutable archive lives — Supabase Storage

The archived response bodies go into a Supabase Storage bucket in the project.
PostgreSQL stores the checksum, the fetch metadata and the object path. **It
never stores a response body**, so the archive costs nothing against the 500 MB
database quota.

**Why.** Measured, not assumed: the 660 cached E2024 responses are 52,381,257
bytes raw and **3,549,266 bytes when each file is gzipped individually** — a
14.76× ratio. Nineteen E2024-sized seasons therefore come to an **estimated
67 MB**, against a Storage free quota of 1 GB. The earlier worry that a
1 GB pile of raw JSON had nowhere to live was arithmetic on uncompressed bytes.

Per-file compression is the right number to quote here rather than a single
solid archive, because Decision 7 addresses bodies individually by checksum.
A solid `tar.gz` of the same 660 files is 3,242,269 bytes; the 9% difference is
the price of content-addressing, and it is worth paying.

The local disk cache stays exactly as CLAUDE.md requires. Storage is the
durable, CI-readable copy, not a replacement for it.

**Rejected:** committing gzipped seasons to git — every clone would carry the
whole archive and git handles opaque blobs that never diff badly. **Rejected:**
local disk alone — GitHub Actions cannot verify a checksum against a file it
cannot read, which makes the audit trail unenforceable in CI.

---

## 10. Migration tooling — plain SQL, applied through the Supabase MCP

Numbered `up` and `down` SQL files live in `migrations/`. They are applied
through the Supabase MCP against the project.

**Why.** Neither the Supabase CLI nor Docker is installed on the owner's
machine, and Docker Desktop is a heavy dependency to add to a project whose
owner cannot debug it when it breaks. Plain SQL files are also the artefact
that survives a change of tooling.

**How the ROADMAP gate is met.** "Migrations apply cleanly to an empty database
and roll back cleanly" is tested literally, and it can only be tested once:
apply every `up`, apply every `down`, apply every `up` again, all against the
project **before a single row exists in it**. Do this before Phase 4, because
after ingest the database is no longer empty and the gate can never be run
honestly again.

Supabase's own convention is forward-only migrations with no `down` files. We
write them anyway, because the gate requires them.

**Revisit if** local iteration becomes slow enough to be painful; a local
Postgres is then worth its install cost.

---

## 11. EuroCup — schema-ready, not loaded

`competition_code` exists on every table that needs it from the first
migration, so EuroCup lands in the same tables later with no schema change.
Nothing EuroCup is fetched, parsed or loaded before the October launch.

**Why.** CLAUDE.md names EuroCup in the project goal, but every measurement the
project owns counted EuroLeague only — the 176,483 events, the 500 MB
projection, the 19-season plan. Loading a second competition would roughly
double both the backfill fetch hours and the storage projection, against a
budget whose physical size is still unmeasured. The column costs nothing now;
the data can wait until the gate in item 8 has an answer.

---

## 12. The Supabase project

Created 2026-08-09: **`euroleague-analytics`**, ref `pctiewdpstnwcutrvegu`,
region `eu-central-1`, free plan, $0 per month.

Frankfurt because the owner is in Turkey and interactive queries from the MCP
server dominate latency-sensitive use; batch ETL from GitHub Actions does not
care where the database is.

**Two free-tier facts that are operational constraints, not trivia.**

- **An empty project already occupies 25,688,885 bytes.** Measured on this
  project on 2026-08-09 with `sum(pg_database_size(datname))` before a single
  table existed: `postgres` 10,415,104 bytes, `template1` 7,752,704,
  `template0` 7,521,077. The usable budget is therefore **474,311,115 bytes**,
  not 500,000,000, and item 8's arithmetic should be read with that reduction.
  This replaces an earlier "40–60 MB" figure taken from Supabase's
  documentation rather than from the project — the documented range describes
  projects with extensions installed, and is roughly twice what an untouched
  project actually uses.
- **Free projects pause after seven days of low activity.** A few queries a day
  prevents it. This is harmless during the August–September build, and the MCP
  server's own traffic should cover it after launch, but a quiet week in the
  off-season will pause the warehouse and it must be resumed by hand.

---

## 13. Public repository — and `CONTEXT.md` stays out of it

The repository is public on GitHub under the owner's own name. **`CONTEXT.md`
is untracked** and lives only on the owner's machine.

**Why public.** `CONTEXT.md` itself sets the goal: the repository is the CV, and
it is linked from the account bio. A visible trail of measurements, rejected
hypotheses and corrected mistakes is worth more to a club than a repository
that appears fully formed on launch day. Public repositories also get unlimited
GitHub Actions minutes, where private ones get 2,000 a month — a full backfill
could eat that.

**Why `CONTEXT.md` is the exception.** It is strategy, not method, and three
parts of it change meaning when strangers read them: it names the specific club
the owner wants to work for, which tells every other club they are second
choice; it names a real competing account and states an inferred reason for its
shutdowns, which is an unproven public allegation made under a real name; and
it states a hobby-scale budget while the repository is asking to be taken
seriously.

Nothing is lost from the public record. `DECISIONS.md`, `ROADMAP.md` and the
`exploration/` documents already carry the reasoning that demonstrates method,
which is the part that does the work.

**Consequence for agents.** `CLAUDE.md` points at `CONTEXT.md`, and in a fresh
clone it will be missing. That is expected. Ask for the goals rather than
inferring them from the code.

**Reversible.** Removing one line from `.gitignore` publishes it. The reverse
is not reversible, which is why the private direction was taken first.

---

## 14. How the test suite gets its data — committed fixtures, full season on demand

A small set of games is committed to `tests/fixtures/`. The full 330-game
validation runs on demand against the cache, and later against the Supabase
Storage archive.

**Why this was needed at all.** The cache is gitignored by item 9, so CI has no
data. A test suite that cannot run in CI is a test suite the owner has to
remember to run, and the entire validation architecture exists precisely
because he cannot catch errors by reading code.

**Why the fixtures are derived, not chosen.** The set is selected from
`exploration/sweep_results.json` by which defect each game carries — the
double-overtime game, the overlapping substitution batch, the games that
quarantine on minutes, the games the ±60 correction fires on, plus the
reference game. Each is committed with a note naming the defect it protects.
Hand-picking convenient games would reintroduce the n=1 reasoning that produced
the wrong offensive-foul rule.

**What this does not do.** Fixtures prove the logic handles the known hard
cases. They cannot prove a season-wide count. Any claim about a season number
must come from the full run, never from the fixtures.

---

## 15. How Python reaches Postgres — `psycopg` through the **session** pooler

Bulk loads use `psycopg` and the `COPY` command, addressed through **Supabase's
shared pooler in session mode**: the `...pooler.supabase.com` host on port
**5432**.

Supabase offers three connection strings and two of them are wrong here. This
item originally said "the pooler", which is ambiguous, and the ambiguity
immediately produced a `.env.example` showing the wrong port.

| String | Address | Verdict |
|---|---|---|
| Direct | `db.<ref>.supabase.co:5432` | No — IPv6-only on the free plan, and GitHub runners are IPv4-only. |
| Transaction pooler | `...pooler.supabase.com:6543` | No — no prepared statements. |
| **Session pooler** | `...pooler.supabase.com:5432` | **Yes** — IPv4, and otherwise behaves like a direct connection. |

**Why not the Supabase client.** `supabase-py` speaks to PostgREST over HTTPS,
which has no `COPY`. Loading 176,483 events would mean thousands of batched
insert requests: slow, and every batch is an opportunity to half-fail and leave
the table in a state no test anticipated.

**Why not the direct connection.** Free projects have no dedicated IPv4
address, and GitHub Actions runners are IPv4-only. Code pointed at the direct
host works on the owner's machine and fails only in CI. That is the worst
failure shape this project has.

**Why not the transaction pooler**, which is the one most guides reach for.
Transaction mode does not support prepared statements, and psycopg prepares a
statement automatically once it has seen the same query five times. A bulk load
would therefore succeed for the first few batches and begin failing partway
through — a failure that looks like our loader and is not. Transaction mode is
built for serverless functions issuing one query and disconnecting; this project
is one long-running process issuing large loads, which is what session mode is
for.

**Transaction mode is not impossible, and this is a policy rather than a
constraint.** It can be made to work by turning prepared statements off in the
driver — `prepare_threshold=None` in psycopg. We are choosing not to: one
enforced connection style is easier to reason about than two, and a project
whose owner cannot audit the code should not carry a second configuration whose
failure mode is a partial load.

**Enforced in code.** `DatabaseSettings` rejects both wrong strings with an
error naming the fix, so a mis-pasted connection string fails at startup rather
than halfway through loading a season.

---

## 16. Dependency tooling — `pip` and pinned requirements files

Exact versions pinned in `requirements.txt` and `requirements-dev.txt`.

**Why not `uv`.** It is faster and its lockfile is stronger. But the measured
dependency count is four — `requests` and `psycopg` at runtime, `pytest` and
`ruff` for development — because the entire 330-game sweep was written against
the standard library and imports nothing external. At four dependencies a
heavier tool buys reproducibility the pins already provide, and costs another
tool between the owner and code he is learning to read.

**Revisit if** the dependency list grows past roughly ten, or if a transitive
version conflict ever costs an afternoon.

---

## 17. `Points` is a coordinate source only — approved

Build every shot population from the play-by-play event stream. Archive
`Points` for its court coordinates and join it to the corresponding event by
the shared play number, but never count `Points` rows as the population of shot
attempts.

**Why.** `Points` omits missed free throws entirely. A query that counts shots
from `Points` and one that counts them from the event stream therefore return
different answers without raising an error. The event stream is the complete
source for attempts; `Points` contributes spatial fields only.

**Condition.** Any shot query that includes free throws must start from
`game_event`. `raw_shot` may be left-joined only to attach coordinates, and its
`(-1, -1)` free-throw sentinel must remain excluded from plotting and distance
calculations.

**Timing.** Settled 2026-08-09; first implemented 2026-08-10.

---

## 18. The MCP layer aggregates in views, not in pre-computed tables — approved with a measurement

`CLAUDE.md` requires the MCP server to be a thin query layer over pre-computed
tables with no heavy computation at query time. Nothing it needs is pre-computed,
and building those tables costs storage against a budget Phase 6 measured down to
four seasons.

Measured against the live warehouse: four factors for all 18 teams across a whole
season runs in 403 ms; the lineup on/off leaderboard in 98 ms; a clutch filter in
24 ms. Queries are season-scoped, so none of these grows as the archive deepens.

**Why.** The rule's purpose is to stop the server reconstructing lineups on
demand, which genuinely is heavy. Adding up one season is not. Views cost zero
bytes and their SQL is versioned like the rest of the schema.

**Condition — the measurement is the licence.** If any view is measured
materially above the 403 ms recorded here, promote that one view to a table rather
than widening this decision. The identified lever is an index on `possession
(season_code, gamecode, offense_team_code)`, which would remove the 366 ms
sequential scan that dominates the four-factors path.

**Also settled here: counting statistics are served from the official box score,
never recounted from events.** Recounting would create a second set of numbers
that can silently drift from euroleague.net after any change to event logic. Our
reconstruction is served where the official box score has no equivalent —
possessions, pace, lineups, on/off, clutch, and every per-100 rate.

**Timing.** Settled and first implemented 2026-08-12.

---

## Rules to add to the project instruction file

```
- Any correction rule tuned on one season must be re-measured on every
  new season, never assumed. A correction that increases disagreement
  with the official box score in any season must auto-disable for that
  season and fail its test.
- MCP responses involving minutes must state whether the value is raw or
  corrected. A number without its provenance is a number that will be
  misquoted.
- Shot queries spanning free throws must be built from `game_event`.
  `raw_shot` omits missed free throws entirely and is a coordinate
  source only.
- Possessions carry `margin_at_start` and `seconds_remaining_at_start`.
  Clutch is a filter on those columns, never a hard-coded threshold and
  never a separate pre-computed table.
- Report the measured rate of possessions straddling a substitution.
  A documented approximation without a measured magnitude is not
  documented.
```
