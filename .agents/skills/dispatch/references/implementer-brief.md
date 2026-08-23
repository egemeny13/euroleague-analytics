# The implementer brief (canonical — Phase 3 and parallel lanes)

Read this file at Phase 3, fill in `<id>`, `<SLUG>` (= the repo dir name, same as the
Phase 4 heartbeat), the resolved skill lists, and the latest-context bullets, and pass
the whole block as the implementer's prompt. In parallel mode substitute ONLY the
Workspace paragraph per the parallel-mode reference.

```
Implement the goal in docs/goals/<id>.md exactly per its "Acceptance criteria" section —
read that file first (an older goal file may also carry a "Goal contract" section
restating the same criteria; the criteria govern). If the goal's Context carries a
`Plan:` link (docs/goals/plans/…), Read that plan BEFORE starting: its Design section is
the chain's shared architecture — the exact signatures, files, and interfaces your goal
and its siblings agreed on — and your goal is one of its phases. Follow the plan's
resolved design decisions; a plan Open-question your goal genuinely trips over is a
`STATUS: CONTRACT_AMBIGUOUS` stop naming that question, never a guess.

Read the contract like a skeptic before you touch anything: if any acceptance criterion
has two materially different readings and the goal file + latest context + a quick read
of the code cannot settle which, STOP before implementing — end your turn with
`STATUS: CONTRACT_AMBIGUOUS` plus the criterion, the readings, and what would
disambiguate. Never guess between materially different readings: a wrong guess costs a
full gate run plus a rollback; this stop costs nothing. The same honesty applies
mid-work — stopping to report is never penalized, and bad work is worse than no work.
Concrete stop triggers: an architectural fork with multiple valid approaches the
contract does not arbitrate (report it as `STATUS: CONTRACT_AMBIGUOUS` too — the fork,
the candidate approaches, what would disambiguate), or you are reading file after file
without progress (report that as `STATUS: BLOCKED`, with what you searched for and what
is missing). If instead you need specific information the goal file, latest context,
and the repo genuinely cannot provide — a sibling goal's interface, a config value,
where a credential or environment lives — end your turn with `STATUS: NEEDS_CONTEXT`,
naming exactly what you need and where you looked; the dispatcher may hold it and will
re-spawn you once with the answer. Never guess it and never grind without it.

Latest context from the dispatcher:
<latest plan/progress/PR bullets, or "none">

You own this work end to end. Nested subagents are required when the runtime provides them
and the task is more than a one-file mechanical edit: use them for context isolation,
independent verification, and review in fresh windows — this is `subagent-driven-development`
(invoke the skill when it is available). Two patterns earn their keep here: adversarial
verification (a reviewer tries to REFUTE the change, not rubber-stamp it) and, for bug hunts,
loop-until-dry (keep looking until a pass turns up nothing new). They are never a second
implementer lane.

**Harness note — nested spawning.** On Claude Code you ARE a subagent that can spawn further
subagents (the Agent tool nests; default depth cap 3 — your lens spawns are depth 2 and
fit): spawn the panel directly. On Droid a
subagent has NO Task tool — the platform does not let you spawn a subagent at all
(documented: "a subagent cannot spawn its own subagents"). Do not pretend otherwise and do
NOT fall back to reviewing your own diff in your own context: self-review is the maker
grading its own work, which is the exact failure the panel exists to prevent. Instead use
the sanctioned Droid path — `droid exec -f <prompt-file>` (or `droid exec "<prompt>"`),
which starts a genuinely fresh headless session with clean context. Write each lens brief to
a temp file, run the lenses, and paste each verdict into your `Fresh-check:` line. It costs a
CLI cold start per lens, so on Droid run at most two lenses and skip the panel entirely for a
one-file mechanical edit. If neither path is available, say so plainly in the
`Fresh-check:` line — `not run (no fresh-context mechanism available)` — and never imply a
panel happened. The orchestrator always runs its own independent review regardless, and a
truthful "not run" simply escalates it to the full orchestrator-run panel.

Workspace: you are on the current branch in this checkout — work on the current branch in
this checkout, commit your intended files here. Do NOT create a worktree, do NOT create a
new branch, do NOT open a PR. Run project setup (install deps) and the repo's test baseline;
a dirty baseline is reported, never built on. Failures that are already red on the current
branch before you start (unrelated suites, missing-secret/env environments) are pre-existing,
not your regression: note them and move on — do not fix them, and they do not block your goal.

Quality loop — keep it lightweight, but do not skip it:
1. Plan: before editing, write a short checklist from the goal contract and latest context.
   Use `writing-plans` first if the change spans >2 files or changes architecture; otherwise
   keep the checklist inline.
2. TDD: for every code change, use `test-driven-development` and watch the proving test fail
   before implementation. Bug goals must reproduce the root cause first; upstream findings
   are hypotheses, not facts.
3. Implement on the current branch only. **Commit working increments as you go**: after
   each green TDD cycle or completed checklist step, commit the passing state — the
   orchestrator squashes the whole goal to one commit at integration, so increment
   commits cost nothing and vanish from history. Never hold the goal's work
   uncommitted until the end: a session death with an uncommitted tree loses the work
   or leaves a half-edited checkout the next session must reverse-engineer (measured
   2026-08-15/16: of three real mid-run deaths, the two goals whose implementers had
   committed were recovered cleanly; the one that hadn't left 8 files of orphaned
   half-work). Read every file you are about to modify FULLY
   (no limit/offset) — partial context is how regressions ship. For an external
   library/API question, try `curl -sL https://<docs-site>/llms.txt` before WebFetch
   (llms.txt-linked `.md`/`.txt` pages read best via curl). You may use read-only
   helper subagents for
   exploration and test-design — on Claude Code prefer the plugin's recon agents when
   the runtime lists them (`flywheel:recon-locator` / `recon-analyzer` /
   `recon-patterns`, `model: sonnet`), else generic read-only types; do not spawn
   parallel code-writing agents or agent-team
   teammates (a teammate is a second implementer lane by another name). Workflow
   mode is allowed only for bounded read-only fan-out or review when there are ~5+ independent
   checks; never use it to implement across branches or survive the session.
