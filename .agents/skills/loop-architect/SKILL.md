---
name: loop-architect
description: Use when the user wants to automate, schedule, or run work autonomously/remotely — setting up a /goal, /loop, routine, channel, or long unattended run, or asking "how do I keep the agent working on X". Designs the loop contract (prompt + verification + stop conditions) instead of just running the task.
argument-hint: "[what should run autonomously]"
---

# Loop Architect

Design loops and goals the way Boris Cherny does: "Turn workflows into skills, then loop them."
Output of this skill = a concrete, copy-pasteable setup (goal contract, loop prompt, or routine
prompt) with verification and hard stops — not a vague plan.

## Intake rule

Start with a short brief: repeated task, target repo/system/environment, gate command(s),
state file/ledger, budget/cadence, tools available, and the stop/escalation condition. Ask
one concise proactive question round (max 4 questions) when any of those missing pieces
changes the primitive, safety, or verifiability. If enough context exists, proceed with
explicit assumptions. If the user is also asking to create work for the factory, pair this
skill with define-goal: design the repeat mechanism, then return to a real goal artifact
(`docs/goals/` entry or run-now command). Do not leave the user with loop advice only.

## Step 1 — Qualify (the four-condition test)

A loop pays off only when ALL four hold. Check honestly; if one fails, recommend a plain
one-shot prompt instead and say which condition failed.

1. **Repeats** — the task recurs at least ~weekly (or runs many iterations within one goal)
2. **Automated gate** — a test / typecheck / build / linter / benchmark can REJECT bad output
   without a human in the room
3. **Budget** — the user's plan can absorb retries and re-reads (loops explore and waste)
4. **Tools** — the agent can run what it changes and see what breaks (logs, dev server,
   browser extension, simulator, MCPs)

**Closed first, open later.** Default to the most bounded primitive and scope that still
solves the task — a *closed* loop (defined steps, a gate after each, tight blast radius);
widen to a broader open-ended goal only after the gate has demonstrably rejected bad output
in practice. Every loop that fails dies one of four deaths — runaway cost, silent death
(stands still, pretends alive), aimless drift, or shipping faster than you can review — and
all four are cheaper to prevent in a bounded loop than to detect in an open one.

## Step 2 — Pick the primitive

