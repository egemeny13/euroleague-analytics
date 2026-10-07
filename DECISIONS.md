# Decision log

The settled decisions, one short entry each: what was decided, why, and the
condition attached. **A condition is binding; the decision holds only with it.**
Where this file and `CLAUDE.md` disagree, this file is newer and wins.

Entries were compressed on 2026-10-06 (Decision 90). The full original text —
measurements, rejected alternatives, provenance and approval records — is in git:
`git show 45d3040:DECISIONS.md`. Detailed evidence lives in the documents each
entry cites. Cite decisions by number; numbers are permanent and never reused.

New entries: keep them to the decision, the reason, the condition, and where the
evidence is. If it needs more than a screen, the detail belongs in `docs/`.

**Who decided, and when.** "Owner" is Egemen Yücelen. Dates are as recorded in
the original log (`git show 45d3040:DECISIONS.md`); "not recorded" means that log
preserved no approval.
- 1–16: owner, 2026-08-09 (8's season-count amendment, a measurement, 2026-08-10).
- 17: owner, 2026-08-10. 18: owner, 2026-08-12; re-measurement orders 7a and 7c
  approved 2026-08-24, 7b executed at the owner's request the same day.
- 19: no owner approval recorded (agent-implemented 2026-08-13).
- 20: owner, 2026-08-13; amended 2026-08-18; its conditions A and B closed
  2026-08-18 and 2026-08-19. 21, 22: owner, 2026-08-19.
- 23, 24: owner, 2026-08-24 (24's later production steps approved separately the
  same session). 25: owner, 2026-08-26. 26: owner, 2026-08-27.
- 27, 28: owner, 2026-08-28. 29, 30, 31: owner, 2026-08-29 (31 after being shown
  the stop condition it overrides).
- 32: owner's stated direction (a 2026-08-30 split-product proposal rejected).
  33, 35, 36, 37, 43, 44, 46, 51, 52, 54: approval not recorded.
  34: 2026-08-30, approval not recorded.
- 38, 39, 40: owner, 2026-08-31. 41, 42: owner, 2026-09-01.
- 45, 47, 48, 49, 50: owner, 2026-09-02. 53: owner, 2026-09-04.
- 54b: owner, 2026-09-05 (product subdomain). 55–58: 2026-09-04, owner-directed
  findings. 59: owner, 2026-09-05. 60–62, 64, 65, 66: owner, 2026-09-06; 63:
  2026-09-06, approval not recorded.
- 67, 68: owner, 2026-09-07 (Tiers A, B and D approved together in one message,
  which also satisfied "approval immediately before" the applies that followed).
  69, 71, 81: owner, 2026-09-07. 70, 72–77, 79, 80: 2026-09-07, under the
  derived-layer plan. 78: same plan; no separate owner sign-off recorded.
- 82: owner, 2026-09-16. 83: owner, 2026-09-18. 84, 85: owner, 2026-09-19.
- 86: owner, 2026-10-03. 87, 89, 90, 91: owner, 2026-10-06 (87's amendment the
  same day). 88: Claude, from measurement, 2026-10-06, on the owner's instruction;
  not yet reviewed by the owner.

---

## 1. Trim IDs and team codes in raw tables

Byte fidelity lives in the checksummed response archive; tables are trimmed so
joins cannot fail silently on padding. Owner, 2026-08-09.

## 2. Foul type comes from `PLAYTYPE`; offensive fouls are never inferred

The "foul + turnover at the same clock reading" rule measured 77.7 % precision
(340 invented turnovers in E2024) and is banned. Every `OF` has its own `TO`
row: count the `TO`, ignore the `OF`. Owner, 2026-08-09.

## 3. Corrected minutes are the default

A narrow correction (32 rows) cut box-score mismatches from 36 to 4; raw stays
alongside for positional logic.
**Conditions:** (A) every MCP response with minutes states raw or corrected;
(B) re-measure every season, and auto-disable with a failing test in any season
where the correction increases disagreement with the box score.

## 4. Stints are matchup-bounded

Either team substituting starts a new stint; the finer grain aggregates up, not
down. Substitution batches span first-to-last clock reading and absorb
intruders, checked with the union attribution window (0 on-court violations,
7 misattributed rows in E2024).

## 5. A straddling possession belongs to the lineup that started it

A convention, not a measurement.
**Condition:** publish the measured per-season straddle rate.

## 6. Clutch is a filter on possessions, not a split of stints

`possession` carries `margin_at_start` and `seconds_remaining_at_start`; callers
supply thresholds. No baked definition, no clutch table. Duration-based clutch
metrics are given up.

## 7. Responses are immutable, checksum-addressed versions

Record every fetch, store a body only when its checksum is new, keep a pointer to
the current version, never overwrite. A changed checksum rebuilds that one game's
raw and derived rows in one transaction; a wholesale rebuild is reserved for a
schema or transformation-rule change that can affect every game.
**Condition:** for one live season, re-check completed games at +6 h, +24 h,
+72 h and +7 d before reducing that cadence (`scripts/settlement_recheck.py`).
Evidence: `exploration/OPEN_ITEMS.md` item 7.

## 8. Archive every available season; drop event text from the hot tables

`player_name`, `dorsal` and `playinfo` (37.44 % of event payload) are not stored;
audits read the archive. Cost is quoted per game, not per season (E2024 has 330
games, E2025 402).
**Condition:** a physical-size gate before any production backfill; if the
warehouse does not fit, shrink the hot window, never the archive.
Amended by 52 (archive ends at E2007) and 68.

## 9. The archive lives in Supabase Storage, gzipped per file

PostgreSQL holds checksums and paths, never bodies. Per-file gzip is ~14.8×.
The local disk cache stays as the working copy.

## 10. Migrations are plain numbered up/down SQL files

Applied through the Supabase MCP, or the recorded script of Decision 81. Every
migration has a `down`; the gate is up/down/up on an empty database (Decision 44).
Revisit if local iteration becomes painful enough to justify a local Postgres.

## 11. EuroCup is schema-ready, not loaded

`competition_code` is on every table that needs it. Loading a second competition
needs a storage measurement first.

## 12. The Supabase project

`euroleague-analytics`, ref `pctiewdpstnwcutrvegu`, `eu-central-1`, free plan.
An empty project already uses 25,688,885 bytes, so the usable budget is
474,311,115. Free projects pause after seven idle days.

## 13. The repository is public; `CONTEXT.md` stays untracked

The repository is the owner's CV. `CONTEXT.md` holds strategy that must not be
public. In a clone it is missing: ask for the goals rather than infer them.

## 14. Tests run on committed defect fixtures; full seasons on demand

Fixtures are chosen by the defect each carries (`tests/fixtures/MANIFEST.json`).
A season-wide number must come from a full-season run, never from fixtures.

## 15. Python reaches Postgres with `psycopg` through the session pooler

`...pooler.supabase.com:5432`. Direct is IPv6-only (CI is IPv4); the transaction
pooler breaks prepared statements mid-load. `DatabaseSettings` rejects both.

## 16. Dependencies are pinned requirements files

Revisit if the list passes about ten or a version conflict costs an afternoon.

## 17. `Points` is a coordinate source only

Shot populations come from `game_event`; `raw_shot` is left-joined for
coordinates. It omits missed free throws.
**Condition:** any shot query including free throws starts from `game_event`;
the `(-1, -1)` sentinel stays out of plots and distances.

## 18. The MCP layer aggregates in views, not pre-computed tables

Views cost no storage; season-scoped queries measured 403 ms (four factors),
98 ms (lineup on/off) and 24 ms (clutch) in PostgreSQL execution. Counting stats
are served from the official box score, never recounted from events.
**Condition:** a view measured materially above its threshold is promoted to a
table individually; the decision is not widened. Re-measured 2026-08-24: clutch
re-earned (0.6–0.8 ms), lineup re-earned by a one-scan rewrite (88.5 ms); client
latency is a connection-lifecycle matter (single lazy connection, Order 7c).
Evidence: `docs/DECISION_18_REMEASUREMENT.md`,
`docs/LINEUP_ON_OFF_PERFORMANCE_DECISION.md`, `docs/MCP_CONNECTION_LIFECYCLE_REPORT.md`.

## 19. The game winner is derived in `v_game` from the final score

The source schedule's winner field is wrong (it repeats the champion). A tie
yields null. `raw_game.winner_team_code` stays null and is never back-filled.
**Condition:** the derivation lives in `v_game` and nowhere else; the gate asserts
E2024 has no ties, no winner who did not play, and no winner disagreeing with the
score. The in-place up/down/up equivalent of the empty-database gate holds only
for view-only migrations; a table change needs a fresh empty database.
No owner approval is recorded.

## 20. The hot window is E2024, E2025 and E2026

Amended 2026-08-18 from E2023–E2025 to include the live season. Measured cost
after compaction: 362,966 bytes per game whole-database; a complete E2026
projected to fit with 14.40 % headroom.
**Conditions:** (B) the size gate asserts this window and must fail if it stops
fitting — never relaxed, deleted or xfailed; (C) do not pre-build a
derived-only tier; (D) re-project against a complete E2026 before every
backfill and when the real game count is known. If it no longer fits, dropping
E2024 is a fresh owner decision, not an automatic fallback; nothing shrinks the
window silently at load time. The gate prices E2026 at its full 380 scheduled
games from day one, and keeps the inverted assertion that all 23 seasons must
*not* fit. Every tool that reports loaded seasons must say which are absent
rather than return an empty result.

## 21. The physical-size gate measures bytes per game within a band

Exact byte pins went red on correct growth. The band cannot see uniform growth
under 2.5 %; the fixed-budget window projection covers that.
Re-measured nightly since Decision 69.

## 22. Derived event references are attached on first insert, never by update

Parents first, then each `game_event` inserted once with all references; one
game is one transaction. Zero `UPDATE game_event` (it cost ~530k–670k dead rows
per season).
**Conditions:** merge by full primary key; a derived load runs zero
`UPDATE game_event`; incremental and single-pass loads produce identical rows.
Applies to every already-loaded derived table (Decision 76). The latent composite
`game_event_possession_fkey` defect stays separate; no migration repair is approved
here.

## 23. The public Data API exposes no warehouse view

All views are `security_invoker`; `anon` and `authenticated` have no grants.
**Condition:** any future public Data API feature is a separate product and
security decision with explicit grants, RLS policies, role tests and owner
approval. A security migration that changes a view definition, column signature
or served row is not this decision and stops for separate review.

## 24. Pre-season rosters keep source identity and registration grain

`roster_registration` stores one row per source registration; `person.code` is
kept as-is and never turned into a `player_id` by string surgery.
**Conditions:** cache and archive before parse; role `J` only; keep source array
position; reject a page shorter than its reported total; never update dimension
rows or insert `player`; RLS with no public policy or grant; production migration,
archive upload and load each need a separate attended approval.

## 25. Structural possession residuals do not weaken the possession gate

Tolerance stays 2; the 11 failing games stay quarantined. The structural
decomposition is diagnostic only.
**Condition:** recovering them is a new decision with all-season measurements.

## 26. The MCP server also serves StreamableHTTP, hosted and OAuth-protected

So testers never hold a database credential. The MCP SDK is scoped to
`requirements-http.txt`.
**Conditions:** HTTP publishes a tool list byte-identical to stdio (tested);
the hosted server connects as a role that cannot write; HTTP uses its own
connection pool; timeouts and a per-subject cap ship with it; `protocol.py`,
`scripts/mcp_server.py` and `ReadOnlyConnectionManager` stay unmodified (the
Order 7c latency evidence was measured through them).

## 27. Roster persons are linked to box-score players by within-game observation

`person_game_link` pairs people who appear in the same game's v2 stats and box
score. The `P`-prefix convention is a published check, never the rule that
creates a link.
**Conditions:** a test fails if any link came from string construction; publish
coverage and agreement rate wherever the link is used; a person who never played
stays unlinked; the storage projection is measured before the table is created
(Decision 28); backfill obeys the v2 host's backoff.

## 28. Hot window E2024–E2026 and the admitted reference data

Admits `person_game_link`, roster biography, venue/referee/club directories and
club season stats; excludes the global `/v2/people` directory. The compaction
precondition was withdrawn by Decision 30.
**Condition:** re-measure before EuroCup or any fourth season; the 480,000,000-byte
stop rule stands; measure after every step; a staging-table measurement with the
real primary key precedes creating `person_game_link`.

## 29. Clients connect through one shared public (Native, PKCE) Auth0 client

Dynamic registration hit the tenant's ten-application cap.
**Conditions:** the client id identifies the client only; who may sign in is a
separate control; replacement clients need explicit API authorisation; turn
Dynamic Client Registration off once the shared client is proven (done 2026-08-29,
see 51); the Auth0 tenant is labelled DEVELOPMENT and must be settled before a
public opening, not during one.

## 30. Compaction is not a precondition; the nightly storage watch governs the window

The compaction pilot failed its own gate. `src/euroleague/storage_watch.py`
reports headroom in games every night.
**Conditions:** at the warning level the response is an owner decision (paid tier
or a smaller window), never automatic; the stop rule is unchanged; no further
compaction write until the page-census discrepancy is understood. Compaction
stays available as a tool, only no longer a precondition.

## 31. The historical archive chain ran unattended

Switched off by Decision 52. Its in-job restore gate and the "refuse to guess"
season chooser remain the pattern for unattended archive work.

## 32. The hosted server is a portfolio project with its costs covered, not a product

No billing, tiers or per-season entitlements. The row budget and sweep refusal
are cost controls.
No second repository (33). The row budget and sweep refusal must be measured
before a public opening, not trusted.
**Conditions:** commercial use of league-derived data is unsettled; nothing that
sells proceeds before it is. If the collaborator arrangement does not happen, the
paid project does not exist and everything below E2024 stays archive-only.

## 33. Free and full offerings are one code base in two deployments

Two Supabase projects so the public one survives a sponsor leaving.
Amended by 37 (the archive stays on the free project).
**Condition:** if the free project cannot hold E2024–E2026 within 500 MB, the lever
is the number of seasons in the public hot window, never the archive; measure with
`pg_total_relation_size` first. The nightly E2026 job loading both hot windows is a
new partial-failure mode that needs explicit handling.

## 34. Tokens must name this server; `/userinfo` is not a way in

Audience and issuer are checked on every verification path; the userinfo
fallback is deleted. `MCP_REQUIRED_SCOPE` defaults empty until a real token has
been seen carrying it; the audience check has no such switch. Issuer and audience
compare by equality after trailing-slash normalisation, never by prefix. Refusal
reasons go to the log (no claim values), never to the client.
**Condition:** this removes one way in; it does not by itself make the server safe
to open. Who obtains a token and the row budget (32) remain separate controls.

## 35. The archive restore gate has a manual workflow

`.github/workflows/verify-archive-season.yml`, one named season, no schedule,
sharing the `e2026-live-fetcher` concurrency group.
**Condition:** if verification becomes part of archive completion state and the
chooser refuses unverified seasons, re-evaluate whether this workflow still earns
its keep.

## 36. An interrupted archive run is resumed, not refused

Fetchers restore through `restore_for_resume` (missing entries tolerated; extra or
duplicate current entries still raise). Gates keep the strict restore.
**Condition:** safe only while the completeness gate runs in the same job right
after the fetch.

## 37. The archive fits free Storage; a paid project waits for a sponsor

Gzipped, all seasons are ~118 MB of the 1 GB quota.
The paid project is created when a sponsor exists, not before; access is separated
by which database a deployment points at, never by per-user entitlement (32).
**Condition:** publish the stored total with each archive batch; past 500 MB,
stop and re-take this decision.

## 38. `define-goal` is opt-in

Only when the owner explicitly asks in the current request. Superseded by 49.

## 39. Season codes cover EuroLeague, EuroCup and SuperCup

`E####`, `U####`, `SC####`; v2 URL builders derive the competition path. Anything
else is rejected.

## 40. SuperCup live rehearsal

`SC2026` accepted by the live scripts through a manual-only workflow; settlement
re-checks stay E2026-only. Three games cost ~1.1 MB.

## 41. Small related changes share one milestone pull request

No direct pushes to `master`, no unrelated work in the branch, no unreviewably
large branch; tests stay green throughout; a merge is a production release.
**Lesson (2026-09-01):** a missing `fly-deploy.yml` was read as "the deploy is
gone" and nearly relaxed merge timing (the owner had approved PR #45 on that false
claim). The deploy is the `deploy` job in `ci.yml` (`flyctl deploy` on every push
to `main`/`master`, behind `needs: test`), and `pages.yml` also publishes on
`site/**`. When a named path is missing, search for the behaviour (`flyctl`), not
the filename.

