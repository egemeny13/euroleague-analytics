# Open items — handover verification and decisions 7–8

**Measured 2026-08-09.** No DDL, migrations, production writes, or changes to
the existing cache were made.

The definitions of Items 7 and 8 below come from `DECISIONS.md` and
`ROADMAP.md`. `AGENTS.md`, `CLAUDE.md`, both of those files, and
`exploration/FINDINGS.md`, `exploration/SEASON_SWEEP.md`, and
`exploration/SCHEMA_PROPOSAL.md` were read in full. `AGENTS.md` is a pointer to
`CLAUDE.md`, not a second copy of the rules.

## Handover questions

### 1. The three silent-corruption rules

1. **Preserve the API arrays exactly and order only by our `ingest_index`.**
   Never sort events by `MARKERTIME` or `NUMBEROFPLAY`. The clock has collisions
   and backwards steps, while `NUMBEROFPLAY` is entry order and has 2,169
   inversions in E2024. Breaking this rule quietly assigns events,
   possessions, and stint results to the wrong lineup. The output can still
   contain five plausible players and plausible totals, so there need not be
   an exception or an obviously absurd result.
2. **Trim every string on ingest and join entities by opaque ID, never by
   name.** Play-by-play team codes and player IDs are padded while equivalent
   box-score fields are not, and names vary in spelling. Breaking this rule
   makes joins return no match without raising an error. Downstream dimensions
   become null or rows disappear from aggregates, silently understating player
   and team results.
3. **Build a shot population that includes free throws from `game_event`; use
   `raw_shot` only to attach coordinates.** `Points`/`raw_shot` omits every
   missed free throw. Breaking this rule silently undercounts attempts and
   changes percentages and possession-related totals while the query itself
   succeeds.

### 2. `raw` versus `corrected` minutes

`raw` is duration calculated from the timestamps exactly as the API published
them. `corrected` applies only the narrow, measured rule that re-times
overtime-tip substitutions by +60 seconds. It changes elapsed times and
durations, never array order, lineup membership, event attribution, or
possession membership.

**`corrected` is the default for minutes and per-minute rates.** `raw` remains
beside it and is the positional provenance. Every response involving minutes
must say which one it used.

### 3. Why `numberofplay` is stored

It is a join key. `Points.NUM_ANOT` joins shot coordinates to
`PlayByPlay.NUMBEROFPLAY`. It is unique and non-null within every E2024 game,
but it is out of sequence in every game, so it must never be treated as an
ordering key.

---

# Measurements

## Item 7 — re-ingest policy

### Method

- Population: the 330 cached E2024 games.
- Sample: 30 games at equal positions after sorting the season schedule by UTC
  game date and then game code.
- Coverage: game 1 on 2024-10-03 through game 330 on 2025-05-25; rounds 1–43;
  Regular Season, Play-In, Playoffs, and Final Four.
- Game codes: `1, 12, 23, 35, 46, 57, 69, 80, 97, 103, 113, 126, 141, 149,
  161, 172, 184, 195, 205, 218, 229, 240, 251, 262, 273, 285, 296, 308, 318,
  330`.
- Endpoints: both cached endpoint types, `Boxscore` and `PlaybyPlay`, for 60
  response comparisons.
- Each current response was written untouched to a temporary archive before it
  was parsed or compared.
- Two comparisons were made: SHA-256 of the exact response bytes and SHA-256
  after canonical JSON encoding. The second distinguishes a data change from
  whitespace or property-order changes.
- The existing cached files were not overwritten.

### Results

| Measure | Result |
|---|---:|
| Games sampled | 30 |
| Responses compared | 60 |
| HTTP or JSON failures | 0 |
| Exact-byte checksum changes | **0** |
| Canonical-JSON changes | **0** |
| Changed games | **0 of 30** |
| Changed `Boxscore` responses | **0 of 30** |
| Changed `PlaybyPlay` responses | **0 of 30** |
| Sample bytes compared | 4,865,884 |
| Re-fetch wall time at the safe request cadence | 540.4 seconds |

The checksum manifest — SHA-256 over sorted lines of
`gamecode`, endpoint, and per-response SHA-256 — was identical for the cached
and current sets:

```text
37e209690e517bcb7d9ba1b85139028a8c842c0ad8fff8d8e867b46f94927731
```

There is therefore no changed field, row, event order, score, minute, player
line, or formatting to report in this sample.

The API does not expose a useful revision validator. No response had an
`ETag`. `PlaybyPlay` supplied no `Last-Modified`; every `Boxscore`
`Last-Modified` value equalled that request's `Date` header, so it describes
response generation rather than the age of the underlying game data.

### What this measures — and what it cannot measure