Anthropic's official loops guidance ("Getting started with loops") names four loop types;
they map onto this table as: **turn-based** = a plain prompt + verification skills (no loop
primitive — Step 1's one-shot answer), **goal-based** = `/goal`, **time-based** = `/loop` /
routines via `/schedule`, **proactive** = the no-human-in-real-time compositions (the
docs/goals queue + repeated `/dispatch`, routines/automations, channels — goals, skills,
workflows, and auto mode composed in). A user asking for a "proactive loop" over a work
stream (bug reports, triage) usually wants the queue row or a routine, not just a channel.
(Workflows, agent teams, and Stop hooks below aren't loop types — they're building blocks
a loop composes.)

| Situation | Primitive |
|---|---|
| Work until a verifiable end state is true | `/goal` (Claude Code; a separate small-fast-model evaluator — default Haiku — checks after every turn) |
| Poll/babysit on a cadence while a session is open | `/loop <interval> <skill-or-prompt>` |
| Recurring default maintenance for this repo | bare `/loop` + a `.claude/loop.md` |
| A backlog of shippable changes worked unattended | docs/goals queue — fill with `define-goal`, then `/dispatch` (v10.0.0: a flagless run DRAINS the queue on the checked-out branch; `/loop /dispatch` only re-drains as new goals arrive) |
| Drain must survive account usage-limit stops (subscription 5-hour/weekly windows) | Window-timed attended drains: `/dispatch` (drains by default since v10.0.0; `--count N` to size it) started right after a limit reset, repeated per window — the limit-proof shape around the backlog row; in-session `/loop` dies silently at the limit (see Step 5 limit-proofing) |
| Must run with the laptop closed | Routine (`/schedule`; cloud; schedule / API / GitHub triggers) |
| Needs local files, machine on, no session open | Desktop scheduled task |
| React to external events (CI, chat) instead of polling | Channels (`--channels`) or Routine API trigger |
| Massively parallel / adversarial / unknown-size work | Dynamic workflow (pair with `/goal` for hard completion) |
| A few collaborating peers that message each other (competing debug hypotheses, cross-layer feature) | Agent teams (own contexts + shared task list; markedly more tokens than subagents) |
| Deterministic check on every turn, all sessions | Stop hook |

Combos are normal: workflow + `/goal` for hard completion; skill + `/loop` for
cadence; routine/automation + channel for laptop-closed with phone telemetry.

Workflow thresholds (per platform docs): >5 independent agents or a multi-stage
find→verify→synthesize loop → workflow; 2–4 parallel
lookups → plain subagents, cheaper and simpler; anything that must survive the session
(cross-iteration implementers, multi-day queues) → the `docs/goals/index.yaml` ledger plus
repeated one-goal dispatch runs, never workflow state — workflows are session-bound and don't
resume across sessions. Dispatch implementers may use workflows only for bounded read-only
fan-out or review inside that one goal, never as parallel code-writing lanes. Agent teams are
interactive-session machinery, never a factory lane — dispatch implementers don't spawn
teammates. The Workflow
tool needs Claude Code ≥2.1.154 and can be disabled; design a plain-subagent
fallback for when it's unavailable.

## Step 3 — Write the contract

### For /goal — six elements, one cap (condition max 4,000 chars)

CRITICAL CONSTRAINT: the `/goal` evaluator (Claude Code's configured
small-fast model — default Haiku, a Claude Code setting) only reads the
transcript. It cannot run commands or read
files. Every clause must be demonstrable by output the agent prints (test results, exit
codes, diffs, counts). Never write taste conditions ("clean", "better", "high quality").

```
/goal <end state> verified by <command + expected output the agent will print>
while preserving <what must not regress/change>.
Work only within <files/branches/tools boundaries>.
Between iterations, record what changed, what the check showed, and the next best action.
If blocked or no valid paths remain, stop and report attempted paths, evidence, the
blocker, and what would unlock progress.
If the same check fails the same way twice in a row, or after ~3 honest attempts the end
state can neither be reached nor shown measurable (a flaky, non-deterministic, or
contradictory check), declare GOAL_UNREACHABLE: <which clause, why unmeasurable, last
measurement> and stop — never retry the identical failing approach. Before stopping on
success, re-print the final check outputs. Stop after <N> turns.
```

- Evaluator mechanics that shape the condition (verified against the shipped CLI): the
  evaluator reads a RECENCY-truncated transcript (roughly the newest half of its context
  window) and answers "insufficient evidence" when proof may sit in the omitted prefix —
  hence the template's closing-turn recap of the final check outputs; long runs should
  also announce "turn N of cap M" so the turn cap stays provable. Its built-in
  `impossible` verdict is what honors GOAL_UNREACHABLE — but only with evidence attached
  (its prompt treats a bare "can't be done" as evidence, not proof). Evaluation is
  deferred while background tasks/workflows run — the workflow + `/goal` combo judges
  only after the fan-out settles.

- Reachability pre-check: before drafting the condition, confirm the end state is one the
  agent can drive to TRUE and MEASURE — a binary or a threshold it can print — not an
  asymptote ("every page < 50ms") or an unmeasurable absolute. An unreachable target spins
  forever; fix the target before writing the goal. Pair it with the GOAL_UNREACHABLE escape
  hatch above so the loop terminates even when a check turns out flaky in practice.
- Include an explicit outcome taxonomy for queue-like work ("every item ends as
  fixed | acknowledged-stale | abandoned | blocked-external; 0 items left unclassified") —
  a missing "blocked" bucket makes the goal bounce forever on reality.
- Prefer two small goals with a checkpoint over one mega-goal.
- Unattended runs: pair the goal with auto mode — auto mode removes per-tool permission
  prompts, `/goal` removes per-turn prompts (complementary, not redundant). `/goal` is a
  session-scoped Stop hook under the hood: it needs a trusted workspace with hooks enabled
  (`disableAllHooks` blocks it, and the command says why).
- If the user's ask is vague, run pre-goal calibration: ask what "done" means until it is
  specific and measurable, THEN draft the condition for approval. Keep the question round
  short; derive code-level detail from repo recon instead of asking the user to debug for you.

### For /loop — skill-first

1. Confirm the task ran manually at least once reliably. If not, do that first.
2. Put the procedure in a skill (scope, exact checks, allowed actions, FORBIDDEN actions,
   state-file location, one-line status format per iteration). The loop body is then just
   `/loop 10m /skill-name`.
3. Fixed interval for predictable cadence — match it to how often the watched thing
   actually changes (don't poll a nightly job every 5 minutes); omit the interval to let
   the agent self-pace (1m–1h based on observed activity; it may switch to the Monitor
   tool and stream instead of polling); bare `/loop` uses `loop.md` if present — project
   `.claude/loop.md` beats user `~/.claude/loop.md`.
4. Remember mechanics: fires between turns only, 7-day expiry, jitter up to 30m on
   recurring tasks, Esc cancels a pending iteration, restored on `--resume`.

### For routines (cloud) — fully autonomous, no permission prompts exist

The prompt must be self-contained: what to read, what to do, how to verify, where to write
results, what success means, what to escalate. Pushes only to `claude/`-prefixed branches
unless unrestricted pushes were explicitly enabled. Scope repos, connectors, and network
access to the minimum the routine needs.
Create conversationally with `/schedule` (recurring or one-off); manage with
`/schedule list|update|run`. Scheduled cadence has a 1-hour minimum (custom cron via
`/schedule update`); API and GitHub event triggers are added on the web
(claude.ai/code/routines).

## Step 4 — Wire verification and state (non-negotiable)

- **Gate**: name the exact command(s) that can fail the work, and require their output in
  the transcript / PR / summary.
- **Maker/checker split**: for anything substantial, a separate verifier (subagent,
  workflow verifier, or /goal's evaluator)
  judges the work — never the agent that wrote it.
- **State file**: a markdown/board/ledger outside the conversation records done/next/blocked
  so the next run resumes instead of restarting. Name the file in the prompt. For factory
  work, the canonical ledger is the `docs/goals/index.yaml` queue (created by `define-goal`,
  worked by repeated one-goal `/dispatch` runs) — prefer it over inventing a new state file.
- **Self-verification tooling** (Boris's #1, "2-3x the quality"): browser extension for web
  UI, simulator MCP for mobile, runnable server + tests for backend. Name the tool in the
  prompt and describe it.
- **Liveness**: each iteration writes a heartbeat (cycle number + timestamp + one-line
  status) to the state file/ledger and announces the cycle number, so the ABSENCE of an
  update is detectable — a loop that silently dies (e.g. after a context-window blowout)
  otherwise looks alive. For unattended/cloud runs, recommend an external silence-detector
  ("no heartbeat in N intervals → alert"). Note a usage-limit stop is indistinguishable
  from silent death on the heartbeat alone — Step 5's limit-proofing rail is what tells
  them apart and survives it.
- **Health metric**: the number that matters is cost (tokens/$) per ACCEPTED change — a
  gate-passed completed goal or a passing artifact — not raw tokens or loops run. A sustained
  acceptance rate below ~50% means the loop is making slop: tighten the gate or stop it. For
  factory work the completion ledger (`index.yaml` completed count) is the acceptance
  denominator. (The v4 dispatch model has no PRs — nothing is "merged"; a goal is accepted when
  it passes the local gate and its squashed commit lands on the branch.) Numerator data
  comes from the built-in usage surfaces: `/usage` (recent usage by skill/subagent/MCP),
  `/goal` with no arguments (the active goal's turns + token spend), `/workflows`
  (per-agent tokens, stoppable mid-run).

## Step 5 — Hard stops and safety rails

In-prompt caps are the SOFT layer — the agent can edit its own context, so a drifting loop
can weaken or delete its own brakes. Where the runtime allows it, the load-bearing brake (the
hard token/dollar/iteration ceiling AND the pass/fail gate) must be enforced by something the
agent CANNOT edit: a Stop hook, an external cron/budget process ("burnstop"), the CI gate,
/goal's separate evaluator, or dispatch's `config.budget`. "Install the brakes before the
horsepower" — and never let the loop grade itself against a criterion it can rewrite.
(One caveat on `/goal` as a brake: its evaluator FAILS OPEN on its own errors — an
evaluator API failure lets the session stop with the goal unmet — so on an unattended run
it is never the ONLY rail; the docs/goals ledger + the window-timed drain pattern (below)
stay the hard layer.)

Always include, in the prompt itself (the soft layer, restated for the agent):
- Max iterations / turn cap ("stop after 25 turns", "max 3 retries on the same finding")
- No-progress detection ("if the same error appears twice without progress, stop and report")
- Convergence stop for review/verification loops: stop when the gate verdict clears even if
  cosmetic nits remain — treat reviewer comments as findings to verify, not orders to obey,
  and cap review rounds. Chasing a perfectly clean review spawns fresh nits forever.
- Token budget for workflows ("+200k budget") — workflows balloon 5–10× without one; and
  pilot on a smaller slice first (a dynamic workflow can spawn hundreds of agents — gauge
  cost before the full run)
- The repo's hard rules verbatim (e.g. forbidden merges, protected branches, prod flags) —
  hooks are a backstop, not the encoding
- Human gate before merge / deploy / dependency changes
- Quarantine: agents reading untrusted content (tickets, scraped pages) get no
  high-privilege tools; separate actor agents never see the raw text

### Usage-limit proofing (long runs on subscription plans)

A subscription usage limit (the 5-hour rolling window; a separate weekly window) blocks EVERY
turn until its reset time. An in-session `/loop` simply stops
firing, in one of two shapes — neither self-recovering: hit the limit BETWEEN turns and the
banner just blocks new prompts (no hook fires, SessionEnd never reports it); hit it MID-turn
and the turn dies on a rate-limit API error, the one case a `StopFailure` hook can observe.
Either way the CLI ships no wait-until-reset auto-resume. Treat the limit like a power cut,
not an error the loop can handle from inside. Rails, in order of leverage (owner decision
2026-07-28: the factory runs in-subscription and in-session — no fast mode, no headless
`claude -p` scheduling; the prior cron/launchd→`claude -p` rail is retired):

- **Drain the window, don't trickle into it.** The limit-proof shape is a window-timed
  ATTENDED drain: at (or right after) a limit reset, start ONE interactive session and run
  `/dispatch` (a flagless run drains by default since v10.0.0; `--count N` sizes it to
  the window when you want a cap) so the run front-loads
  work into the quota that just refreshed instead of a `/loop` trickling fires into a
  window that then throttles mid-goal. Dispatch's per-goal cycles are settled and
  idempotent, so a batch the limit kills mid-goal costs nothing: the next window's drain
  settles the in-flight goal first (Phase 1) and continues. Cycle-time forensics
  (2026-07-28) showed limit pauses — not work — were the largest wall-clock sink in
  real factory sessions; timing drains to the reset clock attacks exactly that.
- **Read the reset clock, don't guess it.** The statusline stdin JSON carries
  `rate_limits.five_hour.resets_at` / `rate_limits.seven_day.resets_at` (Unix epoch
  seconds; subscription plans; present after the session's first API response) — note
  the value BEFORE the window dies (it's only readable inside a live session, so the
  session that hits the limit is the one that knows when the next window opens) and
  time the next drain to it. A `StopFailure` hook with
  the `rate_limit` matcher fires when a turn dies mid-flight on a rate-limit API error
  (informational only; it misses the between-turns banner shape — never the only rail).
  On Droid no equivalent reset-clock surface is verified — time drains by wall clock.
- **Respect the weekly window.** `seven_day.resets_at` can be days away — draining an
  exhausted weekly window hourly is pure noise; stand down until that reset.
- **`/loop` stays the in-window cadence option, eyes open.** For polling/babysitting
  within a window `/loop /dispatch` still works; know that it dies silently at the limit
  (the heartbeat's per-fire line is what makes that death detectable afterwards) and
  hands unclaimed work to the next window's drain. It is a cadence tool, not a
  limit-survival rail.
- **Bookkeeping survives on its own.** The docs/goals ledger plus dispatch's fires-observed
  cross-fire brake already treat a quota pause as "no attempts made" (stale claims resume,
  never get blocked as dead). `factory-doctor`'s `limit-resilience` probe warns when a repo
  with a live loop has none of these rails.

## Step 6 — Remote layer (offer when relevant)

- Steer from phone: `claude --rc <name>` or `/remote-control`; server mode
  `claude remote-control --spawn worktree` for multiple phone-spawned sessions.
- Telemetry: `/config` → "Push when Claude decides"; or "notify me when X
  finishes" in the prompt; channels (Telegram/Discord/iMessage) for two-way chat into a live
  session.
- Laptop closed: routines + Claude Code on the web; teleport (`&` / `--teleport`) to move
  sessions between local and cloud.

## Output format

Deliver: (1) chosen primitive + one-line why, (2) the exact contract/prompt block ready to
paste, (3) the gate + state file, (4) the hard stops included, (5) any skill/loop.md file to
create — create it if the user agrees or has asked for setup. Keep it to one screen.
