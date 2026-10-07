# Roadmap

Where the project stands and what is still open. Decisions and their conditions
are in `DECISIONS.md`; the rules are in `CLAUDE.md`. The phase-by-phase history
(Phases 0–8, Orders 1–9, R-1 to R-14, Blocks B–E) was removed on 2026-10-06
(Decision 90); read it with `git show 45d3040:ROADMAP.md`, and the per-phase
reports in `docs/`.

Keep this file short: current state, open work, and gates. When an item is done,
delete it and, if it changed what the system does, record it in `DECISIONS.md`.

---

## Current state — 2026-10-06

- **MCP server:** 17 read-only `el_` tools in the repository (Decision 93;
  list in `docs/SCOPE.md`); the hosted release still has fourteen pending approval.
  The original surface is served over stdio and hosted
  StreamableHTTP on Fly (`euroleague-analytics-mcp`), OAuth through Auth0,
  open to public sign-in since 2026-09-02.
- **Hot warehouse (Supabase free tier):** E2024 and E2025 complete; E2026 loading
  nightly through `.github/workflows/e2026-live.yml` (first game 2026-09-24).
  Games that fail an invariant are quarantined and excluded by default.
- **Archive (Supabase Storage):** every season the API serves, E2007–E2026,
  immutable and checksummed (Decisions 7, 9, 52). Archived is not loaded:
  E2007–E2023 are not queryable in the hosted warehouse.
- **Local warehouse:** E2020–E2025 in schema `warehouse` on the disposable
  database, for local projects (Decisions 84, 85).
- **Launch:** public on 2026-09-16; website at `euroleague.egemenyucelen.me`
  (GitHub Pages, `site/`), Turkish page at `/tr/`. Media lives in the
  [launch repository](https://github.com/egemeny13/euroleague-analytics-launch)
  (Decision 47).
- **Deploys:** a push to `master` deploys the MCP server (`ci.yml`, behind the
  test job) and republishes the site when `site/**` changes (`pages.yml`).

## Open work

### Owner-requested analytics expansion (2026-10-08)

Decision 93 and `docs/superpowers/plans/2026-10-08-mcp-analytics-expansion.md`.
Local implementation verified: season prompt, standings, shot profile,
opt-in advanced player rates and game logs; 1,775 offline tests and six guarded
local PostgreSQL tests pass. Up/down/up, actual handler calls and reader grants
passed; official-score/log and shot populations reconciled over complete seasons.
Open: approve and apply migrations 0030-0032, then release the reviewed branch.
Historical E2024/E2025 progress remains blocked on a truthful successful-load
timestamp: preflight found no historical application records. The backfill was
rehearsed with synthetic recorded loads; production dates were not fabricated.


### Needs verification now

1. **Fly idle sleep never happens (Decisions 86, 89, 91).**
   - **What failed.** Neither `suspend` nor `stop` took effect. The
     `cordon`/`uncordon` cycle came every ~6 min, with or without the health
     check. 89 and 91 are both reverted, and `suspend` is back in `fly.toml`.
   - **Owner's call.** Either approve a machine clone to another host, or post
     on the Fly forum with the evidence in 89 and 91.
   - **Cost meanwhile.** The machine runs always-on, about $2 a month.
   - **How to check.** Read the event log with `python scripts/fly_read.py`.
2. **E2026 foul codes (Decision 88).** Re-measure the three new codes as games
   arrive; `CMT1` rests on two clean cases. An unknown code stops the rebuild by
   design.

### Owner decisions waiting

- **Permission rules under bypass mode** (Decision 87): options 1–3.
- **Free-throw multiple-award split** (Decision 77): whether short trips holding
  two awards are split, which changes whether a technical free throw ends a
  possession.
- **Decision 88 review:** classified by Claude from measurement, not yet reviewed
  by the owner.

### Phase 9 — external judgement (the one open phase)

`CONTEXT.md` puts one goal first: would a club's analytics staff respect this.
Nothing so far measures it.

- **Work:** three readers who read box scores for a living, not friends of the
  project, use the hosted server and report what is wrong, incomplete or
  missing. Each answer is checked against the warehouse and euroleague.net, and
  each remark sorted with `docs/SCOPE.md`: wrong → a fix; missing → a candidate
  tool under Decision 65's condition; left out on purpose → the reason goes back.
- **Gate:** three written reports in `docs/evidence/`, every remark sorted, every
  "wrong" fixed or recorded as a known limit in `docs/SCOPE.md`.
- **Would fail to detect:** three readers are not a market. They can say the
  numbers are right and the tool usable, not that anyone will choose it.
- New tools come only from what Phase 9 returns, never from what the API
  still has.

### Watch, and act when a condition trips

- **Storage:** the nightly summary reports bytes per game and games of headroom
  (Decisions 30, 69). The 480,000,000-byte stop rule stands; at the warning, the
  owner chooses a paid tier or a smaller window. Re-project against a complete
  E2026 when its real game count is known (Decision 20, condition D).
- **Settlement re-checks** (Decision 7): finish the +6 h/+24 h/+72 h/+7 d
  observation on E2026 before reducing the cadence.
- **Corrected minutes** (Decision 3): re-measured for E2026 once the season has
  enough games; auto-disables if it makes things worse.
- **Archive size** (Decision 37): stop and re-decide if Storage passes 500 MB.

### Parked, by decision

- **Historical seasons in a hosted warehouse (R-12):** rehearsed on E2023
  (`docs/HISTORICAL_WAREHOUSE_REHEARSAL_REPORT.md`); all seasons project to about
  2 GB, so this waits on a sponsor-funded paid project (Decisions 32, 33, 37).
- **EuroCup loading** (Decision 11): schema-ready, needs a storage measurement.
- **Tier C row narrowing:** a table rewrite for about 28 MB, judged not worth it.
- **Two- and three-player lineup combinations:** postponed by the owner.
- **Player-level season-totals oracle** (Decision 78): would go through
  `person_game_link`, not names.

## Out of scope

Video and broadcast footage, tracking data, and scraping sites that forbid it
(`CLAUDE.md`). Billing, tiers and per-season entitlements (Decision 32).