## 42. A dropped Supabase Storage connection is retried

Up to four attempts (2/4/8 s) for failures before an answer; an HTTP status is
never retried.
**Condition:** retrying a status code, or widening the budget, is a new decision
backed by a measurement.

## 43. Testers get `el_tester`, a separate read-only role

Same reach as `el_reader` (views plus their base tables, `bypassrls`), so a
tester can be cut off without touching production's credential.
**Condition:** split into per-tester roles once one tester must be revoked alone
or the group grows past a handful. If RLS ever expresses a real per-row rule,
revisit `bypassrls`.

## 44. The migration gate runs in CI on PostgreSQL 17

Reads `EL_TEST_DATABASE_URL` through `load_test_database_settings`, which refuses
anything but `euroleague_test` on port 5433.
**Condition:** the literal credential in the workflow is safe only while the
database is a throwaway service container.

## 45. The launch was 2026-09-16

Chosen for the SuperCup audience, accepting that the live pipeline had not yet
met a real game. Quarantined games are excluded from every response by default.

## 46. Agent permissions are a committed file

`.claude/settings.json`: `allow` for local reads/edits/tests, `ask` for
remote-effecting commands, `deny` for deploys, destructive git and production
MCP writes. `-q` removed from `addopts`; pytest cache moved to `.tmp/`; an
undeclared third-party import fails the suite. Amended by 87.

