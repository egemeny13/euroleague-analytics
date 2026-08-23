# Parallel mode — the lane model (`--parallel` / auto-parallel drains, Claude Code only)

Read this file when a run carries `--parallel`, when a flagless drain auto-enters lane
mode (v11.0.0: `config.parallel` exists, Claude Code, ≥2 co-schedulable ready goals —
the flag and the auto-entry run the identical lifecycle below; `--serial` suppresses
auto-entry), or when Phase 1 finds lane-backed claims to settle.

Parallel mode is the merge-queue architecture localized: N goals BUILD concurrently in
isolated worktree lanes; ONE integration lock admits them onto the branch strictly one
at a time, re-gating each on the exact tree the branch is about to become. Parallelism
never touches the gate's authority — it moves wall-clock, never the bar. Everything not
restated here (claim protocol, briefs, gate arms, budgets, escalation ladder, report,
heartbeat, settle triage) is exactly the canonical per-goal sequence.

**Harness gate.** Claude Code only (concurrent foreground Agent spawns are the same
proven mechanism the lens panel uses). On Droid, note the ignored flag in the report and
run serially — Droid's concurrent-Task and worktree behavior is unverified (v7.0.0
doctrine: no Droid claim ships without live verification).

**Admission control — which ready goals may share a wave.** Walk the ready list in
normal priority order; a goal joins the wave only when ALL hold against every goal
already in it:

1. No `depends_on` path between them, in either direction, transitively.
2. Disjoint `touches:` globs at the DIRECTORY level. A goal with no `touches:`
   frontmatter is not parallel-eligible — it runs in a wave of one (define-goal stamps
   `touches:` on recon-backed goals; since v10.0.0 a missing field on a recon-backed
   feature/bug goal is a contract defect at definition time, so new queues should
   rarely hit this).
3. No conflict-domain membership — any of these makes the goal exclusive (wave of one):
   it adds/removes a dependency (manifest + lockfile), touches DB migrations/schema,
   regenerates generated artifacts, or touches CI/workflow files or global config
   (env schema, tsconfig/build config).
4. Disjoint drivable surfaces: two goals whose acceptance drives a live dev
   server/port are never co-scheduled (v9.0.0 serializes them; no port juggling).
5. Same `base:` branch.

Anything uncertain → not co-scheduled. A wave of one is always legal and is just the
serial cycle. `config.budget` outranks the wave: never start more lanes than the
remaining budget allows.

**Lane lifecycle (per wave-member goal):**

1. Claim exactly as the protocol requires — K claims are K separate
   `chore(goals): claim <id>` commits on the branch, made before any lane spawns
   (claim commits are index-only and cannot conflict with lane work).
2. Create the lane:
   `git worktree add ~/.local/state/pg-dispatch/<SLUG>/lanes/<id> -b lane/<id> <branch-HEAD>`.
   `lane/<id>` is LOCAL, never pushed, deleted at settle — a disposable build
   directory, not v3's remote PR branch. If `config.parallel.setup` is set (e.g.
   `pnpm install --prefer-offline`), run it in the lane; lanes persist across fires to
   amortize setup, and factory-doctor reports orphans. A fresh worktree contains NO
   gitignored local files: if the suite needs one (a `.dev.vars`, a local env file),
   copy it from the main checkout at lane creation or add it to
   `config.parallel.setup` — a missing local secret fails as auth errors that read
   exactly like a real regression and burns a full gate cycle (measured on a real
   lane 2026-08-13: 6 failures in the lane, 7/7 green once `.dev.vars` was copied).
3. Spawn ALL wave implementers foreground in ONE message (the lens-panel concurrency
   pattern — concurrent, returning synchronously; never background-then-poll). Each
   brief is the canonical implementer brief (references/implementer-brief.md) with ONE
   substitution — the Workspace
   paragraph becomes: "Workspace: you are in the worktree at
   `~/.local/state/pg-dispatch/<SLUG>/lanes/<id>` on local branch `lane/<id>` — work
   and commit THERE only. Never touch the main checkout, never switch branches, do NOT
   create further worktrees or branches, do NOT push, do NOT open a PR."
4. In-lane gate, per returned implementer: Arm B reviews `<branch-HEAD>..lane/<id>`
   (read-only reviewers of DIFFERENT lanes may spawn concurrently in one message;
   Arm A background commands run inside each lane directory). Verified findings → ONE
   repair round IN the lane (warm resume first, per the escalation-and-repair
   reference); focused re-check in the lane. At most one writing agent
   per lane at any moment — reviews of lane A may overlap a repair in lane B freely.
   A goal is integration-ready when its lane gate has no open findings.
