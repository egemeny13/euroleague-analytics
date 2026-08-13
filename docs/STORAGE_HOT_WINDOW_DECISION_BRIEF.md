# Storage hot-window decision brief

**Cost basis: billing-aware whole-database growth, measured live on 2026-08-13.**
This is the basis that matches the 500 MB Supabase limit: the sum of
`pg_database_size` for every database in the project, less the measured empty
project baseline. It includes the public tables and indexes, PostgreSQL system
relations, catalogue growth, and other database space that Supabase counts. The
older Phase 5 and Phase 6 figures were measured on different bases and are not
used in any projection below.

This document measures and recommends. It does **not** choose or implement the
hot window. That decision remains with the owner.

## Season counts

Exactly two EuroLeague API requests were made in this session: one schedule
request for E2022 and one for E2023, 9.67 seconds apart. Both returned HTTP 200
on the first attempt, were written unchanged through the production cache path,
and were recorded in `exploration/cache/fetch_log.jsonl`. E2024 and E2025 were
read from their existing cached schedules.

| Season | Scheduled games | Played games | Unplayed games | Evidence |
|---|---:|---:|---:|---|
| E2025 | 402 | **402** | 0 | Existing cached schedule |
| E2024 | 330 | **330** | 0 | Existing cached schedule and loaded warehouse |
| E2023 | 331 | **331** | 0 | Fresh archived schedule response |
| E2022 | 328 | **328** | 0 | Fresh archived schedule response |
| **Total** | **1,391** | **1,391** | **0** | Sum of the four measured rows |

The two new exact response checksums are:

- E2022: `4cb7c6d8aad3824be5b1a6f04e2427653fea3e36c363cc4e0d69c701f0cc283a`
- E2023: `ae1af5bc9abbc8e1fed27b61799a10aae53e2ca200b0aa977231c6e024f722cc`

This table is the durable repository record that the earlier season-count
measurement lacked.

## Live cost measurement

The live database contains only E2024, fully loaded through possessions:
330 games, 176,483 `raw_event` rows, 176,483 `game_event` rows, and 47,831
`possession` rows. One read-only SQL statement measured:

| Billing-aware component | Bytes |
|---|---:|
| Current whole project | 134,822,709 |
| Fixed empty-project overhead | 25,688,885 |
| E2024 data-driven growth | **109,133,824** |

The cost used everywhere below is therefore:

```text
109,133,824 bytes / 330 games = 330,708.5576 bytes per game
projected bytes = 25,688,885 fixed bytes + games x cost per game
```

The free-tier ceiling is 500,000,000 bytes. After the fixed empty-project
overhead, the usable data budget is **474,311,115 bytes**. Headroom below means
unused space under the full 500,000,000-byte ceiling; it is not treated as
available season capacity because PostgreSQL grows through ordinary operation.

### Price of the event layer

The same live snapshot measured `raw_event` at 31,383,552 bytes and
`game_event` at 51,560,448 bytes. On the same per-game basis:

| E2024 component | Bytes per game | Share of data-driven whole-database growth |
|---|---:|---:|
| `raw_event` | 95,101.6727 | 28.76% |
| `game_event` | 156,243.7818 | 47.25% |
| Everything retained by the proposed derived-only tier | **79,363.1030** | **24.00%** |

Dropping only `raw_event` would not create a season with no queryable event
rows: `game_event` is the MCP play-by-play source and is larger. The layer-split
option therefore omits **both** event relations for older seasons, after using
the archived payloads to build and validate lineups, possessions, minutes, game
quality, and box-score rows. The archive remains the source from which an older
season could be rebuilt. The estimate is conservative at small scale because
it allocates the relation files' fixed pages per game rather than counting them
only once.

## Exactly three free-tier options

Megabytes are decimal MB, matching Supabase's 500,000,000-byte limit. Project
total includes the 25.689 MB fixed overhead.