## 47. Launch media lives in its own repository

Media production lives in
[`euroleague-analytics-launch`](https://github.com/egemeny13/euroleague-analytics-launch);
the website (`site/`), launch copy and claims stay here.
**Condition:** before a site deploy, thread or render, re-verify displayed tool
names and numbers against this repository.

## 48. Public opening keeps the baseline limits

120 calls/min per subject, 50,000 rows/day, 200 rows per response. The
invite-only Auth0 Action was unlinked on 2026-09-02 (R-9).

## 49. The flywheel skills are removed

`define-goal`, `dispatch`, `factory-doctor`, `goals-status`, `ideate`,
`loop-architect`, `process-inbox`, `show-me` must not be invoked. Restoring any
needs a new owner decision.

## 50. ChatGPT is a thin adapter over the same MCP server

Full standard read-only annotations and `outputSchema` on every tool; the only
OpenAI-specific piece is the optional `/.well-known/openai-apps-challenge` route.

## 51. A URL-only client gets the shared client id from a registration shim

With `MCP_OAUTH_PROXY_CLIENT_ID` set, this server serves OAuth metadata, a
registration endpoint returning the shared client id, and forwarding
authorize/token endpoints (`src/euroleague/mcp/oauth_proxy.py`).
**Condition:** the shim forwards and never decides; validating credentials,
issuing tokens or storing clients would make it an authorization server and needs
a new decision. It rewrites only `client_id` and `audience`. Registration at the
provider stays off (it was turned off 2026-08-29 after hitting the tenant's
ten-application cap).

## 52. The historical archive stops at E2007

E2006 and older return HTTP 200 with empty bodies. An empty body is a failed
target, never cached. The chain's schedule is removed. Moving the floor needs a
fresh measurement.

## 53. Website pages may carry Turkish; everything else stays English

`.html` under `site/` is exempt from the English-only scan; site scripts and
styles are not.

## 54. Launch claim tests guard consistency, not fixed sentences

Documents whose job is to state the verified figures must state them; any figure
a surface does state must be the verified one.

## 54b. Vercel serves branch previews only

The site's home is GitHub Pages at `euroleague.egemenyucelen.me`.
**Condition:** no custom domain is ever attached to the Vercel project.
(Numbered 54 twice in the original log; this is the second.)

## 55. `COORD_Y` is measured from the ring

Measured over 93,269 shots: the ring origin disagrees with the league's 2/3 flag
for 0.37 %, the baseline origin for 28 %. The baseline sits at `y = -157.5`.
No stored metric uses coordinates for distance or shot type.

## 56. Withdrawn

A claimed 4.5 % scale error was a misreading of the boundary. Kept for the
lesson: read a boundary off the mass of a distribution, not its first stray row.

## 57. The coordinate frame is settled; per-shot accuracy cannot be

Five court anchors (sideline, baseline, restricted area, free-throw line,
half-court) land within the 6.4 cm lattice. Validating a single shot would need
video, which is out of scope.

## 58. Some games are recorded a metre out; check a game against its season before drawing it

`scripts/build_site_shot_chart.py` refuses a game whose non-corner threes sit
more than 40 cm off its season median. Nothing is rescaled in the warehouse.

## 59. "Ask it something hard" is transcript from the running server

**Condition:** when loaded seasons change, re-run the cases against the server;
never edit the figures by hand.

## 60. The hero is a screen recording; the drawn window is its fallback

**Condition:** a recording is an upgrade, never a dependency (shown only after
`canplay`; reduced-motion shows the poster). Re-recording rules: no cursor, no
personal name, human typing pace, whole answer visible.

## 61. Site recordings follow one playback rule

The shot chart and floor stay scripts; the three hard-question clips are
recordings. Lazy-load, play only on screen, one at a time
(`site/demo-video.js`). Re-recording a clip means re-measuring the beats its
counters read.

## 62. The connect section leads with ChatGPT and says no assistant connects itself

**Condition:** each vendor path carries the date it was checked and is
re-checked on every site pass.

## 63. Player name lookup treats a hyphen and a space as the same

**Condition:** extend the fold only with a season-wide measurement of a new
spelling.

## 64. The Turkish page is `/tr/`, reached by a first-language redirect

Only `navigator.languages[0]` counts; `?lang=en` opts out permanently. Scripts
read their sentences from `data-text-*` (tested; a script sentence without its
Turkish key fails the test). If the host can read `Accept-Language`, the redirect
moves server-side; the storage key and `?lang=en` contract stay.

## 65. Version 1's tool surface is frozen

Season totals, standings and similar league surfaces are left out on purpose
(`docs/SCOPE.md`). Count amended to fourteen by 79.
**Condition:** a tool is added only with a decision here, a validation test with
ground truth or an invariant, and a `docs/SCOPE.md` row.

## 66. Four unused raw-layer indexes dropped (migration 0021)

**Condition:** the production apply follows the owner's approval immediately
before it, through the ledger, with `pg_total_relation_size` per table recorded
before and after in `docs/evidence/`; if a tool's production plan changes
unexpectedly, apply the down migration and reopen; re-measure after E2026 loads
(the rehearsal was one season).

## 67. Lineup-reference checks read `lineup_stint`; five indexes dropped (migration 0022)

**Condition:** a future need to filter `game_event` by lineup, stint or
possession gets its own index through a decision with a measured query.

## 68. The event stream is stored once: `raw_event` dropped (migration 0023)

The gate proves `game_event` against the parsed cache; `game_event_source` hashes
the eleven source columns. Amends 8 (the hot-window shape no longer includes
`raw_event`) and 21 (bytes per game re-measured on production once E2026 has
games; 20's window arithmetic redone from it). The down migration restores shape
only, never rows.
**Condition:** `game_event_source` checksums must match the recorded baselines
(E2024 `ed8de487…`, E2025 `45d38508…`); a difference is investigated, never
re-baselined. `events_parsed` must equal the `game_event` count for every game the
gate checks.

## 69. Per-game storage cost is measured every night

**Condition:** if the measured/assumed ratio leaves 0.8–1.2 for a week of loads,
update `BYTES_PER_GAME` with the date.

## 70. Fouls are served by type (`el_get_fouls`)

`committed` is defined as what the box score counts; matched 9,540 of 9,540
E2025 player-games. Coach/bench pseudo-ids never appear as players.
**Condition:** reconciliation stays at zero mismatches for every season; a new
`PLAYTYPE` fails a test and is a decision. Extended by 88.

## 71. The view migration gate can only reach the disposable database

**Condition:** every script that runs migration DDL reads `EL_TEST_DATABASE_URL`
through `load_test_database_settings`, never the live connection variable.

## 72. Possession end reasons and timeouts through existing tools

`el_get_possessions` gains `aggregate_by`; five end reasons sum to every
possession.
**Condition:** a sixth `end_reason` value fails a test and is a decision.

## 73. Player on/off accepts the possession clutch filters

Applied identically to both sides of the split. Validated by the invariant
on + off = team total.
**Condition:** re-run the rehearsal if lineup membership logic changes; the
invariant cannot see a possession on the wrong side.

## 74. Referee aggregates are an unpivot of games, keyed on referee code (`el_get_referee_stats`)

**Condition:** a referee code that stops identifying one person is a decision;
nothing detects it automatically.

## 75. Roster biography via the observed stat-line link (`el_get_roster`)

Rows are defined by the box score; biography is attached through
`person_game_link`, never by name.
**Condition:** row count equals distinct box-score players per season, and no
null birth dates; a season that breaks this needs its own decision.

## 76. Possession seconds are stored from `elapsed_seconds_raw`

Migrations 0027–0028. No ordering constraint: 0.29 % of E2024 possessions end
"before" they start, every one from a flagged backwards clock.
**Condition:** an ordering violation without a `clock_moved_backwards` event in
its span is a computation bug.

## 77. `free_throw_trip_id` stores the unsplit trip grouping

Unique within a game only. Whether some trips hold two foul awards is an
**open owner question** (it changes whether a technical free throw ends a
possession); see `docs/FREE_THROW_TRIP_GROUPING_REPORT.md`.
**Condition:** every `FTM`/`FTA` carries a trip id and nothing else does; a split,
if approved, arrives as a new decision through insert-time attachment.

## 78. League season totals are a validation oracle only

v3 team averages (rounded, half-increment tolerance) and v2 club exact totals
validate our sums; neither is stored in the warehouse or served. Named
exceptions: `KNOWN_ROUNDING_CASES` (six) and `KNOWN_LEAGUE_DISCREPANCIES` (three,
where the league's season page disagrees with its own box scores; we follow the
box score). Evidence: `docs/evidence/season_totals_oracle.json`.
**Condition:** both exception lists change only by a decision with a
measurement; tolerances are not widened without one; club totals stay disk-cache
only (archiving them needs a schema decision of its own). A recorded entry that
stops reproducing its numbers fails the test. No player-level oracle: the v3
player code is not our player id and is not bridged by guesswork.

## 79. Version 1 is frozen at fourteen tools

`el_get_fouls`, `el_get_referee_stats` and `el_get_roster` met Decision 65's
condition.

## 80. The view migration gate scopes columns to the schema and allows select grants on any object

**Condition:** it is the only sanctioned way to rehearse a view-only migration;
a rejected migration is either not view-only or a reason to amend this decision.

## 81. Migrations reach production through a recorded script

`scripts/apply_migration_with_evidence.py` applies an up file and its ledger row
in one transaction and records sizes in `docs/evidence/`. Owner's approval
immediately before each apply (Decision 87).
**Condition:** evidence and the ledger row land in the pull request that closes
the work; drift is reconciled by re-apply, never by editing the ledger.

## 82. The HTTP pool discards a dead connection

Connection errors close the connection and retry once on a fresh one.
**Condition:** re-examine if pooled connections ever run multi-statement
transactions.

## 83. The Turkish page has its own launch film cut

`site/launch-film-tr.mp4`; the other recordings are shared.

## 84. A kept multi-season schema on the local test database

`scripts/load_local_warehouse.py` loads several seasons into schema `warehouse`
on `euroleague_test:5433` for local projects. Only a successful load is kept;
an existing schema needs `--replace`. Never a production system.

## 85. E2020–E2022 load with three accepted source formats and five named skipped games

`N/D` referee token dropped; `TPOFF`, `F`, `BF` classified as not touching the
ball; shot loader reads played games only. E2020 games 16, 127, 273, 279 and
E2022 game 102 are skipped by name, not repaired.
**Condition:** each older season is measured the same way before loading.

## 86. The hosted MCP suspends when idle

Chosen by the owner to cut combined hosting cost, accepting wake-up latency:
`auto_stop_machines = 'suspend'`, `min_machines_running = 0`, one machine (the
running floor is not a machine-count ceiling). No monthly dollar cap is promised;
a cold start or release can still discard MCP sessions.
**Condition:** verify idle suspension, wake, health and OAuth metadata before
claiming success. Never verified: the machine did not suspend (see 89, 91);
superseded in setting by 91.

## 87. Sessions run in bypass-permissions mode

Agents run commands themselves; only `deny` rules still apply.
**What still binds:** branch work and pull requests; a merge to `master` waits for
the owner's go-ahead in the conversation; a production write needs the owner's
approval in the conversation immediately before it; tests are required and
nothing merges red (amended by 90); decisions land here in the same pull request.
**Open owner choice:** what `.claude/settings.json` should deny under bypass mode
— (1) leave as is, (2) deny `gh pr merge` and pushes to `master`, (3) also deny
production SQL tools. Until decided, option 1 stands.
**Amendment, 2026-10-06 (owner: "you should be able to run it too"): agents
read Fly state only through `scripts/fly_read.py`.** `Bash(flyctl:*)` and
`Bash(fly:*)` are denied outright; `Edit` and `Write` on the script are denied
too (the owner or a reviewed pull request made outside an agent session changes
it). The script maps seven names to fixed read commands against the fixed app;
the only free argument is a machine id (8-20 lowercase hex characters), never
run through a shell; `tests/test_fly_read.py` asserts what is built and what is
refused. A first form (read-only allow list plus a deny list of writing
subcommands, PR #111) was wrong: a deny list cannot be complete, and
`flyctl machines stop` would have passed. The script uses the operator's own
token, so the guarantee is only as good as its allow list; changing the list is
a change to this decision.
**The limit, stated plainly:** Bash permission rules match command prefixes and
are not a sandbox. `python -c "import subprocess; ..."` or a `sed` edit is not
stopped by these rules. They stop accidents and make the intended route the easy
one. The actual control is unchanged: a production write needs the owner's
approval immediately before it.
**Condition:** if an agent crosses a merge or production-write boundary without
approval, or the owner leaves bypass mode, option 2 or 3 becomes the default.
**Amendment, 2026-10-07 (owner, in Turkish: "I give permission for everything",
after repeated Supabase prompts):** the `ask` list in `.claude/settings.json` is removed and its
twelve rules (pushes, pull-request create/merge/close, workflow runs, merges,
rebases, `pip install`, and the read-side Supabase tools `execute_sql`,
`list_tables`, `query_logs`, `get_advisors`) move to `allow`. An `ask` rule
prompts even in bypass mode, which is what kept interrupting him. The `deny` list
is unchanged, so migrations, branch and project operations stay refused. The
conversation rules above are unchanged too: `execute_sql` can write, and a
production write still needs his approval immediately before it.

## 88. E2026 uses three new foul codes, each classified from measurement

`CMU_DI` (disruptive), `CMU_FL` (flagrant), `CMT1` (technical 1); E2026 has no
`CMU`, `CMT`, `CMD`, `CMTI`. All three count as committed fouls (719 of 719
player-games), are possession-retaining, and are served as separate columns
(migration 0029). `CMU_DI` is not disqualifying. Decided by Claude from
measurement; not yet reviewed by the owner.
**Condition:** re-measure as E2026 games arrive (30 games so far); an unknown
code stops the rebuild by design and is measured, never mapped by name.
`CMT1` is classified with `CMT` on two clean cases; a "Technical Foul 2" code, if
it appears, arrives as an unknown code and stops the rebuild. `CMU_FL` retention
rests on 5 resolved cases.

## 89. The hosted MCP runs without a Fly service health check

The 30 s `/healthz` check was the only recurring traffic and the suspected cause
of Decision 86's machine never suspending. `/healthz` is still served.
**Condition:** after deploy, the machine log must show a `suspension` event
within 15 minutes of idle; if not, revert this and try a machine on another host.
**Result, 2026-10-06: reverted; the check is restored.** The deploy updated the
same machine in place. Without the check it was still cordoned and uncordoned
without suspending, twice (19:55:27Z/19:55:49Z and 20:02:02Z/20:02:23Z), and the
app logged nothing in between. The health check was not the cause; the cause
points below the application, at the platform. Decision 86 stays unverified;
next step is 91.

## 90. The instruction file holds facts and boundaries; the project documents are kept short

Decided 2026-10-06 by the owner: current models do not need procedural
scaffolding, and the documents had grown past usefulness (`DECISIONS.md` 5,344
lines, `ROADMAP.md` 1,349).
- `CLAUDE.md` keeps every data fact, validation standard, architecture and MCP
  rule and the production boundaries; it drops line-by-line explanation,
  strict test-first ordering, one-task-per-session, handoff re-verification,
  most tooling tips and incident narratives.
- `AGENTS.md` is a byte-identical copy of `CLAUDE.md`, enforced by
  `tests/test_documentation_integrity.py`. Edit `CLAUDE.md`, then
  `cp CLAUDE.md AGENTS.md`.
- This file is compressed to one short entry per decision; `ROADMAP.md` is
  rewritten as current state and open work. Full history stays in git
  (`45d3040`). Tests that pinned historical sentences in these two files were
  retired; the evidence documents they also checked are still pinned.
- Unchanged: production writes and merges need the owner's approval in the
  conversation; decisions land here in the same pull request.

**Condition:** if an agent repeats a mistake one of the removed rules described,
restore that rule with the incident.

## 91. The hosted MCP stops, not suspends, when idle

Decided 2026-10-06 by the owner, choosing (a) of three put to them after 89 was
reverted: (a) stop instead of suspend, (b) clone the machine to another host,
(c) ask on the Fly community forum. `fly.toml` now has
`auto_stop_machines = 'stop'`.
**Why:** Decision 86's `suspend` never took effect; the proxy cordoned the
machine every ~6 minutes and flyd uncordoned it ~20 s later, with and without
the health check, with no open connections and nothing in the app log.
Suspension depends on a platform VM snapshot; stopping does not.
**What it gives up:** a start is a fresh process, so an MCP session open before
idle does not survive it (clients must reconnect), and the first request after
idle waits for a full start (3.9-7.8 s observed on 2026-10-06, against the 0.5 s
resume 86 hoped for). Everything else in 86 stands: one machine,
`min_machines_running = 0` as a floor, no promised dollar cap.
**Condition:** after the deploy, the machine event log must show a `stop` event
after idle. If it shows `cordon` then `uncordon` with no `stop`, the cause is
not the suspend mechanism: revert to the last setting that worked and take
option (b) or (c). 86's "verify idle suspension" becomes "verify idle stop".
**Result, 2026-10-06: reverted.** Deployed 20:39Z.
- **Same failure as suspend.** With `stop`, the machine was cordoned and
  uncordoned with no `stop` at 20:51-20:52Z, 20:58Z and 21:04Z. So the cause
  is not the suspend mechanism.
- **No setting has worked, so `suspend` is restored.** `stop` would cost every
  open MCP session and gain nothing.
- **What the agent cannot do.** Option (b), a machine on another host, needs a
  `flyctl` write. Agents are denied that (Decision 87), and it needs the
  owner's approval. Option (c), the Fly forum, needs the owner's account. Both
  wait for the owner.
- **Cost meanwhile.** The machine runs always-on, as it did before 86, at
  about $2 a month.

## 92. The website and its film are rebuilt from scratch around one message

Owner, 2026-10-07: the site and the promo did not make a stranger understand
the product or want it; rebuild both, reusing nothing of the old design. The
message is "Your AI knows the score. Now it knows why." The page sells the
visitor's gain first (questions a box score cannot answer), then shows the
proof, then the two-minute setup.
- **Design.** One self-hosted OFL typeface (Archivo, variable width), paper and
  ink, one accent that marks only answers from the data and the connect
  action. `test_the_accent_colour_is_spent_only_on_answers_and_actions` holds
  the accent to that list.
- **Figures.** Every number on the page and in the film was read from the
  warehouse views on 2026-10-07 for E2025 with quarantined games excluded, using
  the grouping of the matching MCP tool (lineups, on/off, possessions, team
  games, referee games). The hero is E2025 game 406, the 2026 final. The shot
  chart is that game's checksum-verified `Points` archive, built by
  `scripts/build_site_shot_chart.py` (Decision 58 check: +3 cm). The two/three
  tallies use the league's shot type, never coordinates.
- **Supersedes** the site parts of Decisions 59, 60, 61 and 83: no screen
  recordings, no hard-question clips, no launch film on the page. The film is
  `site/film.mp4` (English) and `site/film-tr.mp4` (Turkish), one HyperFrames
  composition rendered per language. Decisions 53 and 64 stand: the Turkish
  page is `/tr/`, reached by the first-language redirect, and scripts hold no
  copy (now tested by `test_site_scripts_hold_no_copy`).
- **Kept for others:** `site/launch-film.mp4` stays published because the
  ChatGPT directory submission names it as the demo recording.
- **Connect steps** (Decision 62's condition): Claude re-checked against its
  help centre on 2026-10-07; ChatGPT against current secondary guides the same
  day (OpenAI's own page was not reachable); Gemini still carries its
  2026-09-06 date.
- **Music.** The film's bed was generated locally with Meta's MusicGen
  (medium). Its weights are licensed CC-BY-NC 4.0; the project is
  non-commercial, but if a sponsorship (see CONTEXT) is ever judged commercial,
  replace the bed with a licensed track. The composition renders silent and the
  bed is mixed in afterwards, so a swap is one ffmpeg command, not a re-render.
- **Source.** The composition lives outside this repository (launch media,
  Decision 47) at `E:\dev\euroleague-film\film`.
**Condition:** when the loaded seasons change, re-query every figure on both
pages and in the film; never edit one by hand. The Turkish page's figures are
tested equal to the English page's.