5. **Integration lock — strictly serial, one goal at a time, in wave order of
   readiness**: rebase `lane/<id>` onto the CURRENT branch HEAD (later wave members
   replay over freshly integrated work). If the rebased range carries ANY commit
   touching `docs/goals/**`, restore those paths to the branch's copy before gating
   (`git checkout <branch> -- docs/goals/` in the lane) — queue state is written
   ONLY by the orchestrator on the branch, never through a lane. Then re-run Arm A
   (pg_validate over the
   rebased range + every `config.verify` command) INSIDE the rebased lane — this
   verifies the exact tree the branch is about to become, which is where cross-goal
   interference is caught. PASS → collapse the lane to one commit IN THE LANE
   (`git reset --soft <branch-HEAD>` then commit as `feat(goal <id>): <slug>`), and
   fast-forward the working branch to the lane tip from the main checkout
   (`git merge --ff-only lane/<id>`). NEVER `git merge --squash` (v11.4.1): it
   re-merges the lane against the branch and can conflict on files the rebase
   already settled — on 2026-08-13 exactly that put conflict markers INTO a
   committed `index.yaml`; the rebase-then-ff-only path cannot conflict by
   construction. Then
   `chore(goals): complete <id>`, delete the lane and its branch, push (non-blocking),
   surface needs-independent-review criteria exactly as the canonical sequence's
   step 4. The branch moves ONLY
   by fast-forward to verified trees — strictly stronger than serial mode's
   commit-then-maybe-reset.
6. Report line + heartbeat per settled goal, exactly as Phase 4 (each settle = one
   fire for the cross-fire brake). In parallel mode `current:` lists the live lane
   ids (e.g. `current: 131+134`).

**Failure rulings (every scenario, decided in advance):**

- **Conflict on `docs/goals/**` at integration** — NOT a touch-set misprediction:
  implementers never write the queue, so the conflict means queue commits rode
  into the lane range. Take the BRANCH's copy of the conflicted queue paths,
  never the lane's: mid-rebase that is
  `git checkout <branch> -- docs/goals/ && git add docs/goals/ &&
  git rebase --continue` (a queue commit emptied by this resolves with
  `git rebase --skip`); after a clean rebase it is step 5's restore. Then
  continue integration. Absolute rule regardless of file: a tree with conflict markers is
  NEVER committed — any `<<<<<<<` in `git status`/`git diff` output means stop,
  restore, re-integrate; markers committed into `index.yaml` corrupt the queue
  every later fire reads.
- **Rebase conflict at integration** (goal-work files) — the touch-set prediction was wrong. Never
  resolve by guessing (the standing conflict rule). Discard the lane's commits,
  delete the lane, KEEP the goal claimed, and re-run it serially from the new branch
  HEAD as a fresh implementer spawn (worst case = today's serial cost). Surface
  needs-you class `parallel-conflict`. TWO mispredictions in one run → degrade the
  rest of the run to serial (self-throttle) and say so in the report.
- **Arm A fails on the integrated tree though the lane's own gate passed** (semantic
  interference, no textual conflict) — ONE integration-repair spawn in the rebased
  lane scoped to the failing commands' output, re-run Arm A; still failing → block
  the goal with reason `integration interference`, delete the lane, continue the
  wave (needs-you class `integration interference`). The environment brake still
  applies if the failure is infrastructure-shaped.
- **Flaky test at integration** — the step-3 flake protocol applies unchanged
  (isolated re-run once; never a repair, never a second retry).
- **A lane implementer dies transiently** (stream death, empty return) — the
  Re-entrancy transient rules apply per lane; other lanes are unaffected. A lane
  respawn continues from the lane's current state. Death needs evidence first
  (Re-entrancy's two-sample rule, v11.6.0): a spawn that has not RETURNED is never
  declared dead on one silent probe — check twice with real minutes between and
  require zero new lane commits between; a respawn onto a live lane agent is two
  writers in one lane (three false dead-calls measured in one real 2026-08-15 run).
- **CONTRACT_AMBIGUOUS / NEEDS_CONTEXT / BLOCKED / GOAL_UNREACHABLE from a lane** —
  identical routing to serial mode (escalation ladder, contract-defect classes);
  ladder re-spawns continue in the lane; a goal that blocks discards its lane.
- **Lockfile churn from parallel installs** — the brief's stray-churn rule already
  reverts it; a goal that legitimately changes dependencies never shares a wave
  (conflict domain 3).
- **Crash / usage-limit death mid-wave** — recovery is derivable with no new state:
  `git worktree list` + `lane/<id>` branch names ARE the lane ledger
  (status-only-in-index holds; nothing new is written to the queue). See Phase 1.
- **Crash between fast-forward and the `complete` flip** — Phase 1's existing
  detection: a `feat(goal <id>)` commit on the branch for an `in_progress` entry →
  flip to complete, no re-gate.
- **Token burn** — a wave spends the same tokens per goal, faster; that is the point
  of a window-timed drain. `config.budget` always outranks the wave size.
