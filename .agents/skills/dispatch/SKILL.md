---
name: dispatch
description: Factory dispatcher — use when the user says "/dispatch" (optionally with a goal id, --count N, --unlimited, --parallel, or --serial), "run the factory", wants the docs/goals queue worked, or wants to work one specific queued goal in this session ("work goal 005", "/dispatch 005"). Works in any repo with a docs/goals/ queue. Works ready goals on the currently checked-out branch and by default DRAINS the queue (keeps working ready goals until empty; --count N limits the run, a goal id scopes it to one); parallel lane mode builds provably-disjoint goals concurrently in local worktree lanes while still integrating them strictly ONE at a time behind the same local gate — entered via --parallel, or automatically on a flagless drain when the queue's config.parallel block exists (--serial forces one-at-a-time) — no pull requests, no remote branches, never two writers in one tree. Orchestrates only — never implements in its own context; the phase procedure lives in the skill body, never in this description.
argument-hint: "[goal-id] [--count N | --unlimited] [--parallel [K] | --serial]"
---

# Dispatch — the factory orchestrator

You are depth 0: a thin orchestrator. Your context stays small; the implementer (depth 1)
and its nested helpers (depth 2+; default nesting cap is 3 layers below the main
conversation per official docs — this chain uses 2) hold the mess. Compose existing
skills — never re-derive what a skill already encodes. The queue is `docs/goals/index.yaml`
(see `define-goal` for the format).

Dispatch works ready goals **on the currently checked-out branch** (e.g. `staging`).
Integration is serial, one goal AT A TIME — and since v10.0.0 the flagless default is a
DRAIN: keep working ready goals, one fully-settled cycle after another, until the queue
is empty or a stop condition fires (`--count N` is the opt-in limiter; lane mode —
Claude Code only, entered via `--parallel` or auto-entered on a flagless drain when
`config.parallel` exists (Invocation) — builds provably-disjoint goals concurrently in
local worktree lanes: references/parallel-mode.md). Per goal: claim it, spawn a single foreground implementer that
commits its work (on this branch in serial mode; in its lane in parallel mode), run a
LOCAL gate yourself, and on PASS keep one squashed commit — on FAIL roll the goal back so
the branch never carries unverified work. No pull requests, no remote or `goal/<id>`
branches, no agent-team teammates, and NEVER two writers in one working tree.
**The invariant, stated precisely: at most one goal INTEGRATES at a time, the branch only
ever advances to gate-verified trees, and every gate verdict is rendered on the tree the
branch is about to become.** That is what "one at a time" always protected. The v4.0.0
scar stays load-bearing in what it actually proved: v3's per-goal worktree PRs + parallel
`wip` implementers + CI-gated auto-merge livelocked on real autonomous runs —
PR-shepherding churn, CI runners blocking every merge, stale remote branch garbage (see
CHANGELOG 4.0.0). What failed was the PR/CI/remote INTEGRATION machinery, and none of it
returns: parallel lanes are disposable local build directories behind the same local
gate, serialized at integration, deleted at settle. Cross-goal parallelism outside the
Parallel-mode section's rules — parallel writes to one tree, PRs, remote branches,
background implementers you poll — stays banned.
A single `/dispatch` now drains the queue; `/loop /dispatch` exists only to keep
re-draining as NEW goals arrive.

## Invocation — `/dispatch [<goal-id>] [--count N | --unlimited] [--parallel [K] | --serial]`

| Invocation | Behavior |
|---|---|
| `/dispatch` | **Drain — the v10.0.0 default:** keep working ready goals until the queue drains or a stop condition below fires. **Auto-parallel (v11.0.0):** when the queue's `config.parallel` block exists (the repo owner's standing opt-in), the harness is Claude Code, and ≥2 ready goals are co-schedulable under the untouched admission rules, the drain runs them as `--parallel` waves (K = `config.parallel.max_lanes`, else 2); otherwise — no `config.parallel`, Droid, or nothing co-schedulable — it works sequentially exactly as before. `--serial` forces sequential for this run; `config.parallel.auto: false` (v11.2.0) is the PERSISTENT opt-out — it keeps the block's tuning for explicit `--parallel` runs while flagless drains stay sequential (the knob exists because pre-v11 queues configured `parallel:` when it only tuned the flag). |
| `/dispatch 087` (also `87`, `087-slug`, or "work goal 087") | Solo mode: work exactly that goal (see Solo mode below). |
| `/dispatch --count N` | Work up to N ready goals, then stop (N ≥ 1). `--count 1` is the pre-v10 single-goal fire — use it when one goal is deliberately all you want. |
| `/dispatch --unlimited` | Explicit alias of the flagless drain default (kept for compatibility and for loop prompts that spell intent out). |
| `/dispatch --parallel [K]` (combinable with `--count`) | Lane concurrency: build up to K provably-disjoint goals at once in local worktree lanes (default K = `config.parallel.max_lanes`, else 2; hard cap 4), integrating strictly one at a time. Claude Code only — on Droid the flag is REFUSED out loud (v12.0.0): the run's FIRST line states `parallel unavailable on this harness — running serial`, and lane machinery is never emulated with background workers. A repeated non-blocking task-status poll with no intervening work is a compliance miss on any harness (measured 2026-08-17: a Droid run that emulated 4 lanes burned 293 poll calls — 34% of its turns — and the waste exhausted the account balance mid-drain, killing the run). See references/parallel-mode.md. |

Argument rules: a goal id combined with `--count`/`--unlimited`/`--parallel`/`--serial`
→ the id wins; note the ignored flag in the report. `--count` without a valid N ≥ 1, or
an unknown flag → report the usage line above and run the drain default. `--parallel`
without `--count` waves through the drain default (keep claiming co-schedulable waves
until the queue drains); `--serial` disables auto-parallel for the run (and beats
`--parallel` if both are given — note it). The count meters CLAIMS exactly as below —
lanes change where work builds, never how much is claimed.

**A drain repeats the same settled cycle — it changes nothing about safety.** The
invariant was never "one goal per run"; it is one goal AT A TIME, on one branch, behind
the local gate. A drain is in-session what `/loop /dispatch` is across fires: Phase 0
and Phase 1 run ONCE at run start (finished work still beats new work), then per goal
the full cycle — Phase 2 claim → Phase 3 implement → the local gate (Working a goal,
steps 3–4) → settle (complete or
blocked, branch clean) → Phase 4 report line + heartbeat append — before the next
claim. The single-`in_progress` invariant holds continuously; each per-goal cycle
counts as one fire for the heartbeat and the cross-fire brake. A goal that settles
`blocked` does NOT stop the run — the next ready goal is claimed, exactly as the next
loop fire would claim it. The end-of-drain CI observation stays end-of-run, never
per-goal; the stalled-factory notification stays once per distinct blocker set.

**The count counts CLAIMS — Phase 1 settles are free, and a spent count claims nothing.**
`--count N` budgets the number of Phase-2
claims this run may make: each claim consumes one unit BEFORE the implementer spawns,
and settling a pre-existing `in_progress` goal in Phase 1 neither consumes a unit nor
licenses an extra claim. When the count is spent, the run reports and stops even if
ready goals remain — a real fire on 2026-07-27 worked two full goals on `--count 1`
because "finish then claim" was read as "the settle didn't count"; it does not: the
settle is free, the NEXT claim is what the count meters, and on a spent count there is
no next claim.

**Stop conditions — first one wins (they are the ONLY legal reasons a run stops with
ready goals left):**

1. Count reached (`--count N`) — measured in claims, per the rule above.
2. No ready goals left (for a drain this is the drained-queue terminal stop,
   Phase 0).
3. `config.budget.max_goals_per_session` exhausted — the budget ALWAYS outranks the
   flag (effective cap = min(flag, budget)); it is the external brake precisely because
   this session cannot edit it. A true unlimited drain requires the repo owner to
   remove the budget from `config`, never a flag.
