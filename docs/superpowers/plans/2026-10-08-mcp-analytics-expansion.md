# MCP analytics expansion

Owner requested on 2026-10-08; supersedes the frozen-surface restriction for
these named additions. Execute the six items in the requested order.

1. Correct the shared season description and warehouse prompt: EYYYY starts
   in autumn YYYY (E2024 = 2024-25). First replace the wrong regression assertion;
   confirm it fails, repair prompts, refresh the transport fingerprint, verify parity.
2. Prepare truthful historical progress backfill from the cached schedule and
   recorded successful load timestamps. Refuse missing evidence and partial loads.
   Never substitute fetch time or current time for historical load time. Rehearse
   locally; production writes require immediate owner approval (Decision 87).
3. Standings: season and optional phase. Aggregate completed official scores,
   including quarantined games, into wins/losses, home/away splits, points for and
   against, differential and chronological last five. Explain that this is a
   results summary; do not claim official head-to-head tie-break ranking.
4. Shot profile: season plus team or player, optional event-defined shot_type.
   Aggregate existing source zone codes, preserving an unknown-zone bucket and
   separate free throws. Same season/type/quarantine population for league rates;
   include attempts, makes, FG rate and percentage-point difference. Never expose
   coordinates. Keep event-based attempts so missing coordinates do not drop shots.
5. Optional advanced=true on player stats; false preserves the old query/response.
   Publish explicitly defined TS%, eFG%, usage, assist, turnover and offensive/
   defensive rebound rates. Use reconstructed possession counts for possession
   rates, never the box-score possession estimate. On-court populations must follow
   the existing possession-start lineup convention and disclose it. Undefined
   denominators return null. Do not silently call an approximate definition exact.
6. Game logs: season plus player or team, optional last_n, home_away and opponent.
   One row per played game, deterministic newest-first order, official box-score
   counting statistics, explicit minute basis, bounded pagination. Apply filters
   before last_n. Player DNP rows are excluded; retain quarantine disclosure.

Implementation keeps the MCP read-only query architecture and response envelope.
New calculations live in SQL views with security_invoker and no public API grants.
Do not edit transport code. Main agent owns registry, fingerprint, scope, decisions
and progress integration. Subagents own isolated query modules/migrations/tests:
standings and logs (0030), shot profile (0031), advanced stats (0032).

Verification: focused unit tests, real PostgreSQL fixture calculations and
up/down/up migration rehearsal on the guarded disposable database, existing
offline suite, Ruff and transport parity. At least 50 cached official box scores
must reconcile for box-score metrics. Record measurements and limits; never
call a live check passed without observing it. No deployment or production writes.


## Advanced-rate definitions settled before integration

TS = points / [2 * (FGA + 0.44 * FTA)], explicitly approximate; eFG =
(FGM + 0.5 * 3PM) / FGA. usage_event_rate = (FGA + distinct inferred FT
trips + TO) / exact offensive on-court-start possessions, including and-ones;
this is not standard USG and can exceed one after offensive rebounds.
AST / teammate FGM, TO / exact offensive possessions, OREB / (team OREB +
opponent DREB), DREB / (team DREB + opponent OREB), each restricted to the
player's side-specific possession-start lineup. Rebound denominators retain
team-only outcomes. Suspect player attribution does not enter individual
numerators. Publish support counts as season totals in both per_game modes.