The cached season was first fetched only shortly before this re-check. Depending
on the sampled file, the interval between cache write and re-fetch was **1.31
to 2.81 hours**. At the time of the first snapshot the games were already
**440.23 to 674.17 days old**.

The only defensible settlement statement is therefore:

> In this sample, responses aged 440–674 days were stable across a second
> observation 1.3–2.8 hours later.

This proves that old responses are not rewritten on every request. It does
**not** measure whether corrections settle after 6 hours, 24 hours, 3 days, or
30 days. Determining that lag requires snapshots beginning immediately after a
future game. Any more precise settlement time stated from this experiment
would be an estimate disguised as a measurement.

### Measured archive and request costs

The existing full-season archive for the two measured endpoints is:

| Endpoint | Responses | Bytes |
|---|---:|---:|
| `Boxscore` | 330 | 4,490,227 |
| `PlaybyPlay` | 330 | 47,891,030 |
| **Total** | **660** | **52,381,257** |

One 30-game re-check took 9.0 minutes. A full 330-game re-check at the same
cadence is **estimated**, not measured, at about 99 minutes by linear
extrapolation.

## Item 8 — backfill scope and storage

### Measurement boundary

There is no table or approved DDL yet. Physical PostgreSQL size depends on the
eventual column types and order, tuple headers, null bitmap, alignment, TOAST,
page fill, and indexes. No EuroLeague Supabase project exists in the configured
account, and unrelated projects were not used. Consequently, physical
`pg_total_relation_size` is **not measured here**.

The exact measurement below is the logical value payload for every proposed
`raw_event` row:

- all 176,483 E2024 events across all 330 games;
- strings trimmed as the approved schema requires and counted as their actual
  UTF-8 byte length;
- each non-null integer counted as four bytes;
- null values counted as zero value bytes;
- with and without `player_name`, `dorsal`, and `playinfo`;
- no JSON property names, CSV delimiters, tuple/page overhead, or indexes.

This is the only actual row-byte measurement possible before types and a table
exist. It must not be presented as physical Postgres disk usage.

### Actual E2024 bytes

| `raw_event` option | Rows | Total value bytes | Mean bytes/row | Median | P95 | Minimum | Maximum |
|---|---:|---:|---:|---:|---:|---:|---:|
| With all three columns | 176,483 | **14,548,201** | **82.434** | 79 | 105 | 40 | 114 |
| Without all three | 176,483 | **9,101,622** | **51.572** | 51 | 60 | 32 | 61 |

The three columns add **5,446,579 bytes**, or **30.862 bytes per event**. They
are 37.44% of the full logical value payload.

| Optional column | Non-null rows | Actual E2024 bytes | Bytes per all rows | Mean bytes when present |
|---|---:|---:|---:|---:|
| `player_name` | 166,559 | 2,460,945 | 13.944 | 14.775 |
| `dorsal` | 166,559 | 270,412 | 1.532 | 1.624 |
| `playinfo` | 176,154 | 2,715,222 | 15.385 | 15.414 |

### Nineteen-season and 500 MB extrapolations

For this section, **500 MB means exactly 500,000,000 bytes**, not 500 MiB.

The following are **estimates**, because they multiply one measured E2024
season by 19 and assume every season has the same 176,483 rows and the same
value-length distribution. They exclude PostgreSQL and index overhead.

| `raw_event` option | Measured bytes in E2024 | **Estimated** bytes for 19 E2024-sized seasons | Share of 500 MB | E2024-sized seasons whose logical values fit in 500 MB |
|---|---:|---:|---:|---:|
| With all three columns | 14,548,201 | **276,415,819** | 55.28% | **34** complete seasons |
| Without all three | 9,101,622 | **172,930,818** | 34.59% | **54** complete seasons |

Dropping the three columns saves an **estimated 103,485,001 bytes** across 19
E2024-sized seasons.

These are not claims that 34 or 54 physical PostgreSQL seasons fit. The actual
physical capacity will be lower and must be measured with
`pg_total_relation_size`, including the primary key index, after DDL is
approved. The 500 MB budget for the whole warehouse also has to include every
other raw and derived table; this experiment measured `raw_event` only.

---

# Recommendations

## Decision 7 — append-only response versions, selective rebuilds

**Recommend versioning, not overwrite.** Treat a response as immutable and key
its body by content checksum. Record `fetched_at` for every observation, but
store a second body only when its checksum differs. Keep a current-version
pointer for normal ingest.

Why:

- Overwrite would destroy the evidence needed to explain why a derived number
  changed and would contradict the proposed meaning of `raw_api_response` as
  one response the project actually received.
- Storing an identical body repeatedly wastes space. Content-addressed
  deduplication retains the observation history without duplicating the bytes.
- The experiment found zero revisions, but its observation window was too late
  to justify assuming revisions never occur.