4. **Environment brake:** two CONSECUTIVE goals fail with the same
   infrastructure-shaped cause — the same `config.verify` command failing identically
   in a way the two goals' diffs cannot explain, or two INCONCLUSIVE gate verdicts →
   stop the batch and surface it under needs-you as class `environment brake`. A broken
   environment must not burn the queue one blocked goal at a time. The first goal
   still gets its normal repair attempt (one failure can't prove a systemic cause);
   when the SECOND goal's gate failure matches the first's infrastructure signature,
   skip its repair spawn and fire the brake — a repair agent cannot fix the registry
   or the environment.

The drain is the default because window-timed drains are the factory's primary
throughput pattern (loop-architect's limit-proofing): start `/dispatch` right after a
usage-limit reset so the run front-loads work into the fresh quota — and because real
2026-07/08 forensics found 7 runs that ended "stopping after this one goal, run
/dispatch again" with ready goals queued, which is a manual re-invoke tax with no
safety payoff. An in-session
drain still dies silently at a subscription usage limit with no hook fired — the
per-goal heartbeat makes that death detectable and Phase 1 makes the next window's
recovery clean (the killed batch's in-flight goal settles first), but nothing restarts
a session from inside it; the next drain is a human (or the next attended session)
starting one, never a headless scheduler (owner decision 2026-07-28: no `claude -p`
fires).

Read the queue's `config:` block first; defaults when absent:
`base` = the branch dispatch works ON (the started branch — staging, main, or other;
default = the currently checked-out branch), `model: inherit` (heavy|medium|light — the
repo-wide DEFAULT execution tier for implementer/fix agents; a goal file's own
frontmatter `model:` overrides it per goal), `skills: []` (repo-wide skill mandates),
`verify: []` (the
ordered LOCAL gate — a list of shell commands run top-to-bottom, all must exit 0; e.g.
[ "npm ci", "npm run build", "npm test" ]; empty = auto-detect a single test command, and
if none is found the gate is INCONCLUSIVE, never a silent PASS), `budget` (default none;
`max_goals_per_session` + optional `max_iterations` = the external burnstop).

**Implementer-tier resolution — per goal, before each spawn.** Resolve the execution
tier for a goal's code-writing agents in this order: the goal file's frontmatter
`model:` field (`inherit | heavy | medium | light` — stamped by define-goal at
contract-writing time as the goal author's difficulty call), else `config.model`, else
`inherit`.

**Execution tiers (canonical alias table).** Legacy values are read as aliases forever —
`opus` → heavy, `sonnet` → medium, `haiku` → light — and never written into new goals or
claims. Spawn-time mapping per harness:

- **Claude Code**: heavy → `model: opus`, medium → `model: sonnet`, and
  light → `model: haiku` on the code-writing agent spawn; `inherit` omits the pin.
- **Droid**: pass `complexity: heavy|medium|light` on the Task spawn (the accepted
  value set, live-verified 2026-07-25); `inherit` omits it. Implementers always spawn
  as the `worker` type regardless of tier.

**Pin-failure fallback (v11.6.0; class widened v12.0.0).** A spawn (or mid-goal death)
whose error names the
MODEL, PROVIDER, or the ACCOUNT'S ACCESS to them rather than the work —
`unknown provider for model …`, `model not
found`, a 4xx quoting the pinned id, and equally `insufficient balance` /
`billing_error`, `auth_unavailable`, "provider is currently overloaded", a 403/429/503
from the model endpoint — is infrastructure, NOT a transient work death: retry ONCE
with the pin omitted (the agent inherits
the session model), note `tier-fallback: <id> <tier> → session` in the fire's report,
and continue the run. When the UNPINNED retry fails with the same
infrastructure class, the environment itself is down — settle CLEANLY instead of
hanging: block only the in-flight goal (`environment: model endpoint unavailable —
<error>`, needs-you class `environment failure`), run Phase 4, release the checkout
lock, and stop. A clean stop resumes at Phase 1 next window; a mid-wave hang waits for
a human (measured 2026-08-18: a 4-lane drain hit `403 billing_error` +
`503 auth_unavailable` and sat 4h46m until the owner typed "continue"; measured
2026-08-18 on a second harness: two "provider overloaded" deaths each cost a manual
"continue"). Never burn the ~3 transient respawns on an error that
reproduces identically by construction (measured 2026-08-15: a drain at 28/39 died
mid-run when a heavy pin's mapped model was rejected — `400 unknown provider for model claude-opus-5` —
and respawning the same pin could only repeat it), and never substitute a LIGHTER
pin — inherit-the-session-model is the only fallback, same rung as the escalation
ladder's capability re-spawn.

A non-`inherit` tier applies to EVERY code-writing agent you spawn for THAT goal — the
implementer and any fix/repair agent alike; `inherit` means omit the mapping so the agent
runs your session model. This split keeps judgment on strong models: the orchestrator
stays on the session model for claim/gate/review calls, features and bugs default to a
`heavy` stamp (define-goal's rubric), and only rote mechanical goals run lighter
implementers. Neither field is yours to override, and neither ever applies to review
read-only agents — those always inherit the session model (one carve-out: the
implementer's fresh-check LENSES pin the medium tier — see Named review agents).

**Named review agents (plugin-shipped).** The plugin ships three read-only agent
definitions for the factory's review roles: gate-reviewer (the orchestrator's
independent second view, also used for focused re-checks), fresh-check (one
lens of the implementer's panel), and contract-red-team (define-goal's draft
review). Spawn them as `flywheel:gate-reviewer` etc. on Claude Code, bare
`gate-reviewer` etc. on Droid (Droid auto-translates plugin agents and registers them
unprefixed). Each definition carries the role brief, the output contract, and a tool
allowlist with no write-capable tools — read-only enforced by the runtime, not by prompt
discipline — so a spawn prompt carries only the per-goal specifics (repo/branch, diff
range, goal file, checklist, evidence to challenge). None pins a `model:` in its
definition, so each resolves by the runtime's normal inheritance: an orchestrator-spawned
`gate-reviewer` or `contract-red-team` inherits the session model — never pass them a
model or complexity parameter (the review-agents rule above). The ONE exception is the
implementer-spawned `fresh-check` lens: the implementer pins it to the medium tier
(`model: sonnet` on Claude Code) instead of letting its own heavy pin cascade —
measured 2026-08-01 across 68 real lens runs, a heavy-tier lens costs ~2× the tokens
of a medium one for the same verdicts, and lens verdicts are corroborating evidence,
never the gate verdict, so the cheaper tier is safe exactly there. For the
verdict-rendering roles, review cost is controlled
by the BUDGET in each role's brief, never by pinning review agents to a cheaper tier —
the gate is the only merge gate, and the same brief must hold on whatever model the
session runs. That matters because an unbudgeted brief does not cost the same everywhere:
measured 2026-07-29 across 11 real gate reviews on same-size diffs, the identical
gate-reviewer brief ran 5 min / 14k output tokens on one model and 43 min / 181k on a
stronger one — the stronger reasoner spends its extra capability on depth, not speed, so
an open-ended "refute this" brief has no natural stopping point. The budget supplies the
stopping point at every tier. Fallback is mandatory,
never a stop: when the runtime doesn't
list the type (plugin agents disabled, older CLI, a failed spawn naming the type),
spawn the generic read-capable type (`general-purpose` on Claude Code, `worker` on
Droid) and state the role inline exactly as the relevant step describes.
Never use the built-in Explore type (Claude Code) for any review role — it is a search
agent and its own description forbids review use. On Droid, `explorer` is likewise never
a review role: review needs to run commands (tests, builds), which `explorer` cannot.
**Droid spawns are awaited (v12.0.0):** every dispatch spawn on Droid — implementer,
gate-reviewer, fresh-check lens, repair — passes `await: true` on the Task call. A
spawn without it runs in the background and its verdict arrives as a later event that
can land AFTER the gate has already ruled (measured 2026-08-17: a goal's review
verdict was delivered two minutes after the run's final report, five hours after the
goal settled — the v5.4.0 background-review scar on a new surface).

## Hard rules (every iteration, before any action)

- One goal INTEGRATES at a time, in this session, on the current branch. Serial mode
  (the default): the next claim waits for the current goal to fully settle (the
  Invocation flags size the run; default one goal), work commits land directly on the
  branch, and there are NO worktrees. Parallel mode (`--parallel`, or auto-entered on a
  flagless drain per Invocation): up to K
  co-schedulable goals build concurrently in local lanes per the Parallel-mode section —
  but integration stays strictly serial and the branch only ever advances to
  gate-verified trees. In BOTH modes: no pull requests, no remote or `goal/<id>`
  branches, never two writers in one tree. After a goal's work passes the LOCAL gate you
  keep its commit on the branch (squashed to one) and move on per the run's flags. A
  failed gate rolls the goal back (serial: `git reset --hard <gate_base>`; parallel: the
  lane is discarded — the branch never held the work) so the branch never carries
  unverified work. Implementers never merge.
- Read the repo's CLAUDE.md hard rules once per session and treat them as law
  (deploy rules, forbidden merges, migration rules). Repeat-check before any git/deploy action.
- **Every queue write goes through the claim protocol below.** Implementers never touch
  `docs/goals/` — the orchestrator owns queue state.
- No-progress rule: same goal fails the same way twice with no progress → stop retrying,
  set the goal `blocked` with a `reason`, report, and claim the next ready goal
  (Invocation stop conditions and the environment brake still apply). (Orchestrator-level —
  distinct from the implementer's own ~3-honest-attempts rule inside one spawn.)
- **The cycle is never a confirmation point.** Claiming, spawning the implementer,
  running the repair round, re-gating, squashing, completing, blocking, and the
  (pre-authorized) push are this skill's own specified steps — execute them without
  asking. "Want me to run the repair?", "Say the word and I'll squash and mark it
  complete", "Should I continue with the next goal?" are compliance misses, not
  politeness: real 2026-07/08 forensics counted 6 such invented permission-asks, each
  stalling an autonomous run on a question the skill already answers. The ONLY legal
  interactive ask is the Attended-only rule below; anything else a human must know goes
  to needs-you or the settle-triage inbox, and the run continues.
  **Declarative stalls are the same miss (v12.0.0).** The ban was measured as
  question-marks and re-emerged as statements: "I don't push without you asking, so
  staging is yours to review first" (40 verified commits stranded), "`/dispatch` was
  not started — the tree has unrelated dirty files", "it needs your word", "Say the
  word and I'll run the release". A statement that ends the run's forward motion on a
  step this skill (or the repo's own standing authorization) already licenses is an
  invented permission-ask wearing a period. This covers the CLOSING turn too: a run
  never ends on an offer — an action inside the rails is taken; an action that is
  genuinely the owner's is emitted as a needs-you item WITH a recommendation, never
  as a question or an offer. Measured 2026-08-16/19 across both field repos: five
  "say the word" closers cost ~18 hours of idle wall-clock, and three declarative
  stalls each ended a run the owner had already authorized twice.
- Substantive conflicts are never guessed through. A local `git merge`/squash that hits a
  conflict on the current branch means two pieces of work changed the same logic → set the
  goal `blocked`, surface it under needs-you as class `conflict`, and roll back; never
  resolve by guessing.
- **Session budget (external brake).** If `config.budget.max_goals_per_session` (or
  `max_iterations`) is set, count each claimed goal against it. A run claims until its
  stop condition but NEVER past the
  cap — the budget always outranks a flag (effective cap = min(flag, budget));
  lower/zero or exhausted caps stop before claiming. Let any in-flight goal finish its gate
  cleanly, surface `budget exhausted (<n>/<cap> goals)` as class `budget exhausted` under
  needs-you, and send ONE
  notification per Phase 4 via the PushNotification tool. The cap comes from config you
  cannot edit; that is what makes it a real brake and not a soft self-limit.

## needs-you — the canonical format (every human decision names its command)

needs-you is the factory's only channel to a human, and a diagnosis is not an answer:
`004 — contract defect: criterion 3 ambiguous` tells the reader what broke and leaves them
to work out what to do about it. Every needs-you item is emitted in ONE shape, defined here
and nowhere else — the emission sites below name their CLASS and let this table supply the
command, so a new class is one new row instead of a new phrasing:

`<id or item> — <reason> → <what to run>`

`<id or item>` is the goal id (or the item name for a queue-wide condition), `<reason>` is
a faithful condensation of the block reason **capped at ~120 characters** — the FULL
reason lives in `index.yaml` and the report file, and the two must agree in substance
(v12.0.0: the old exactly-as-written rule met a real 740-character index reason and
forced every session into "needs-you: 3 items below" + a prose essay — the escape hatch
that produced the walls of text) — and `<what to run>` is the resolving command from
the table, with `<id>` and `<base>` substituted. Command unclear for a class not in the
table? Emit the item with the closest table command and say what is uncertain — never drop
the `→` half.

| class | trigger | what to run |
|---|---|---|
| `contract defect (ambiguous)` | reason `contract defect: <criterion> ambiguous` | `/define-goal --amend <id>` |
| `contract defect (unreachable)` | reason `contract defect: <criterion> unreachable` | `/define-goal --amend <id>` |
| `contract defect (finding)` | reason `contract defect: <the verified finding>` (FAIL_CONTRACT) | `/define-goal --amend <id>` |
| `contract defect (too large / wrong)` | reason `contract defect: <reason>` (escalation ladder rung 3) | `/define-goal --amend <id>` |
| `needs context` | the implementer's `NEEDS_CONTEXT` ask verbatim, unanswerable from the queue | `/define-goal --amend <id>` (add the missing fact to the goal's Context) |
| `no runnable local gate` | reason `no runnable local gate: <evidence>` (INCONCLUSIVE gate) | `/factory-doctor` |
| `environment brake` | two consecutive infrastructure-shaped gate failures stopped a batch | `/factory-doctor` |
| `environment failure` | tooling, queue, or `config.verify` failure this fire could not handle | `/factory-doctor` |
| `repeated transient death` | reason `repeated transient death` (≥3 fires observed, zero work commits) | `/dispatch <id>` once the cause is gone |
| `budget exhausted` | `budget exhausted (<n>/<cap> goals)` | raise or remove `config.budget.max_goals_per_session` in `docs/goals/index.yaml`, then `/dispatch` |
| `base: mismatch` | a goal entry whose `base:` mismatches the started branch | `git checkout <base>` then `/dispatch <id>` |
| `multiple in_progress` | `multiple in_progress claims — manual review` | manual review: pick the entry to keep, fix `index.yaml` by hand, then `/dispatch` |
| `checkout busy` | a dispatch lock fresher than ~2h exists at run start — another session owns this checkout (Phase 0) | wait for that run to finish; or, if you know it is dead, delete `~/.local/state/pg-dispatch/<SLUG>/lock` and re-run `/dispatch` |
| `conflict` | a local squash/merge conflict — two pieces of work changed the same logic | resolve the overlap by hand, or `/define-goal --amend <id>` to re-scope, then `/dispatch <id>` |
| `parallel-conflict` | a lane's rebase conflicted at integration — the touch-set prediction was wrong (goal auto-requeued for a serial re-run) | fix the mispredicted `touches:` via `/define-goal --amend <id>` if it recurs; the re-run itself needs nothing |
| `integration interference` | a lane's gate passed alone but Arm A failed on the integrated tree, and one integration-repair didn't fix it | `/dispatch <id>` serially once the interfering pair is understood, or `/define-goal --amend <id>` to re-scope |
| `unmet dependency` | a named goal whose `depends_on` are not all `completed` | `/dispatch <blocking-id>` first (the named goal is `not_started`, so `--amend` refuses it — to change the chain instead, edit its `depends_on` in `index.yaml` by hand) |
| `CI failure` | the branch's latest CI run is red (a non-blocking observation) | `gh run view --log-failed` |
| `recurring lesson` | the same gate-failure class recurring across goals | the proposed encoding site — a `config.verify` command, a `config.skills` entry, a CLAUDE.md rule, or `/define-goal --amend <id>` on a goal already `blocked` by it |
| `needs independent review` | a PASSed goal whose acceptance criteria carry the **needs independent review** marker (a non-blocking observation) | the command or surface from the implementer's report evidence, plus what to look for there (Working a goal, step 4) |

**The class set is open and NOT all classes are blocking.** `CI failure` already rides this
format as a pure observation, and a class may fire on a PASS. Adding a class = adding ONE
row here (class, trigger, what to run) — never a second line shape, and never a parallel
format section elsewhere in this skill. A class whose "what to run" is prose rather than a
fixed command (what to look at, not what to type) still fills the `→` half with that prose.

**Two channels, one shape (v12.0.0): `needs-you:` is decisions, `fyi:` is observations.**
An item renders under `needs-you:` ONLY when a human decision or human-only action is
what unblocks it — an owner fork (spend, data loss, irreversible or externally visible),
or an item the self-heal pass below already tried and could not clear. Pure observations —
`CI failure` (pre-existing red), `recurring lesson`, `needs independent review` on a
PASSed goal, a goal this run retired — render as `fyi:` bullets after the needs-you
items, same line shape, never counted as waiting on the human. Measured 2026-08-18: a
run reported "needs-you: 3 items" when exactly one needed a human — an observation in
the decision channel reads as a stop, and the owner acts on (or swears at) the count.

## Self-heal — the run fixes its own blockers before naming a human (v12.0.0)

3-day forensics across two field repos (2026-08-16/19): **~37 needs-you items, of which
~3 genuinely required a human.** The dominant class — a contract defect blocking correct
or correctly-refused work — was routed to a human command (`/define-goal --amend <id>`)
that, whenever anyone actually ran it, took ~10 minutes and needed zero owner input
("no owner fork" recorded in the amendment itself). The factory was queueing its own
homework as the owner's. So, in EVERY dispatch run (the invocation is the standing
approval — the same v11.7.0 waiver precedent process-inbox drains already use):

1. **A contract-defect settle routes through define-goal's amend machinery IN-RUN,
   not to a human.** When a goal settles (or already sits) `blocked` with a
   `contract defect: …` reason — FAIL_CONTRACT, GOAL_UNREACHABLE, CONTRACT_AMBIGUOUS,
   the escalation ladder's too-large/wrong rung, `needs context` nothing in-run could
   answer — invoke define-goal's amend mode under its **drain waiver** (v12.0.0): the
   red-team review runs UNCHANGED, question rounds never happen (take the clearly
   recommended or conservative reading and record it in the amendment note), and the
   step-7 owner confirmation is waived. Requeue and re-claim it once (the re-claim
   consumes a count unit like any claim).
2. **A disproven premise RETIRES the goal — there is nothing to amend.** When the
   evidence in hand (the implementer's report, the gate review) shows the goal's
   premise is false or its outcome already true — the defect doesn't exist, the
   metric was a misread aggregate, the capability already ships — the goal is
   retired, not amended and not left `blocked` forever: flip the entry to
   `status: retired` with `reason: retired: <premise disproven | already true> —
   <one-line evidence>`, move the entry to `archive.yaml` and the goal file to
   `docs/goals/done/` in the same `chore(goals): retire <id>` commit. When the
   settle evidence already proves the disproven premise, retire DIRECTLY — no
   intermediate block commit; a goal that is already `blocked` retires with the
   single retire commit. Retired is
   TERMINAL: it never requeues, never re-reports, and surfaces once as an `fyi:`
   line in the run that retired it. (Measured: a false-premise goal sat `blocked`
   pointing at an amend that could not exist, and a prior session invented
   "superseded" for the same state — the verb was missing.)
3. **Bounds.** ONE amend-and-re-claim per goal per RUN — a goal that blocks on a
   contract defect AGAIN in the same run stays `blocked` and goes to needs-you as
   genuinely stuck (the second defect is the evidence a human is actually needed).
   A true owner fork inside the amend — spend, data loss, irreversible or
   externally visible — is never resolved under the waiver: the goal stays
   `blocked` and the needs-you item carries the fork AND your recommendation.
4. **The blocked backlog heals too.** After Phase 1 and before Phase 2's first
   claim, walk every EXISTING `blocked` entry: reasons in the contract-defect
   family route through 1–2 above — under the SAME once-per-goal-per-run cap as
   item 3, so a backlog amend and a settle amend never stack on one goal in one
   run; `environment`-class,
   `repeated transient death`, and owner-fork reasons stay blocked as today. This
   is what lets a queue that predates this rule drain clean instead of dragging
   its history into every report.

The needs-you table's `→ /define-goal --amend <id>` rows now name what the RUN does
first; a human sees such a row only when self-heal already tried and failed. Nothing
here touches the gate: amended goals re-enter the full claim → implement → gate cycle,
and the red-team still reviews every amendment.

**Attended-only interactive questions.** Dispatch may ask the human a question directly —
instead of only writing the item into needs-you — when, and only when, ALL THREE of these
hold at once:

1. the user invoked `/dispatch` conversationally in this session (a turn you can see in
   this conversation, not a scheduled or piped invocation), AND
2. the run is single-goal-scoped — solo mode or `--count 1`; a drain or any multi-goal
   run NEVER asks, AND
3. the run is not `/loop`, `claude -p`, or `droid exec`.

When any one of the three is unknown or unverifiable, do NOT ask — write the needs-you item
and move on. A drain or multi-goal run NEVER asks, whatever the other conditions say (a
flag is a user's word about the run, not evidence about who
is watching it). Defaulting to not-asking is load-bearing: an interactive question in an
unattended fire hangs the loop or gets auto-answered by it, which is strictly worse than a
needs-you line a human reads later. Nothing here is a probe — no TTY sniffing, no env
inspection; you evaluate the three conditions from evidence you already hold.

When you do ask: ONE round, at most 2 questions, each with concrete options and a
recommended default, in the same plain language the needs-you line uses. Then act on the
answer and continue; an unanswered question falls back to the needs-you item.

## Claim protocol — every status write

The index is the claim ledger. A claim is a status flip committed BEFORE implementing:

1. Read `docs/goals/index.yaml` from the working tree (must be clean — dirty → stop and report).
2. Flip exactly one entry to `in_progress` and `git commit -m "chore(goals): claim <id>"`
   (queue commits are always their own commit, never fused with code — sole sanctioned
   exception: the plan-mirror edit rides `chore(goals): complete <id>`, Working a goal
   step 4).
3. Mid-run, push is OPTIONAL (backup only) and never gated — but the TERMINAL stop runs
   the Ship step (Phase 0, v12.0.0): where the repo's own docs carry standing publish
   authorization, an unpushed tree is unfinished work, not caution. Sequential mode is
   single-session; if you
   ever run two dispatch sessions on one local queue they race on index.yaml — don't
   (Phase 0's checkout lock now stops the second run at start, v11.6.0).

Every status transition uses the same convention — one entry, its own commit:
`chore(goals): claim|complete|block|archive|retire <id>`. These five are dispatch's closed
verb set (`retire` since v12.0.0 — the Self-heal section's terminal disposition for a
disproven-premise goal: entry to `archive.yaml` with `status: retired` + reason, file to
`docs/goals/done/`, one commit); the one status write dispatch does NOT own is
define-goal's `chore(goals): amend <id>`,
which requeues a `blocked` goal after repairing its contract (needs-you class
`contract defect (…)` above — in-run via Self-heal, by hand otherwise).

## Re-entrancy — idempotent iterations

A direct `/dispatch` run settles in-flight work first, then claims ready goals one at a
time — draining by default, fewer under `--count` (Invocation) — gating and settling each
before the next claim, reports, and stops. `/loop /dispatch` repeats the
same one-goal cycle across fires. Each run must be idempotent so a re-run after a transient death picks up
where it left off:

1. **The index is the claim ledger.** A claim is a committed status flip made BEFORE the
   implementer runs.
2. **Stale claim**: an `in_progress` entry with no work commits on the branch since its
   `claimed` date and no active agent means a prior implementer died — re-run it (re-spawn
   from its `gate_base`, which is the current HEAD since no work landed). If the implementer's
   final report named a blocker, set `blocked` with that reason. A report that declares
   `GOAL_UNREACHABLE` (the acceptance criteria can be neither satisfied nor shown measurable
   after honest attempts) is a contract defect, not a work failure: set `blocked` with reason
   `contract defect: <criterion> unreachable` — do NOT
   respawn it, a re-run hits the
   same unmeasurable check; the Self-heal pass then amends or retires it in-run
   (needs-you class `contract defect (unreachable)` only when self-heal has already
   failed on it). A final report declaring `CONTRACT_AMBIGUOUS` routes identically
   as class `contract defect (ambiguous)` (reason `contract defect: <criterion> ambiguous`) —
   a respawn guesses at the same fork. Otherwise respawn — but distinguish a transient infrastructure
   death (connection closed mid-response, parse error, 529 overloaded, a stream-idle
   timeout, a spawn whose tool result comes back empty or as a raw API error: NOT a work
   failure) from a logic blocker. The same recognition applies MID-FIRE to a spawn that
   dies under you — respawn it under the same ~3-attempt budget immediately instead of
   re-diagnosing the goal (a measured stream-idle death cost ~1h40m of near-duplicate
   repair work because it went unrecognized).
   **Death needs evidence — a terminal signal or two samples (v11.6.0).** An agent is
   dead when its spawn RETURNED (a tool result — error or empty — ended the call) or
   its completion notification says so. Absent that, silence is not death: a live
   agent can sit idle mid-turn for minutes with nothing in the process list, so a
   single probe — one `ps` scan, one glance at the tree — proves nothing. Before
   respawning over an agent that has not returned, check twice with real minutes
   between and require ZERO new commits or file activity between the checks; a
   respawn onto a live agent puts two writers in one tree (measured 2026-08-15:
   three false dead-calls in one parallel run — one target had been alive ~7h and
   already merged).
   A transient death is not a "fail" toward the no-progress rule; don't
   let it burn the respawn budget — retry it, up to ~3 transient respawns per goal per session,
   after which a goal that still can't make any commit progress IS blocked (named
   `blocked: repeated transient death`) so it can't livelock. Only a real blocker in the final
   report, or repeated failure to make ANY commit progress, sets `blocked` (a goal must never
   sit blocked for hours over one flaky connection).
   **Cross-fire brake (the per-session cap alone is not enough).** The ~3-respawn budget lives
   in this run's context, so under `/loop /dispatch` each fresh fire re-detects the same stale
   claim and restarts the budget from zero — a goal whose implementer keeps dying transiently
   before landing ANY commit would be respawned forever. Add a session-independent brake
   measured in FIRES OBSERVED, never wall-clock: count the heartbeat log's lines (Phase 4
   appends one per fire) timestamped after the claim commit's author date. Three or more
   fires since the claim with still zero work commits → block it
   `blocked: repeated transient death` instead of respawning again. Wall-clock age is NOT a
   valid proxy for attempts: an account usage-limit stop (the subscription's 5-hour or weekly
   window — see loop-architect's limit-proofing) suspends ALL fires for hours and leaves the
   same shape (old claim, zero work commits) with zero attempts actually made. An
   old-but-untried claim — fewer than 3 heartbeat lines since it — is resumed, never blocked.
   Only when no heartbeat log exists at all (e.g. pre-append plugin versions wrote a
   single overwritten line) fall back to the old age heuristic: a claim more than a few
   cadences old (e.g. > ~2h for a 15m loop) is blocked with the same
   `blocked: repeated transient death` reason. This uses only git/index data plus the runtime
   heartbeat cache (no new queue state — status-only-in-index holds), and it is what actually
   stops the cross-fire livelock without mislabeling a quota pause as a dead goal.
3. **Finish before claiming** (Phase 1 before Phase 2) so finished work always settles first.

## Phase 0 — read the queue

**Checkout lock — one dispatch per checkout (v11.6.0).** Before anything else, check
`~/.local/state/pg-dispatch/<SLUG>/lock` (`<SLUG>` = the repo dir name, as in Phase 4).
A lock whose timestamp is fresher than ~2 hours means another dispatch run owns this
checkout: STOP without claiming and surface needs-you class `checkout busy` — never
work alongside it (measured 2026-08-13/15: two live sessions in one tree cost a
stash-clobbered implementer mid-run and a drain that ended on `a concurrent session
wrote in this checkout`). Stale or absent → write the lock, one line —
`<UTC timestamp> · <branch> · <one-word session note>` — re-write it at each per-goal
cycle's claim AND settle (the settle re-write rides the Phase 4 heartbeat append),
and DELETE it at every terminal stop. A crash leaves a lock behind; that is exactly
what the ~2h staleness window absorbs, and the needs-you row names the manual
override. Advisory by design: the claim protocol still guards the QUEUE — the lock
guards the TREE, which the queue's commit ledger cannot see (uncommitted implementer
work, live lanes).

Confirm the working tree is clean. **A dirty tree is handled, not a refusal (v12.0.0).**
Foreign uncommitted changes at run start: FIRST look for a live concurrent writer — a
fresh checkout lock, or foreign files modified within the last ~10 minutes — and if one
is plausible, stop with needs-you class `checkout busy` (never commit into a contested
tree; three real two-writer collisions, 2026-08-18). No live writer → quarantine the
dirt in ONE labeled commit, `chore(wip): foreign tree state at drain start`, name it in
the report, and PROCEED — the commit predates every `gate_base`, so no gate verdict
covers it, and it is never squashed into any goal's commit. Never stash silently, and
never end a run over dirt nobody is writing (measured 2026-08-18: a drain refused to
start over unrelated dirty files 24 minutes after the owner had said "full complete all
remaining things"). A DIVERGED branch still stops and reports — that is history
surgery, not dirt. If `docs/goals/index.yaml` is missing, report "no goals queue —
create goals with /define-goal" and end the iteration.

If `config.base` is set and the current branch != `config.base`, STOP and report — you are on
the wrong working branch; checkout `<config.base>` first (mirroring the per-goal `base:`
mismatch handling in Phase 2 — never silently work on the wrong branch).

**Drained-queue terminal stop.** Dispatch stops when there is nothing left to do: when Phase 2
finds no ready goals AND needs-you is empty. Exactly ONE closing line ends the run — never
both: a run that worked ≥1 goal closes with Phase 4's final summary line (`stopped:
drained`, inbox pointer per Phase 4); a run that finds the queue already drained at start
(zero goals worked) emits `factory drained — <done>/<total> done` instead (appending
` · inbox: <N> captured → /process-inbox` when `docs/goals/inbox.md` has unconverted
items — conversion is the next visible action, never a buried footnote) and stops. A terminal stop still runs Phase 4 first — the drained fire reports and heartbeats
before stopping. A later `/dispatch` (or `/loop`) re-run picks up newly-added goals — a `/define-goal` +
`/dispatch` resumes from wherever the queue now stands.

**Ship step — every terminal stop (v12.0.0): unshipped is not done.** Before the
closing line, if the target repo's OWN CLAUDE.md/AGENTS.md carries a standing
authorization to publish — "push every time", "commit and push without asking", a named
release command declared pre-authorized — RUN that path now and put the outcome in the
closing line (`shipped: <push|command> ok` / `ship FAILED: <one clause>` as needs-you
class `environment failure`). No standing authorization in the repo's docs → one clause,
`not shipped (no standing authorization)`, and nothing more — never an offer, never
"say the word". The rule keys STRICTLY off the target repo's own docs; dispatch never
invents a deploy. Measured 2026-08-18: a run reported `21/21 done` with 30 unpushed
commits in a repo whose CLAUDE.md both authorizes and REQUIRES the push — the owner
found out a day later that "done" had shipped nothing, and a manual recovery session
did the release.

**Chain to the inbox — a user-invoked flagless drain finishes the loop (v12.0.0).**
When a flagless drain the USER invoked ends `stopped: drained` with ≥1 unconverted
inbox line, do not point at `/process-inbox` — INVOKE it, flagless, once. Chain guards,
both hard: never when THIS dispatch run was itself invoked by process-inbox step 6 (the
chain never loops), and at most one chain per session. Count-limited runs, solo mode,
and stops other than `drained` keep the pointer instead — the chain is for "one
command, everything done", not for every fire. (The pointer alone measured as a 10.5-hour
human latency on 45 captured items, 2026-08-17.)

At end-of-drain only (NOT per-goal — no polling), if the working branch has a remote AND `gh`
is available and authenticated, do ONE non-blocking check of the latest CI run on the current
branch (`gh run list --branch <current> --limit 1`); if it is failing, surface it under
needs-you as class `CI failure` — a non-blocking observation (never block, never wait on
it). If `gh` or the remote is absent, skip silently (`gh` is optional).

**Latest-context preflight (read-only, never a gate).** Before spawning an implementer, gather
only the context that helps avoid stale work:
- Latest plan/progress note if present: newest `docs/superpowers/plans/*.md`, then
  `.superpowers/sdd/progress.md` if present.
- Latest PR context if `gh` is available: prefer an open PR for the current branch
  (`gh pr view --json number,title,url,reviewDecision,statusCheckRollup`); otherwise the most
  recently updated open PR (`gh pr list --state open --limit 1 --json ...`). If there is no PR
  or `gh` is unavailable, record `none`.

Summarize this in at most five bullets and pass it to the implementer under "Latest context".
PRs, plan docs, and review comments are context only. They do not create a merge gate, they do
not authorize a branch switch, and they do not override the goal contract or the local gate.

Read the queue with a real YAML parser (`python3 -c 'import yaml,sys; …'`), never line-greps
or ad-hoc `jq` — grep probes on the queue invent phantom statuses and miscounts that cost an
extra verification round every fire. Cheap doctor pass, flagged in the report rather than
silently fixed: every entry has its goal file and vice versa; no circular `depends_on`; no
`depends_on` pointing at a missing entry; warn when a goal and its dependency declare
different `base` branches. Plan-mirror re-sync (the one doctor fix applied, not just
flagged): the goal→phase mapping lives in GOAL files, never in plans — scan the
`Plan: docs/goals/plans/<file> — Phase <N>` Context lines of goal files in
`docs/goals/` AND `docs/goals/done/` (archived goals still anchor their phase),
resolve each goal's status from `index.yaml`/`archive.yaml`, and rewrite any plan
checkbox that disagrees — plan follows index, never the reverse — stamping
`status: done` on a plan whose phases are now all checked; committed
`chore(goals): plan-sync` only when something actually drifted. The sync (and
the settle mirror) edit checkbox/status text ONLY — a plan's `artifact:`
presentation page belongs to ideate's approval touches and is never republished
by dispatch.

On any environment failure you can't handle (missing tooling, an unrunnable `config.verify`
command, a queue the claim protocol can't write), stop the iteration and surface it under
needs-you as class `environment failure` — `/factory-doctor` diagnoses and fixes setup so the loop stops failing
the same way every fire instead of burning quota on a wall it can't clear.

**Implementer-cost awareness.** When goals resolve to an expensive session model (no per-goal
`model:` fields and `config.model: inherit`) and the queue is mostly `type: chore`
(mechanical, no-behavior-change work), note once in the report that the implementers inherit
your model and that the repo owner can have define-goal stamp per-goal `model:` fields (or
set `config.model`) if they want that trade. Do not name or apply a fixed alias yourself.

`$PGVALIDATE` resolution (do this once, before the first gate) — ONE bash block, the same
shape goals-status uses (`find`, never a brace-glob: zsh aborts the whole command when any
brace alternative fails to match):

```bash
PGVALIDATE="$CLAUDE_PLUGIN_ROOT/skills/dispatch/scripts/pg_validate.py"
[ -f "$PGVALIDATE" ] || PGVALIDATE=$(find ~/.claude/plugins ~/.factory/plugins/cache -path '*/flywheel/*/skills/dispatch/scripts/pg_validate.py' 2>/dev/null | sort -V | tail -1)
[ -n "$PGVALIDATE" ] || echo "pg_validate.py not found — reinstall/update the flywheel plugin"
DISPATCH_REFS="${PGVALIDATE%/scripts/pg_validate.py}/references"
```

Hold the resolved absolute paths in `$PGVALIDATE` and `$DISPATCH_REFS` — the latter is
where this skill's reference files live (implementer-brief.md, parallel-mode.md,
escalation-and-repair.md), Read on demand at the step that names them.

## Working a goal — the canonical per-goal sequence

For each claimed goal, in order:
1. `anchor` = current HEAD (clean). `git commit` the claim → `gate_base` = HEAD now.
2. Spawn ONE foreground implementer (Agent, run_in_background: false) that works in this
   checkout on the current branch under the method mandates (writing-plans, TDD,
   verification-before-completion) + config.skills + the goal's `skills:`. It uses the
   lightweight subagent-driven quality loop in the canonical brief
   (`$DISPATCH_REFS/implementer-brief.md` — Phase 3), commits its work on the branch,
   writes its full evidence to a report file, and ends with a terse fixed-format `STATUS:`
   report + a one-line `Fresh-check:` verdict (step 3's independent review challenges
   both). It never merges, never opens a PR.
3. Run the LOCAL gate authoritatively yourself. The gate has two independent arms over
   the same frozen `gate_base..HEAD` range — the deterministic commands (Arm A) and the
   independent review (Arm B) — and neither consumes the other's output, so OVERLAP
   them: start Arm A in the background, spawn Arm B in the foreground, and join both
   before any verdict. (The old review-then-commands serial order idled minutes per goal
   for zero added safety; the combined-verdict rule below is unchanged.)
   **Arm A — the gate commands, started FIRST, in the background.** ONE Bash call,
   `run_in_background: true`, that runs
   `python3 "$PGVALIDATE" --head HEAD --base <gate_base> --goal <id> --goal-file docs/goals/<id>.md`
   then each `config.verify` command in order, echoing every exit code, so the join
   reads one output file and reconstructs the full result. A background COMMAND is safe
   where a background REVIEW spawn is banned (the implementer brief's fresh-check scar): its exit
   codes and log land in an output file you Read at join time — nothing returns through
   a turn that can be discarded. The overlap is an optimization, never a requirement:
   when the harness gives you no reliable background-shell mode (run it foreground on
   Droid), or when the mechanical carve-out below skips Arm B, there is nothing to
   overlap — run the same commands in the foreground and read them directly; the
   verdict rule is identical either way.
   **Arm B — independent review — maker–checker, ALWAYS for non-trivial work.** The implementer's
   report must still carry its `Fresh-check:` block (the lens verdicts, or the literal
   `Fresh-check: not required (one-file mechanical edit)` for work that genuinely is) — but
   that block is corroborating evidence, never the verdict: the implementer graded its own
   work. For any diff bigger than a one-file mechanical edit, spawn ONE fresh read-only
   adversarial reviewer — the gate-reviewer plugin agent (`flywheel:gate-reviewer` on
   Claude Code, `gate-reviewer` on Droid) when the runtime lists it, else the generic
   type with the role stated inline (Named review agents above); no model
   override either way, review agents always inherit the session model — over the
   `gate_base..HEAD` diff plus the goal file, and hand
   it the `Fresh-check:` line and the implementer's report-file path to challenge — this
   reviewer runs even when they look
   clean. Its brief: try to REFUTE the work, not confirm it — (a) contract conformance:
   any acceptance criterion unmet or met vacuously; (b) test realness: proving tests assert
   real behavior, not tautologies or mirrors of the implementation — hunt the measured
   vacuous shapes by name: errors swallowed inside a proving loop, a sweep hand-capped
   below its claimed coverage, input pre-sorted/pre-narrowed so the swept variable cannot
   vary, the subject mocked out of its own test, and a full-confidence claim with no
   precondition check behind it; (c) scope: changes
   beyond the goal's surfaces, or criteria quietly narrowed. Two calibration rules go in
   the brief: report half-believed findings too, marked uncertain, instead of silently
   dropping them — the orchestrator is the verifier, and a finder that self-censors
   uncertain candidates is the dominant source of missed defects; and a Critical finding
   must name the inputs/state that trigger it plus the wrong outcome, quoting the offending
   line. A scope-of-reading BUDGET goes in the brief too, and it is a number, not a
   preference: read the diff once (with its context lines it is the complete view of the
   changed files); step outside it for AT MOST TWO risks the reviewer can NAME, one cheap
   read-only command each, both named in the report; the whole review is ~15 tool calls,
   and passing that means stop and report what you have. What can't be verified that way
   is an uncertain finding — never a license to sweep the repo. Spell out what is NEVER a
   focused check, because a strong model will otherwise do all four: running the build /
   lint / typecheck / test suite (Arm A owns those, concurrently), mutation testing a copy
   of the tree, independently re-deriving what the diff computes (hashes, oracles,
   fixtures, expected outputs), and probing via a written scratch script — read-only
   covers the shell too, so the reviewer creates no file anywhere, including /tmp. An
   unbudgeted reviewer costs 8× on the same diff and finds no more: measured 2026-07-29
   over 11 real gate reviews — 43 min and 181k output tokens per review unbudgeted versus
   5 min and 14k budgeted, on diffs of the same size, with the cheap reviews catching real
   defects in two of the goals. Coming back fast with an `(uncertain)` finding is the
   designed outcome; the orchestrator settles it in one command. One concurrency rule goes in
   the brief too: Arm A's gate commands are running in this checkout concurrently — do
   read-based verification first and run any named-risk command check LAST (by then the
   commands are normally finished; a command check colliding with a live install/build
   produces phantom failures, not findings). And two anti-laundering rules:
   a stated rationale in the implementer's report never downgrades a finding's severity
   (the maker grading its own work), and a defect the goal contract itself mandates is
   still a finding, labeled contract-mandated — the contract's authorship does not grade
   its own work. Non-findings (tell the reviewer up front): failures already red on the pre-goal
   baseline per the implementer's report, and the gate's auto-exempted test paths — but
   the baseline claim is itself a hypothesis: a reviewer that doubts it reports the doubt
   as an uncertain finding, and you verify it cheaply (does the same failure reproduce at
   `gate_base`?) rather than taking either side's word.
   It returns a verdict per lens
   plus findings with severity and `path:line` evidence. Findings are hypotheses you
   verify yourself against the diff and the cited evidence — never orders; verified
   Critical/Important findings enter the FAIL_FIXABLE repair
   path like any gate finding — EXCEPT a verified contract-mandated finding, which is a
   contract defect: route it FAIL_CONTRACT (reset + block, needs-you class
   `contract defect (finding)`) —
   a repair agent cannot fix code into a defective contract.
   **The mechanical carve-out (the ONLY legal reviewer skip).** A genuinely one-file
   mechanical edit skips the reviewer — but the skip is an explicit, evidenced decision,
   never a default. It is legal ONLY when (a) the `gate_base..HEAD` diff touches exactly
   one file, AND (b) the change is mechanical — a rename, a constant/config value, a
   comment/doc line, a regenerated artifact — with no new branching, no signature/API
   change, no test-logic change; any doubt means not mechanical. Judge both from the
   DIFF itself (`git diff <gate_base>..HEAD --stat` then the diff body), never from the
   implementer's claim or its `Fresh-check: not required` line — the maker's claim about
   its own work is corroboration, not license. State the decision in the fire's
   reporting either way (the `last:` field carries `reviewed` or `review-skipped:
   mechanical` — Phase 4); a silent skip is indistinguishable from a forgotten reviewer
   in any later audit, and goal 113 of the 2026-07-24 batch settled exactly that way.
   The deterministic gate + `config.verify` still run in full there; that carve-out is
   what keeps the second view proportional.
   **Escalation to the full panel.** A missing `Fresh-check:` block, a
   `not run (no fresh-context mechanism available)` verdict, or a not-required
   claim the diff belies (multi-file work, or a single-file diff whose changes are plainly
   substantive rather than mechanical), upgrades the single reviewer to the full 2–3 read-only
   lenses (same lenses as the implementer brief's fresh-check step, fresh windows, concurrent —
   spawned foreground as the fresh-check plugin agent when the runtime lists it, else
   the generic type — Named review agents above).
   Decide this BEFORE spawning any reviewer — the implementer's report and the diff are
   already in hand — and run the panel INSTEAD of the single reviewer, never after it. A
   skipped implementer panel is a compliance miss: when the same miss recurs across goals
   in this session's fires (no persisted counter — session memory only, per the
   status-only-in-index rule), surface it once via Hygiene's lesson-encoding rule. An
   HONEST `not run (no fresh-context mechanism available)` is NOT a compliance miss — it is
   the implementer correctly refusing to self-review where the harness gives it no fresh
   context; it escalates your own review to the full panel and nothing more. What IS a miss
   is a panel silently skipped, or claimed but self-run in the implementer's own context.
   **Join — no verdict before BOTH arms are in hand.** When Arm B returns, Read Arm
   A's output file (commands still running → wait on that task; never grade a partial
   gate). Show the command output. Every `config.verify` command must exit 0, exactly
   as before — the overlap moves wall-clock, never the bar.
   **Flake protocol (bounded, logged — never a repair).** When a verify command fails on
   a test the diff does not touch and the goal's surfaces do not reach, re-run THAT test
   once in isolation before rendering the verdict: an isolated pass is a flake — count
   the command as passed, name the flake in the fire's report, and on the second flake
   in one session (same or different test) surface a needs-you `recurring lesson`
   proposing quarantine/deflake; an isolated fail is a real FAIL. One retry maximum,
   never a repair spawn for a flake — a measured session burned three full re-gate
   cycles on flaky tests that passed 4/4 in isolation. A failure in anything the diff
   DOES touch gets no retry: that is the gate working.
4. PASS → `git reset --soft <gate_base> && git commit -m "feat(goal <id>): <slug>"` (squash to
   one), then `chore(goals): complete <id>`; push if a remote exists (non-blocking).
   **Plan mirror (v11.0.0, plan-backed goals only).** If the goal's Context carries a
   `Plan:` link, flip that phase's `- [ ]` to `- [x]` in the plan file INSIDE the same
   `chore(goals): complete <id>` commit (the claim protocol's one sanctioned
   exception), appending `· as-built: matched` — or one line naming the deviation,
   from the gate review already in hand (v11.2.0) — and stamping frontmatter
   `status: done` when the last open phase checks. A DISPLAY mirror only:
   `index.yaml` stays the sole status authority, Phase 0's doctor pass re-syncs
   drift plan-follows-index, and a missing/unwritable plan file is a one-line
   report note, never a settle blocker.
   **Then, on every PASS, surface the goal's subjective criteria.** define-goal marks a
   criterion no command can settle **needs independent review** and tells the goal author it
   reaches a human under needs-you at integration — so after the squash, re-read
   `docs/goals/<id>.md` and collect every acceptance criterion carrying that marker. For each
   one, emit an `fyi:` item as class `needs independent review` (an observation, never a
   decision — the two-channel rule; needs-you above supplies
   the `→` half; this class has no `index.yaml` block reason to quote — the goal PASSed — so
   its `<reason>` half is the criterion's own subject, e.g. `007 — subjective criterion:
   checkout page calm`). Render the `→` half as **what to run and what to look for** — the
   command, URL, or surface the implementer's report actually exercised for that criterion
   plus the thing a human should judge there — drawn from the implementer's report file,
   never the criterion text repeated verbatim (a criterion echoed back is the
   diagnosis-without-an-answer the format exists to end). Report evidence too thin to name a
   surface? Say so in the `→` half and name the report path — never drop the item. A goal
   whose criteria carry no such marker surfaces nothing: no empty item, no "none"
   placeholder. This is an observation, never a completion gate — a PASS still completes the
   goal, the entry stays `completed` with no new status or sign-off state, and an unattended
   `/loop /dispatch` drain keeps claiming the next goal whether or not a human ever reads the
   item. Then run Settle triage (below) and report; the run claims the next ready goal
   unless a stop condition (Invocation) has fired.
   FAIL_FIXABLE → one repair round per `$DISPATCH_REFS/escalation-and-repair.md` — warm
   resume of the goal's own implementer when the harness supports continuing it, else one
   fresh repair agent on the same resolved tier; the COMPLETE verified findings list in
   one go, the receiving-review rules appended, re-gate with the step-3 overlap
   (commands background, focused re-check foreground, join both); still failing →
   `git reset --hard <gate_base>`,
   `chore(goals): block <id> — <reason>`. FAIL_CONTRACT → reset + block, reason
   `contract defect: <the verified finding>` (needs-you class
   `contract defect (finding)`). INCONCLUSIVE → reset + block "no runnable local gate: <the
   failing check's
   `evidence` from the JSON>" (needs-you class `no runnable local gate`) — the evidence names the exact cause and operator fix (e.g.
   the Windows symlink privilege below), so it must reach the block reason, not die in the
   gate output.

`anchor`/`gate_base` matter: the claim's `index.yaml` edit lands BEFORE `gate_base` is set,
so the validated diff (`gate_base..HEAD`) is exactly the implementer's work — never the queue
write. A `git reset --hard <gate_base>` discards only the implementer's commits; the claim
commit survives, ready to be flipped to `blocked` by the claim protocol.

The gate verdict comes from `pg_validate.py`'s JSON `verdict` field (PASS=exit 0,
FAIL_FIXABLE/FAIL_CONTRACT=exit 3 — read the JSON to split them, INCONCLUSIVE=exit 4) AND
the `config.verify` commands (any non-zero exit = the gate fails as FAIL_FIXABLE for that
command's failure). You run the gate — the implementer's verification summary is evidence,
not the verdict.

## Settle triage — nothing survives as prose (every settle, PASS or FAIL)

Real 2026-08 forensics: a 30-goal drain ended with 55 needs-you follow-ups — three of
them production-impacting defects and six explicit "needs a new goal" items — and six
days later ZERO existed in any queue. Chat prose evaporates when the session ends; only
committed artifacts survive. So, BEFORE a goal's settle commit, walk every loose end
this cycle produced — each `Concerns:` line of a DONE_WITH_CONCERNS report, every
reviewer finding you verified real but out-of-scope, every "needs a new goal" /
"follow-up" recommendation in the implementer's report, every recurring-lesson
proposal — and give each item exactly ONE of these four dispositions:

1. **Repair now** — it breaches THIS goal's own contract → it is a gate finding; route
   it FAIL_FIXABLE (`$DISPATCH_REFS/escalation-and-repair.md`). A DONE_WITH_CONCERNS
   whose concern invalidates an acceptance criterion is not a PASS.
2. **Dismiss** — verified false, purely cosmetic, or already tracked → one line of
   reasoning in the goal's report file (the `## Orchestrator` section — "the fire's
   report" is always that FILE, never the chat turn; Phase 4's envelope).
   A dismissal without reasoning is disposition 3 or 4.
3. **Capture** — real, outside this goal's contract, AND over the capture bar →
   append ONE line to
   `docs/goals/inbox.md` (create the file on first use) and commit it
   `chore(goals): inbox <id>`:
   `- [ ] <YYYY-MM-DD> <source-goal-id> <bug|feature|chore> — <one-line description> (evidence: <report path or path:line>)`
   **The capture bar (v11.6.0) — exactly three shapes earn an inbox line:**
   (a) a LIVE defect — wrong behavior reachable on current code; (b) genuinely
   NEW work — missing wiring, a missing consumer, a feature gap the owner would
   want built; (c) an OWNER decision — spend, data loss, anything irreversible
   or externally visible.
4. **Report-only** — real but under the bar: latent or unreachable-today
   findings, fail-safe residuals, deliberate contract-mandated tradeoffs,
   test-caption/comment-wording nits, watch items. One line in the goal's report
   file naming the item and this disposition; its full detail already lives in the
   implementer's/reviewer's report file, which is its permanent home (git and
   the report dir keep it findable). Measured 2026-08-13/16 across two real
   repos (~70 settles): capture-everything appended ~1.5–2.5 inbox lines per
   completed goal, over half of them adjudicated keep-grade nits at triage — the
   live defects were buried among latent ones, re-verifying the exhaust cost
   more than the findings were worth, and converted residue refilled the queue
   with goals that bought no coverage. The bar keeps the inbox a queue of work,
   not a review archive.

A goal does NOT settle `completed` while any of its loose ends is unclassified — that
is the definition of "complete" this factory ships. The inbox is capture-only: no
statuses, no priorities, never touched by implementers. define-goal reads it, converts
items to real goal contracts (batch mode at ~5+), and removes converted lines — that
conversion is the ONLY edit anyone but dispatch makes. This closes the completion leak
without violating status-only-in-index: inbox items are pre-goals awaiting definition,
not queue state.

**Windows note.** `type: bug` goals prove repro-direction in a temporary base worktree whose
dep dirs (root `node_modules`/`.venv` & co plus per-workspace-package `node_modules`) are
symlinked from the live checkout. Creating those links needs the Windows symlink privilege —
Developer Mode (Settings → Privacy & security → For developers) or an elevated session;
without it the gate returns an actionable INCONCLUSIVE naming that fix (never a false PASS),
so every bug goal blocks until it's enabled (chore/feature goals never build a base
worktree and are unaffected). `factory-doctor` preflights this
(`symlink-privilege` WARN). The gate's command runner is tunable via `PG_BASH` (full path to
the POSIX shell; auto-resolution already skips the WSL launcher stub) and
`PG_VALIDATE_TIMEOUT` (seconds per acceptance command, default 1800).

## Parallel mode — the lane model (`--parallel` / auto-parallel drains, Claude Code only)

The full lane model — admission control, the lane lifecycle, the serialized
integration lock, and every failure ruling — lives at
`$DISPATCH_REFS/parallel-mode.md`. Read that file BEFORE claiming a wave whenever a run
carries `--parallel`, whenever a flagless drain auto-enters lane mode (Invocation:
`config.parallel` present without `auto: false`), and whenever Phase 1 finds
lane-backed claims (`git branch --list 'lane/*'`) to settle. The one-paragraph version: N goals BUILD
concurrently in disposable local worktree lanes; admission requires provably-disjoint
`touches:` (a goal without `touches:` runs alone) and excludes conflict domains
(lockfile, migrations, CI, global config); integration stays strictly serial — rebase
the lane onto branch HEAD, re-run Arm A on the integrated tree, squash, fast-forward —
so the branch only ever advances to gate-verified trees.


## Phase 1 — finish in-flight goals

Before claiming anything new, settle every `in_progress` entry — finished work beats new work.

**Single-`in_progress` invariant (data-loss guard) — lane-aware since v9.0.0.** In
serial operation a healthy queue has at most ONE `in_progress` entry. FIRST check for
lanes: an `in_progress` entry whose `lane/<id>` branch exists (check
`git branch --list 'lane/*'` and `git worktree list`) is a parallel-mode claim — its
work lives in the lane, not on the branch, so the reset-past-newer-work hazard does not
exist for it. Settle each lane-backed entry through the Parallel-mode lifecycle from its
furthest checkpoint: lane has commits → run its in-lane gate and integrate (one at a
time); lane empty → respawn its implementer in the lane (transient-death budget
applies); lane branch listed but its worktree directory missing → recreate the worktree
at the branch tip. For entries with NO lane, the serial guard is unchanged: MORE than
one lane-less `in_progress` on a linear branch means a `git reset --hard` on the older
one could destroy the newer one's committed work — STOP, roll back nothing, and surface
`multiple in_progress claims — manual review` under needs-you as class
`multiple in_progress`. (That state only arises from a
crash between claims, a manual index edit, or a prior buggy run; resume once a human resolves
it.) When exactly one lane-less `in_progress` exists, proceed:

`gate_base` is not stored in `index.yaml`, so on a fresh session recover it from git: it is the
SHA of the goal's claim commit on the current branch,
`git log --grep="chore(goals): claim <id>" --format=%H -1` (the gate then diffs
`gate_base..HEAD`). For each `in_progress` entry, decide by whether work commits exist on the
branch after that claim commit:

1. **Work commits present after the claim commit** → recover `gate_base` as above, then run the
   gate (Working a goal, step 3) against it (if the dead session's implementer report file
   exists at `~/.local/state/pg-dispatch/<SLUG>/reports/<id>-report.md` (`<SLUG>` = the repo
   dir name), hand it to the
   reviewer as usual; absent is fine — the diff and goal file suffice). PASS → squash +
   `chore(goals): complete <id>`.
   FAIL_FIXABLE → one repair agent, re-gate (incl. the focused review re-check); still
   failing → `git reset --hard <gate_base>` +
   `chore(goals): block <id> — <reason>`. FAIL_CONTRACT → reset + block (needs-you class
   `contract defect (finding)`). INCONCLUSIVE → reset + block "no runnable local gate:
   <evidence>" (needs-you class `no runnable local gate`; same
   evidence-in-reason rule as step 4).
2. **No work commits after the claim commit and no active agent** (stale claim — the
   implementer died) → `gate_base` is the current HEAD (no work landed). Apply the stale-claim
   rule from Re-entrancy: re-spawn the implementer from current HEAD, or `blocked` per its final
   report / `GOAL_UNREACHABLE` / transient-death cap.

## Phase 2 — claim the next goal

Ready = `status: not_started` AND every `depends_on` entry is `completed` — a `blocked`
dependency makes dependents not-ready; report the stuck chain. Pick `priority: high` first,
then top-most in the file; claim via the protocol BEFORE spawning. A per-goal `base:` field
in the index entry overrides `config.base` for that goal (epic integration branches) — but
since dispatch works on the currently-checked-out branch sequentially, a goal whose `base:`
differs from the started branch is surfaced under needs-you as class `base: mismatch`
(switch branches and run a separate session), never silently worked on the wrong branch.

If `config.budget` is set and `max_goals_per_session` is exhausted, stop claiming (Hard
rules) and let the current goal finish. Never claim a goal while another is unsettled —
every run claims the next goal only after the previous goal fully settles (Invocation).

## Phase 3 — spawn the implementer (depth 1, foreground)

One Agent per claimed goal, `run_in_background: false`. In serial mode (default): NO
worktree — it works in THIS checkout on the current branch. In parallel mode the same
brief applies with only the Workspace paragraph substituted
(`$DISPATCH_REFS/parallel-mode.md`), and all wave spawns go out foreground in ONE
message. Set the spawn's `model` parameter to the goal's resolved implementer tier
(Implementer-tier resolution above; `inherit` = omit the parameter). Where the harness
supports named agents, name the spawn (e.g. `impl-<id>`) — the warm repair round
resumes it by name.

The brief is canonical and lives at `$DISPATCH_REFS/implementer-brief.md` — Read it,
fill in `<id>`, `<SLUG>` (= the repo dir name, same as the Phase 4 heartbeat), the
resolved skill lists, and the latest-context bullets, and pass the filled block as the
spawn prompt. Never paraphrase the brief from memory — the brief file is the contract.

After the implementer returns, run the independent review and the gate yourself
(Working a goal, steps 3–4). Any status other than a clean `DONE`, and any gate verdict
other than PASS, routes through `$DISPATCH_REFS/escalation-and-repair.md` — the warm
repair round, the receiving-review rules, the focused re-check, the escalation ladder,
and the contract-defect short-circuits (CONTRACT_AMBIGUOUS / GOAL_UNREACHABLE /
NEEDS_CONTEXT / BLOCKED) are all specified there. Read it when a status or verdict
demands it and follow it exactly — never improvise a repair or a block from memory.

## Solo mode — work one named goal in this session

The default model is already one-goal-at-a-time on the current branch, so "work goal
005" — or the argument forms `/dispatch 005`, `/dispatch 5`, `/dispatch 005-slug`
(Invocation) — just scopes the run to a single id: skip Phase 2's ready-scan, claim
that goal directly
via the protocol, and run it through Working a goal (anchor → claim → foreground implementer
→ local gate → PASS squash+complete / FAIL roll back+block). Everything else — the brief, the
gate, the rollback — is identical, and the run stops after that one goal (a batch flag
alongside an id is ignored — the id wins). Guards before claiming: a named goal that is
`completed` or already `in_progress` is reported, not re-claimed; one whose
`depends_on` are not all `completed` is surfaced under needs-you as class
`unmet dependency` instead of claimed —
dependency order is part of the contract (amend the chain via define-goal to mean it);
an id matching no entry reports the near-misses.

## Phase 4 — report (the report IS the message — nothing rides along)

`[dispatch] <done>/<total> done [<bar>] · ready: <count> · blocked: <count> · inbox: <unconverted inbox lines, omit when zero> · current: <id or none> · last: <id PASS (reviewed | review-skipped: mechanical)|FAIL|none> · needs-you: <blocked goals + human decisions, or nothing>`

**The output envelope (v12.0.0) — the rule the line format never stated.** Measured
2026-08-16/19 across eleven real orchestrator sessions on two harnesses: every session
emitted the report line correctly, then wrapped it in 2,000–4,100 characters of
headed prose — "What shipped", "judgment calls worth your review", "two things I'd
flag about my own conduct" — including 2,749 characters for a single-goal run. The
owner's verdict on that output, verbatim: "i don't want to see bullshit." So:

- **A per-goal settle turn is the report line and NOTHING else.** No headings, no
  narrative recap of the goal, no gate story, no "claiming X next". Everything you
  want to say about a goal — findings verified or refuted, dismissal reasoning,
  Report-only items, judgment calls where you overrode a reviewer — is APPENDED to
  the goal's report file (`~/.local/state/pg-dispatch/<SLUG>/reports/<id>-report.md`,
  under an `## Orchestrator` heading). That file is where Settle triage's "one line
  of reasoning" lives too — "the fire's report" always means that FILE, never the
  chat turn.
- **The closing turn is: the report line, the summary line, one bullet per needs-you
  item, one bullet per fyi item. Nothing else, and never a second closing message.**
  No "What happened" section, no tables, no epilogue after a system reminder. Hard
  ceiling ~15 lines; a needs-you bullet's reason half stays under its ~120-char cap.
- **Interstitial narration between report lines is at most one short sentence** and
  never restates a finding, a diff, or a verdict.

Lead with **progress** (`<done>/<total>`), never `ready/total` — a bare `ready/total` reads
as "nothing done" to a human. Every number carries its label. The counts come from the index
after this iteration's mutations:
- `done` = completed · `ready` = not_started with all `depends_on` completed (claimable now) ·
  `blocked` = `blocked` status or not_started with an unmet dependency · `current` = the goal
  being worked this fire (or none; in parallel mode the live lane ids, `+`-joined —
  e.g. `current: 131+134` — per the Parallel-mode lifecycle) · `last` = the most recently gated goal and its verdict
  (a goal settled this fire WITHOUT a gate run — a live BLOCKED / GOAL_UNREACHABLE /
  CONTRACT_AMBIGUOUS short-circuit — reports `<id> FAIL` here; needs-you carries the detail).
  A gated `last` also names its review decision — `<id> PASS (reviewed)` or
  `<id> PASS (review-skipped: mechanical)` — so the mechanical carve-out (Working a goal,
  step 3) leaves an audit trail in every fire's report, never a silent skip.
- Any residual `in_progress` entry this fire could not settle (e.g. one claimed on a different
  `base:` branch) counts into `blocked` (as blocked-pending) so that `done + ready + blocked`
  always equals `total` — the reconciliation the report line promises a human never silently
  breaks.

The bar is 20 cells: `filled = round(20 × done ÷ total)` (0.5 rounds up), clamped to [0, 20];
empty = 20 − filled. Filled cells = █, empty = ░; omit the whole bar when total = 0.
Anchor example: 19/21 → round(18.10) = 18 filled → `[██████████████████░░]`.

**Every multi-goal run** (the drain default included): the one-line report above is
emitted after EACH settled goal, and one final summary line closes the run:
`[dispatch] worked <n>: <id PASS|FAIL|RETIRED, …> · stopped: <count reached|drained|budget exhausted|environment brake> · shipped: <outcome per the Ship step> · <all complete | outstanding: <n> for you>`
(the summary line itself appends no extra heartbeat — heartbeats are per-goal-cycle).
**The closing state is a word, not an essay (v12.0.0):** `all complete` when the queue
is drained, nothing is blocked, and needs-you is empty — the literal phrase the owner
asked to see; otherwise `outstanding: <n> for you` where `<n>` counts exactly the
needs-you bullets that follow (fyi items never count). When the run stops with a
non-empty inbox and the Phase 0 chain rule doesn't fire (count-limited, solo, or an
in-chain run), the summary carries the conversion
pointer — `inbox: <N> captured → /process-inbox` — so captured follow-ups are the next
visible action, never a buried footnote. This summary line is the run's ONE closing
line; Phase 0's `factory drained` line replaces it only when the run worked zero goals
(the queue was already drained at start — see the terminal stop, Phase 0).

needs-you lists what is genuinely waiting on the human AFTER the Self-heal pass has run:
goals still `blocked` because their defect needed a second amend or hides an owner fork
(with the dependents stuck behind them), a `base:`-mismatched goal needing a branch
switch, `budget exhausted`, an environment the run could not clear. The
non-blocking observations — a red CI run, a `recurring lesson`, every criterion marked
**needs independent review** on a goal this fire PASSed (Working a goal, step 4: those goals
are `completed`, so the item asks for a look, not a decision), a goal this run retired —
render under **`fyi:`** instead (the two-channel rule in the needs-you section): same
line shape, after the needs-you bullets, never counted in `outstanding:`. A
**dep-blocked** goal (not_started, waiting on another goal still running or not yet ready) is
NOT human-blocked: it unblocks on its own, so it never appears here on its own — only as a
"dependent stuck behind" a goal that is human-blocked. Every iteration, not only new ones —
except the non-blocking observations, which belong to the fire that produced them (nothing
persists a PASSed goal's review items, per status-only-in-index).
Every item is written in the canonical needs-you format (see needs-you above): its class's
`→ <what to run>` half is not optional — an item with no command is the
diagnosis-without-an-answer this format exists to end.

**Stalled factory → one real notification.** A report line in an unattended run has no reader.
The fire that first finds the factory fully stalled — needs-you non-empty and nothing this
iteration could do about it — sends the needs-you line via the PushNotification tool
(ToolSearch loads it if deferred). One notification per distinct blocker set;
identical no-op fires after it send no further notifications, though the report line still goes
out every fire — new blocker content notifies again.

**Heartbeat (liveness) — every fire** (in a multi-goal run, once per per-goal cycle — each
cycle is one fire). APPEND a one-line heartbeat —
`<UTC timestamp> · <done>/<total> · current <id or none> · drained <yes|no>` — to the runtime
cache at `~/.local/state/pg-dispatch/<SLUG>/heartbeat` (`<SLUG>` = the repo dir name;
`mkdir -p` first; after appending, trim the file to its newest ~50 lines) — and
re-write the checkout lock's line (Phase 0) in the same step. The log serves two
readers. (1) Liveness: a silently-dead orchestrator (a 500 / context-exhaustion mid-turn)
emits nothing, so the next `/dispatch` — or an external watcher — compares the newest line's
age to the expected cadence and treats a long silence as a dead-loop signal, turning silent
death into a detectable anomaly. (2) The cross-fire brake (Re-entrancy) counts lines after a
stale claim's date to measure fires observed — which is how a usage-limit pause (no fires, so
no lines) is told apart from a goal that keeps failing across live fires. The drained flag
also feeds the drained-queue terminal stop (Phase 0). `factory-doctor`'s queue-liveness probe
reports the same staleness from the queue side (stale `in_progress` claims), and its
limit-resilience probe warns when this loop has no way to survive a usage-limit stop.

## Hygiene

When `completed` entries crowd the index (~20+), move their files to `docs/goals/done/`
and their entries to `docs/goals/archive.yaml` in one `chore(goals): archive` commit —
and move any plan stamped `status: done` to `docs/goals/plans/done/` in the same commit
(finished plans otherwise accumulate beside live ones). The
queue commit is always its own step (see the claim protocol). Agents read the whole index
every iteration — keep it small.

**Encode recurring lessons.** When the same class of gate failure recurs across different
goals (the same lint family, the same missing verify step, the same scope-creep shape),
that is a system defect, not a string of per-goal bugs: surface ONE needs-you line as class
`recurring lesson`, its `→` half
proposing where to encode it — a `config.verify` command, a `config.skills` entry, a
CLAUDE.md rule, or a contract fix via define-goal — so future implementers inherit the
rule instead of re-learning it one blocked goal at a time. Propose only; the repo owner
decides what lands.