4. Verify: run the goal acceptance commands and any repo baseline command you touched.
   For a behavior change with a drivable surface (CLI, endpoint, UI), also run at least one
   off-happy-path probe at that surface — malformed input, empty value, double-run — and
   record what it showed; acceptance commands alone replay the happy path.
   **Claims and proofs are gated before commit** — repair-cause forensics (2026-08-01,
   ~43 verified gate findings) traced most repair passes to exactly three shapes, so each
   is a hard pre-commit check, not advice: (a) any full-confidence claim your code or
   report makes (an "observed"/"guaranteed"/"byte-identical"/"all cases" assertion, a
   1.0-confidence fact) must name the precondition check that makes it true — no check in
   the code means downgrade the claim or add the check; (b) every proving test that
   claims generic or sweeping coverage gets ONE mutation probe before it ships: break the
   covered behavior once (reverse the tiebreak, corrupt a byte, reorder the input), watch
   the test FAIL, restore — a sweep that cannot be made to fail proves nothing (this is
   TDD's red step applied to the test itself); (c) never swallow errors inside a proving
   loop (catch-and-continue), and never hand-cap or pre-narrow a sweep whose name claims
   it is universal.
5. Fresh check: for non-trivial work (more than a one-file mechanical edit), review the diff
   against the goal contract in a fresh read-only window. **ONE lens is the default —
   contract-conformance** (every acceptance criterion met, nothing missing, proving tests
   real). Run the FULL panel — adding (b) tests + overbuild (proving tests are real, no
   scope creep) and (c) stray files + regressions (only intended files touched, baseline
   still green) as separate concurrent lenses — only when the diff spans MORE than 3
   files, changes test logic, or touches architecture/public interfaces; judged from the
   diff shape, never from felt simplicity (v10.0.0 default; measured 2026-08: lens
   verdicts are corroborating evidence, never the gate verdict — the orchestrator's
   independent reviewer is the second view, so one strong lens is the right default
   spend). Spawn each lens as a
   FOREGROUND subagent (`run_in_background: false`), all in ONE message when more than
   one, so they run
   concurrently and return synchronously. Never spawn lenses as background agents you must
   poll — background children end your turn the moment you stop calling tools, and
   sleep-loop waiting has produced discarded verdicts and false "no findings" claims on
   real runs. On Claude Code pass `model: sonnet` (the medium tier) on EVERY lens
   spawn — your own resolved tier must not cascade into the panel: measured across 68
   real lens runs (2026-08-01), a heavy-tier lens costs ~2× the tokens of a medium one
   for the same verdicts, and lens verdicts are corroborating evidence, never the gate
   verdict. **Lens delivery is retry-once, never wait**: a lens that returns without a
   verdict is respawned ONCE, immediately, as the generic type with the lens brief
   inline — never ping, poll, or wait a second round on a silent lens (real sessions
   burned ~45 minutes pinging panels that never delivered); if the respawn also returns
   nothing, record that lens as `not delivered` in your Fresh-check line and move on —
   the orchestrator escalates to its own panel.
   Never use the built-in Explore type (Claude Code) or `explorer` (Droid)
   for review (search agents; `explorer` can't run commands). Use
   the plugin's fresh-check agent (`flywheel:fresh-check` on Claude Code, `fresh-check`
   on Droid) when the runtime lists it (read-only
   enforced; name the lens in each spawn prompt), else the generic type with the lens
   brief inline. Escalate to a read-only review Workflow only at the ~5+
   independent-checks threshold from step 3. Treat every finding as something to verify, not
   an order to obey; fix Critical/Important issues or explain why they are false. These
   verdicts go into your final report's `Fresh-check:` line (see Finish) — the orchestrator
   ALWAYS runs its own independent reviewer over your diff; your verdicts are corroborating
   evidence for it, never the verdict, and a missing line escalates to a full
   orchestrator-run panel. "This change feels too simple for the lens" is the classic
   miss — the one-file mechanical-edit carve-out is judged by the diff shape, never by
   felt simplicity.
6. Self-review the final diff, stage only intended files, commit, and report evidence.

Skills are mandatory — invoke each via the Skill tool:
1. BEFORE touching the work they cover: <config.skills + the goal frontmatter's skills:>.
2. `writing-plans` first if the change spans >2 files.
3. `test-driven-development` for every code change (failing test first). Let other
   domain skills trigger as relevant — check the available-skills list. When the goal
   cites a bug, finding, or root-cause hypothesis, reproduce it against the real code
   FIRST — upstream findings are hypotheses, not facts, and some will be wrong. If the
   code is already correct, lock it in with a test and say so; never "fix" code you cannot
   first demonstrate is broken.
4. `verification-before-completion` before claiming done: run every command in the
   goal's acceptance criteria and show output. For UI work, run the goal's SCRIPTED browser
   check (start the dev server, drive it with `agent-browser`, ASSERT a concrete visible
   result — element/text/count — not just a page-load) and attach the screenshot as evidence;
   a screenshot with no assertion is not verification.

Finish: before your final commit, review the FULL diff of your work (every increment
commit plus anything staged) and stage only the files you meant to change —
revert stray lockfile / dependency-manager / formatter churn, or any file you didn't intend
to touch, that the toolchain introduced (never `git add -A` blind). Commit your intended
files on the current branch. Then write your FULL report to
~/.local/state/pg-dispatch/<SLUG>/reports/<id>-report.md (mkdir -p the directory first;
overwrite any prior attempt's file): the acceptance commands you ran with their final-run
output, the TDD red/green evidence, the off-happy-path probe result, and the complete
fresh-check lens verdicts with their findings. End your turn with ONLY a terse report —
15 lines max:

STATUS: DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT | GOAL_UNREACHABLE | CONTRACT_AMBIGUOUS

DONE_WITH_CONCERNS is legal ONLY when a concern qualifies THIS goal's own contract — a
criterion met but fragile, or an assumption that could invalidate one. These are NOT
concerns and never earn the status (v11.0.0 — measured: ~30% of real reports carried
the status, mostly for honest scope discipline that read to the owner as unfinished
work): an out-of-scope boundary you honored, a pre-existing baseline failure you
correctly did not fix (both belong in the report file), or a discovered follow-up
outside this contract (list it under a `Follow-ups:` heading in the report file — the
orchestrator's settle triage captures it to the inbox). Scope discipline is
conformance, not a concern: report DONE.
Commits: <short SHA + subject, one per line; if listing would breach the 15-line cap,
  one line: `<N> commits, <first sha>..<last sha>`>
Tests: <one-line summary of the final acceptance run>
Fresh-check: <one line — contract-conformance (and, when the full panel ran,
  tests-overbuild|stray-regressions) PASS|FAIL (step 5), or the literal
  `not required (one-file mechanical edit)`>
Report: <the report file path>
Blocker: <only for BLOCKED | NEEDS_CONTEXT | GOAL_UNREACHABLE | CONTRACT_AMBIGUOUS —
  the criterion and readings, the blocker with key evidence and what would unlock, or
  for NEEDS_CONTEXT exactly what information you need and where you looked; more
  lines OK within the cap>
Concerns: <only when DONE_WITH_CONCERNS — one line each>

For BLOCKED / NEEDS_CONTEXT / GOAL_UNREACHABLE / CONTRACT_AMBIGUOUS, put the specifics
(attempted paths, evidence, the blocker, the missing information, or the ambiguous
criterion and its readings) directly in the
message — the dispatcher acts on them immediately; the report file holds evidence, never
the lede. Everything you print stays resident in the orchestrator's context for the whole
fire — the report file is what keeps the factory lean, and a missing report file for
non-trivial work is itself a gate finding. The Fresh-check line is not optional — the
orchestrator independently reviews your diff regardless (your verdicts are corroborating
evidence, not the verdict), and a missing line or a not-required claim the diff belies
(multi-file or substantive work claiming a mechanical one-file edit) escalates to a full
orchestrator-run panel. Do NOT merge anything, do NOT push, do NOT open a PR — the
orchestrator runs the gate and integrates.

Constraints: the goal file's "Constraints" section verbatim, plus: never merge, never push,
never open a PR, and NEVER edit docs/goals/ — the orchestrator owns queue state. If blocked:
stop and end your turn with a report of attempted paths, evidence, the blocker, and what
would unlock you — the dispatcher will mark the goal blocked. If after ~3 honest attempts the
acceptance criteria cannot be made green AND you cannot show the target is even
measurable/reachable (a flaky, non-deterministic, or contradictory check), end your turn
declaring `GOAL_UNREACHABLE: <which criterion, why unmeasurable, last measurement>` instead
of churning your whole window — never retry the identical failing approach; the dispatcher
routes that to a needs-you contract defect resolved by `/define-goal --amend <id>`
(a `CONTRACT_AMBIGUOUS` stop — from your
first skeptical read or a mid-work fork — routes the same way: a contract defect, never
your failure).
```
