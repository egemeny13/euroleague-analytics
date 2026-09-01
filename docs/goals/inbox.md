# Inbox — captured follow-ups awaiting definition

Dispatch appends here at settle time. `/define-goal` converts these into real goal
contracts and removes the converted lines. Capture-only: no statuses, no priorities.

Captured 2026-08-27 from `docs/TEST_PERIOD_READINESS.md`, which holds the evidence
and the shape of each fix.

Converted 2026-08-27 into goals 018-023: T1-2 → 018, T2-1 → 019, T2-2 → 020,
T3-1 → 021, T1-1 → 022, T3-2 → 023.

Owner decisions, not queue items — do not define these as goals without a decision:

- ~~The `DATABASE_URL` repository secret is sending a bare `postgres` username; the nightly E2026 pipeline has failed every night since 2026-08-25.~~ **Resolved. Struck 2026-08-30 on measurement, not on report:** the last four scheduled `e2026-live.yml` runs, 2026-08-27 through 2026-08-30, all concluded `success`. Left visible rather than deleted, because a captured item that silently disappears cannot be told from one that was overlooked. (T0-1)
- ~~No read-only database role exists, so a tester given `DATABASE_URL` holds a credential that can drop every table. Needs two owner decisions — views-only or views-plus-tables, one shared role or one per tester — before a migration can be written.~~ (T0-2) **Resolved 2026-09-01, and the item was wrong.** A read-only role has existed since migration 0013: `el_reader`, approved by Decision 26. Neither of the two proposed decisions survived: "views only" is impossible because migration 0011 made the views `security_invoker`, so a role without base-table grants fails every query; and the shared-versus-per-tester question was settled for the shared role on a stated condition. The real question was the one the item did not ask — hand testers the existing role, or make a second one — answered by **Decision 43** and migration `0020_tester_role`, which is written but not yet rehearsed or applied.
- Goal 031 interprets the `P`-prefix agreement as a post-link diagnostic only: it may compare an already observed link's two identifiers, but it must never create, select, or repair a link. This preserves Decision 27's purpose while making the required published agreement rate computable.
- Goal 031 cannot implement its required within-game statistical-line pairing offline: the worktree has neither a cached v2 game-stats body nor a specified field map to `Boxscore.PlayersStats`. Add one archived, checksummed fixture and its verified field mapping before re-queuing the goal.

Captured 2026-08-30 late:

- Group `pydantic` and `pydantic-core` in `.github/dependabot.yml` so the pair is proposed together. Promised in the comment closing pull request #30 and recorded nowhere else; without it the same unresolvable bump returns every release.
- ~~Recon: does the public API serve the EuroLeague SuperCup (2026-09-18/19, first edition)? It is a third competition alongside `E` and `U` and may carry its own code. Scheduled in `docs/LAUNCH_PLAN_2026.md` for the week of 09-01.~~ **Done 2026-08-30, ahead of its scheduled week.** Yes: `exploration/SUPERCUP_RECON.md` records six read-only probes finding competition code `SC`, with `SC2026` games scheduled for 2026-09-18, and the v1 endpoints competition-agnostic. Acted on, not just recorded: Decision 39 parameterised the competition code through the offline fetch layer, and `.github/workflows/supercup-rehearsal.yml` plus Decision 40 cover the live rehearsal on the day. Struck 2026-09-01.