**Re-fetch cadence:** for future games, take the initial final-game snapshot,
then re-check at +6 hours, +24 hours, +72 hours, and +7 days for one season so
the settlement curve is finally measured. This cadence is a **provisional
policy estimate**, not a finding from E2024. After that season, remove
checkpoints that never catch a change and keep the last checkpoint after which
no revisions were observed. Historical games need only one audit re-fetch,
because repeated checks of 440-day-old data add little evidence.

**Rebuild per game when a checksum changes.** Replace that game's parsed raw
rows from the new current version and rebuild that game's `game_event`,
minutes, quality, stints, possessions, and game-grain metrics in one
transaction. Do not rebuild the whole season for a one-game source revision.
Season aggregates should update from the changed game; a wholesale rebuild is
reserved for a transformation-rule or schema change that can affect every
game.

**Cost:**

- In the measured sample, versioning adds **zero body bytes** because 0 of 60
  bodies changed; it adds only observation metadata and checksums.
- One additional full-season body version would cost at most the measured
  **52,381,257 bytes** for the two currently cached endpoints if every response
  changed once. Real cost is proportional to changed responses.
- The proposed four post-final re-checks are **estimated** at 2,640 requests per
  330-game season (two endpoints × four checks × 330), spread across the
  season. At the measured safe cadence that is about six request-hours in
  total, not six wall-clock hours at once.
- A changed game rebuild costs roughly one game's work rather than 330 games'
  work. That ratio is architectural; actual CPU time remains unmeasured until
  the derived pipeline exists.

## Decision 8 — archive all seasons; keep the event table lean

> **⚠️ The "19 seasons" in this section was never measured, and it is wrong.**
> Measured on 2026-08-10: the API serves E2003–E2026, so **23 complete seasons**
> exist (E2003–E2025), and 23 is a floor because codes below E2003 were not
> probed. Seasons are also not all E2024-sized — E2024 is 330 games, E2025 is
> 402. Every per-season extrapolation below therefore uses both the wrong count
> and a unit that is ~22% too small for a current season. `DECISIONS.md` item 8
> carries the corrected figures and is authoritative. The text below is retained
> as the Phase 1 record.

**Recommend backfilling all available seasons into the immutable response
archive and into the core `raw_event` shape, subject to a physical-size gate
when DDL is approved.** The measured logical values for 19 E2024-sized core
seasons are 172.93 MB, leaving 327.07 MB of the stated 500 MB before physical
overhead and other tables. Older seasons should be fetched and cached before
parsing so the project preserves the source even if only a subset can remain
hot in Postgres.

The gate is concrete: load one complete season into a dedicated staging table
with its real primary key, measure table plus indexes with
`pg_total_relation_size`, and project the full warehouse. If the complete
warehouse—not merely `raw_event`—would exceed 500 MB, keep all 19 seasons in
the archive and reduce the hot Postgres window. Choosing that hot-window count
now would be an estimate because no other table has been measured.

**Drop `player_name`, `dorsal`, and `playinfo` from `raw_event`; do not create a
one-to-one side table. Recover their exact source values from the archived
payload when debugging requires them.**

Why:

- They consume 37.44% of the measured logical value bytes but are not used for
  identity, ordering, lineup reconstruction, or possession boundaries.
- `player_name` is unsafe for joins; the stable player ID and player dimension
  are the query path.
- `dorsal` is descriptive and is also available at player-game grain from the
  box score.
- `playinfo` is descriptive text. Its apparent free-throw fractions are
  cumulative player game totals, not free-throw trip position, so keeping it
  does not solve the fragile inference.
- A one-to-one side table repeats the event key and adds another table and
  index; physical savings could be smaller than simply retaining the columns.
  A deduplicated side table would add mapping complexity while the untouched
  response archive already preserves the exact bytes.

The trade-off is deliberate: ad hoc SQL cannot search those three source
strings. An audit must open one archived game payload and use `ingest_index` to
locate the event. That is acceptable for debugging fields and saves an
estimated 103.49 MB of logical values across 19 E2024-sized seasons. If a
future requirement makes any field part of a validated metric, it can be
recovered and backfilled losslessly from the archive.

## Resolved choices

| Item | Choice |
|---|---|
| 7 — response handling | Immutable, checksum-addressed versions; deduplicate identical bodies; never overwrite history |
| 7 — rebuild scope | Per-game rebuild on source revision; wholesale only for cross-season logic/schema changes |
| 8 — backfill | Archive all seasons and target all of them for core `raw_event`, with a physical staging-size gate before production load. The count said 19 here; it was measured as 23 on 2026-08-10 — see `DECISIONS.md` item 8 |
| 8 — optional event text | Drop `player_name`, `dorsal`, and `playinfo` from `raw_event`; no side table; recover from archived payload on demand |