| Option | Seasons and layer | Total games | Data MB | Project total MB | Headroom left | Analysis that becomes impossible |
|---|---|---:|---:|---:|---:|---|
| **1. Three complete seasons** | E2025, E2024, E2023: every relation | 1,063 | 351.543 | **377.232** | **122.768 MB (24.55%)** | All ten published E2024 evaluations survive, and their question shapes remain possible for the three loaded seasons. E2022 is absent, so every E2022 version is impossible; for example, evaluation 1 cannot identify E2022's best 150-possession lineup. |
| **2. Four complete seasons** | E2025, E2024, E2023, E2022: every relation | 1,391 | 460.016 | **485.704** | **14.296 MB (2.86%)** | All ten evaluation question shapes survive for all four seasons. Nothing among them becomes impossible, but the option leaves too little operating space for table growth, new games, vacuum debt, or schema changes. |
| **3. Four seasons with an older derived-only tier** | E2025 and E2024 complete; E2023 and E2022 keep lineups, possessions, minutes, quality, dimensions, games, and box scores but no `raw_event` or `game_event` | 1,391 | 294.379 | **320.068** | **179.932 MB (35.99%)** | All ten published E2024 evaluations survive. For E2022 and E2023, evaluation 10's final five scoring events in source order becomes impossible in Postgres, and evaluation 7 can no longer count the winner's fourth-quarter made-shot event types. The other eight derived/box-score question shapes remain possible. |

Option 2 technically fits but uses 97.14% of the total limit. It is a boundary
demonstration, not an operational plan. Option 1 leaves a reasonable buffer by
giving up a whole season. Option 3 changes the storage kind instead: it retains
four-season analytical depth while reserving more space than Option 1.

## Supabase Pro, priced separately

As checked against Supabase's current official pricing on 2026-08-13, Pro is
**$25 per month** for the organization, before tax and any overages. It includes
8 GB of general-purpose database disk per project and $10 per month of compute
credits, which covers one Micro project at the listed rate. Storage beyond the
included 8 GB is currently $0.125 per GB-month. Sources:
[Supabase pricing](https://supabase.com/pricing) and
[disk-size billing](https://supabase.com/docs/guides/platform/manage-your-usage/disk-size).

At the measured 330,708.5576 bytes per game, all 23 complete seasons already
known to the API (5,950 played games) project to **1.993 GB including fixed
overhead**. That is about 24.92% of the included 8 GB, leaving approximately
6.007 GB before later growth. Pro would therefore buy the simple design: all
23 seasons complete in Postgres, no hot-window or layer-split policy, no weekly
inactivity pause, and substantially more room for EuroCup and future seasons.
Its $25 monthly price is 2.5 to 5 times the owner's stated $5-10 monthly budget,
so it is not the recommendation.

## Recommendation

**Recommend Option 3: E2025 and E2024 complete, with E2023 and E2022
derived-only.** It costs $0 per month, holds four named seasons, and leaves
179.932 MB of headroom. What the owner permanently gives up while this policy
is in force is direct event-level analysis of E2022 and E2023 through Postgres
and the MCP server: source-order sequences, historical play-by-play browsing,
and new derived questions that require event rows cannot run without first
rebuilding those seasons from the immutable archive. The response bodies are
not lost, but immediate queryability is.

This recommendation becomes wrong if historical source-order or event-level
research becomes a regular portfolio requirement; if a dry-run of the split
load shows that retained derived rows cannot be validated or safely maintained
without resident event rows; if a second full-season measurement shows the
per-game model understates real growth enough to consume the 179.932 MB buffer;
or if the monthly budget rises to $25, at which point Pro removes the storage
trade-off and is the cleaner design. Re-measure after E2025 is fully loaded and
again before adding another competition.

## Scope and decision gate

This session wrote no database table, loaded no season, dropped no relation,
changed no metric, test, query, or gate, and did not alter
`test_live_phase_4_gate`. The only live database operation was the read-only
measurement query. No hot window has been implemented.

**Owner decision required:** choose Option 1, Option 2, Option 3, or reject the
recommendation before any backfill or storage-policy implementation begins.
