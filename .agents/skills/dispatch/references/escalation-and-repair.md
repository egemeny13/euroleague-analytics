# After the implementer returns — repair, escalation, contract routing

Read this file when an implementer returns any status other than a clean `DONE`, or
when the gate verdict is anything other than PASS.

One status routes elsewhere: `DONE_WITH_CONCERNS` is not an escalation — its concerns
are settle-triage input (SKILL.md, Settle triage: repair now / dismiss with reasoning /
capture to the inbox), and only a concern that invalidates one of THIS goal's own
acceptance criteria enters the repair path below as a gate finding.

## FAIL_FIXABLE — the repair round (warm first)

A `FAIL_FIXABLE` verdict gets ONE repair round, fed the COMPLETE verified findings list
in one go (including any verified Critical/Important findings from the independent
review) — never one repair per finding.

**Warm resume is round one (v10.0.0).** When the harness can continue the goal's own
implementer agent with its context intact (Claude Code: message the named implementer
agent you spawned — its window already holds the goal, the code, and the tests, so a
resume costs a fraction of a cold spawn; turn count beats token price), resume it with
the findings list plus the receiving-review rules below. When the harness cannot resume
(Droid, an agent that died or errored, or the resume itself fails), spawn ONE fresh
repair agent instead — same brief as the implementer, same resolved implementer tier,
findings appended. **Replay detection (v12.0.0):** a warm resume that returns with ZERO
new commits and a report indistinguishable from the previous one is the harness
replaying the old turn, not work — treat that resume as failed, disable warm resume for
the REMAINDER of this run, and spawn fresh (measured 2026-08-17 on Droid: three
consecutive warm resumes each "completed" by replaying the implementer's prior final
message verbatim with zero work, caught only by manual lane inspection). Either way it is one repair round: re-gate after it (commands in the
background, focused re-check in the foreground, join both); a second identical FAIL →
roll back + block, exactly as the no-progress rule requires. Never add a second repair
round to a warm resume — if the warm round couldn't fix it, the finding goes to a human
with the evidence, not to another spawn.

**The repair brief appends four receiving-review rules:** verify each finding against
the code before changing anything; a finding you can disprove gets a one-line rebuttal
with evidence in the report instead of a "fix" — the orchestrator adjudicates it; after
fixes, sweep your OWN repair diff once for new instances of the exact defect classes you
just fixed — a real repair reintroduced a just-fixed defect class in a different file
and cost a full duplicate implementer cycle (~4h, 2026-07-31) — and re-run the tests
covering the amended code, appending both results to the report
file — the focused re-check reads evidence, it does not re-run your tests.

**Adjudicating a rebuttal:** verify it against the code and the cited evidence
yourself — confirmed false → drop the finding from the re-check scope (note it in the
report); upheld → it goes back unfixed, and the re-gate treats it as an open failure.

**The focused re-check** (when verified review findings drove the repair): one fresh
read-only agent — the gate-reviewer plugin agent else the generic type, session model —
scoped to exactly those findings PLUS a one-pass collateral scan of the repair diff
itself (a fix can break a neighbor), not a new full panel; its budget is TIGHTER than
the full review's, ~8 tool calls, and the brief says so: the full review already
happened, so nothing outside the named findings and the repair diff is in scope — not
the rest of the goal, not a risk the first pass left unchecked.

## Contract-defect short-circuits (no gate, no ladder)

A `CONTRACT_AMBIGUOUS` return is a contract defect caught early, not a work failure: if
any work commits landed before the stop, `git reset --hard <gate_base>`; set the goal
`blocked — contract defect: <criterion> ambiguous` —
never respawn it to "try a reading", the respawn guesses at the same fork.

`GOAL_UNREACHABLE` likewise skips the ladder: roll back any work commits
(`git reset --hard <gate_base>`) and block with reason
`contract defect: <criterion> unreachable` — never a respawn; same routing as
Re-entrancy.

**Then Self-heal owns the block (v12.0.0 — SKILL.md, Self-heal section).** Every
contract-defect block above routes through define-goal's amend machinery IN-RUN under
the drain waiver (red-team unchanged, one amend-and-re-claim per goal per run), and a
block whose evidence disproves the goal's premise RETIRES the goal instead
(`chore(goals): retire <id>`). It reaches needs-you as a `contract defect (…)` class
only when self-heal already failed on it this run, or the amend hits a true owner
fork.

A live `NEEDS_CONTEXT` or `BLOCKED` return skips the gate — there is nothing to certify
yet — but does NOT go straight to `blocked`: run the escalation ladder first.

## Escalation ladder — before any goal blocks

Each rung fires at most ONCE per goal per session, and never as a
same-model-unchanged respawn — if the implementer is stuck, something must change (more
context, a stronger model, or a better contract). A ladder re-spawn continues from the
current branch state (same claim, same `gate_base`; roll nothing back — the gate
certifies the whole `gate_base..HEAD` diff regardless of which spawn produced it):

1. **`NEEDS_CONTEXT`** → answer it from what you hold — the queue, sibling goal files
   and their Interfaces notes, the latest-context bullets, repo config — and re-spawn
   once with the answer added to the brief. Nothing you hold answers it → roll back any
   work commits and block with the ask as the reason (needs-you class `needs context`).
2. **`BLOCKED`, capability-shaped, on a cheap-stamped goal.** The goal's resolved
   implementer tier is `medium` or `light` AND the blocker reads capability-shaped (an
   architectural fork within contract bounds, "reading file after file without
   progress") → ONE re-spawn on the session model: omit the tier mapping entirely —
   the session model is the strongest judge available in this run, so dropping the
   pin IS the escalation (never pass a lighter tier, and never pass `heavy` instead:
   inherit-the-session-model is the rung) — noted in the report line. Never
   downgrade; goals already resolved to
   `inherit`/`heavy` skip this rung — capability was not the gap there.
3. **Too large / contract wrong.** A blocker that reads "the goal is too large" or "the
   contract is wrong" → the contract-defect route: roll back, block with
   `contract defect: <reason>`, then the Self-heal pass amends (or splits via
   define-goal) in-run — needs-you class `contract defect (too large / wrong)` only
   when self-heal fails. Never respawn — a respawn hits the same wall.
4. **Anything else** → roll back any work commits and block with the implementer's
   stated reason, as today.
