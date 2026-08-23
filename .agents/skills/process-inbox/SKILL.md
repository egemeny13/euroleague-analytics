---
name: process-inbox
description: Use when the user runs "/process-inbox" (optionally --triage-only) or asks to process, triage, clean up, or work through docs/goals/inbox.md — the follow-up capture file dispatch appends at settle time ("what's in the inbox", "convert the inbox", "deal with the captured follow-ups", "clear the inbox"). Flagless runs END TO END: verify, triage, fix the mechanical items, convert the real ones through define-goal's machinery, then drain the queue via dispatch — one command, cleared inbox. Always through the factory's own rails — goal conversion stays in define-goal's flow, non-trivial implementation stays behind dispatch's gate; --triage-only stops at the handoff.
argument-hint: "[--triage-only]"
---

# Process-inbox — verify, triage, and clear the captured follow-ups

## Overview

`docs/goals/inbox.md` is dispatch's settle-triage capture file: one `- [ ]` line
per discovered defect or follow-up that was real but outside its source goal's
contract (date, source goal id, type guess, description, evidence pointer).
Dispatch only ever APPENDS. This skill is the sweep that clears it, with
the discipline the first large field pass proved out (romy, 2026-08-13: 101 items
→ 31 goals, 20 dead lines deleted, 3 settled by querying production — after EVERY
item was re-verified against current code).

**Flagless = drain (v11.7.0, owner decision 2026-08-17 — "one command, come back
to a cleared inbox").** A flagless `/process-inbox` runs the WHOLE path in one
session: verify → triage → FIX-NOW batch → convert through define-goal's inbox
intake with the approval table waived (the drain invocation is the standing
approval; the contract red-team still runs on every draft) → hand the queue to a
normal flagless `/dispatch` drain. The run is never a confirmation point — an
invented mid-drain permission-ask ("want me to convert these?", "should I start
dispatch?") is a compliance miss, dispatch v10's rule applied here. The OWNER
bucket is still the only thing that waits for a human, and it waits at the END
of the report, never mid-run. `--triage-only` restores the pre-v11.7 behavior:
stop after the ledger commit, present the convert list, queue nothing beyond
what define-goal is separately asked to take.

**The one law: verify before you route.** Captures age. The measured base rate on
a weeks-old inbox is ~20% dead — code deleted since capture, fixed in passing, or
disproved on a closer read. An item's evidence pointer is where verification
STARTS, never a substitute for reading the code as it stands today. Converting an
unverified item queues phantom work; deleting an unverified item loses a real
defect. ONE exception (v11.6.0): a line a PREVIOUS sweep already stamped
`KEEP <date>:` is not re-verified — it retires to the ledger (step 1), already
adjudicated once. (Since dispatch v11.6.0 the settle-time capture bar admits only
live defects, new work, and owner decisions — latent/nit findings stay in report
files — so a fresh inbox arrives lean; older inboxes still carry the pre-bar mix.)

**Boundaries.** This skill never writes goal files or index entries in its own
context (define-goal does, behind its contract review), never implements
non-trivial work in its own context (dispatch does, behind the gate), and never
touches inbox lines outside the set it processed. The drain does not blur this:
it CHAINS those skills in sequence — their machinery, reviews, and gates run
unchanged; only the per-batch approval touch is waived because the owner
approved the whole drain by invoking it. No question rounds: the OWNER bucket
below is the only thing that waits for a human.

## The process

### 1. Read and cluster

Read `docs/goals/inbox.md`; count open `- [ ]` items (zero → report "inbox
empty" and stop). **Retire stamped keeps first (v11.6.0 — KEEP is one-cycle
parole, not residence):** any open line whose tail already carries a
`KEEP <date>:` stamp from a PREVIOUS sweep skips verification and triage
entirely — it retires to the `## Triaged` ledger in step 5. It was adjudicated
once; its full detail lives in the source report file and git history, and if it
ever becomes live, a fresh dispatch capture re-surfaces it. Measured 2026-08-16:
a sweep re-verified 28 previously-adjudicated lines at real subagent cost and
changed almost none of them. **OWNER lines carried over from a previous sweep are
RE-ADJUDICATED against the v12.0.0 OWNER bar (step 3), never re-listed as-is:** run
the blast-radius check the bar demands; a line that fails the bar re-triages into a
normal bucket this sweep (which usually means it gets converted or fixed), and only
a line that still clears it — a proven, still-live consequence — is re-presented,
with its check attached. The same five OWNER lines were re-printed verbatim across
three sweeps until the owner cleared them in one instruction; a parking lot is not
a bucket. Then cluster
the remaining unstamped items by the file/subsystem their evidence points at,
folding obvious duplicates (two captures naming the same function and the same
change are ONE item). Aim for one cluster per verification subagent, ~5–15 items
each.

### 2. Verify fan-out — every item re-checked against current code

Spawn one read-only verification subagent per cluster (foreground, concurrent,
cap ~8 per wave; more clusters → more waves). Claude Code:
`flywheel:recon-analyzer` when the runtime lists it, else `general-purpose` —
either way on the medium tier (`model: sonnet`); never the built-in Explore
type. Droid: `explorer` with `complexity: medium`, else `worker` with the
verification brief inline. Strictly read-only.

Each brief: "For each item below: does the described defect or opportunity exist
in the CURRENT code? The evidence pointer is your starting point, not your
answer — read the code as it stands. Return per item: CONFIRMED (current
`path:line` refs + one-line restatement) | DISPROVED (what the capture missed) |
GONE (the code was deleted or the fix already landed — name the commit if
visible) | UNVERIFIABLE-HERE (only a live/production system can settle it — name
the exact query that would). Evidence for every verdict; no fixes, no writes."

Judgment stays with you, on the session model: subagent verdicts are input, the
triage is yours.

### 3. Triage — every item into exactly ONE bucket

- **CONVERT** — confirmed and worth a factory cycle. **Mechanism check (v12.0.0):**
  an item whose fix names a specific mechanism — an alert channel, a queue, a
  binding, a secret — gets that mechanism verified LIVE (read-only) before it enters
  a contract; a measured item's recommended `sendOpsAlert` fix would have paged
  nobody (`ALERT_WEBHOOK_URL` unset in both environments), and only the session that
  checked caught it. Folding rules (measured):
  captures that are one change to one function fold into ONE goal; a cluster
  still carrying more than two independent findings splits — the repair-cost
  rule wins ties (a goal closing more than two independent findings costs more
  repair rounds than it saves). **One class never converts (v11.6.0):
  caption/comment-wording items** — a test name or comment overclaiming what
  its assertion pins, doc phrasing — go FIX-NOW or DROP, never to a goal:
  measured on the first field batch (romy goal 106), four of five findings in a
  caption-class goal resolved by narrowing the wording, so the factory cycle
  bought no coverage; define-goal's intake refuses the class for the same
  reason.
- **FIX-NOW** — confirmed, and genuinely mechanical with no behavior change: a
  wrong comment or caption, a stale doc sentence, a dead constant, a
  typo-class rename. The bar is dispatch's review-skip bar, judged from the
  would-be diff itself; the measured why is that a full factory cycle per
  comment typo costs more than the typo. Any doubt, any test logic, anything a
  reviewer could argue with → CONVERT instead.
- **DROP** — DISPROVED or GONE. The line is deleted, its why recorded (step 5).
- **PRODUCTION-CHECK** — UNVERIFIABLE-HERE. If this session can reach the live
  system read-only (a query, a log read), run the named check now and re-triage
  on the result; otherwise it goes to the report's needs-you list with the
  exact query spelled out.
- **KEEP** — real but deliberately not actionable yet: needs a measurement
  first, blocked on a pending decision, unreachable at current caps. Stays
  captured, reason appended to its line.
- **OWNER** — a decision that is provably the human's: it spends money, deletes or
  exposes data that EXISTS today, or is irreversible/externally visible outside the
  repo's own gated path. **The bar (v12.0.0) — a proven consequence, not a matching
  topic.** Before anything is routed OWNER, run the read-only check that sizes the
  blast radius — the `SELECT` on the table the deletion would touch, the secret/bucket
  listing the alert depends on, the count of affected rows — and attach the check and
  its result to the item. An empty or absent target is NOT a data-loss decision —
  the item then re-triages as ordinary work (a still-real preventive fix CONVERTs,
  a dissolved claim DROPs); a
  change confined to code behind the factory's own gate is NEVER an owner item
  (shipping is what the factory is for); "for convention's sake", "worth your
  attention", and "recommend X" are CONVERT or FIX-NOW. An item whose own
  recommendation is a code edit the gate can verify is not an owner item. Measured
  2026-08-16/19: five items topic-matched into OWNER, sat through three sweeps, and
  four of the five dissolved under one read-only production query — the fifth's
  recommended fix was itself WRONG (`sendOpsAlert` would have paged nobody; only the
  override session checked). The bucket wasn't deferring risk, it was accumulating it.
  Present each surviving item with a recommendation; never act on it. This is the only
  bucket that waits for a human — and only items that clear the bar may wait.

### 4. Act, in this order

1. **FIX-NOW batch:** apply all mechanical fixes as ONE commit
   (`chore(inbox): direct fixes — <N> items`), then run the repo's
   `config.verify` commands (else its detected build+test). On failure: when
   the output plainly names ONE fixed file as the culprit, drop just that fix
   (demote its item to CONVERT) and re-run ONCE; any other or any second
   failure → revert the whole batch, demote every FIX-NOW item to CONVERT,
   and say so. Green → those lines are processed.
2. **CONVERT handoff:** invoke `define-goal` (inbox intake) with the CONVERT
   list inline — each inbox line verbatim plus its verdict and current
   `path:line` evidence; at ~5+ items that list IS define-goal's batch-mode
   item list. Items arrive pre-verified:
   define-goal's recon narrows to verify-and-complete (the plan-backed
   pattern), its contract red-team runs unchanged, and it
   deletes each converted line in the same commit as the index entry — exactly
   its own intake rules. **In a flagless drain the approval table is waived**
   (define-goal's drain-waiver rule): assumptions that would have gone in the
   confirmation are recorded in each goal's Context instead, and a
   contract-blocking red-team finding that one repair pass can't fix demotes
   that item to KEEP with the finding as its reason — never a mid-drain
   question round. A true OWNER fork inside a conversion (spend, data loss,
   irreversible/externally-visible) moves the item to the OWNER bucket
   unconverted. Under `--triage-only` the approval table runs as before. This
   skill writes no goal file and no index entry in its own context, ever.
3. **PRODUCTION-CHECK:** run what is runnable read-only; re-triage each result
   through step 3's buckets — a result can land anywhere, including FIX-NOW
   or OWNER.

### 5. Ledger and commit

Update `inbox.md` in one commit (`chore(goals): inbox triage YYYY-MM-DD`):

- DELETE dropped lines and fixed lines; converted lines go with define-goal's
  own commits.
- RETIRE previously-stamped KEEP lines (step 1): delete each from the open list
  and record it in the `## Triaged` section as one line —
  `retired keep: <gist> — <its original KEEP reason>` — so the adjudication
  survives in the ledger and git without costing another verification pass.
- Record the pass as a short `## Triaged YYYY-MM-DD` section: counts per
  bucket (retired keeps included), the notable folds, and one line of why per
  drop — the same ledger shape the field passes left, so the file carries its
  own history.
- KEEP lines stamped THIS sweep stay `- [ ]` with `KEEP <date>: <reason>`
  appended — they retire on the NEXT sweep; OWNER lines stay untouched
  until the owner decides.

Push if the repo pushes on completion.

### 6. Drain the queue (flagless runs only)

Invoke `dispatch` flagless — the normal drain, exactly as if the owner had run
`/dispatch`: it claims ready goals until the queue is empty, auto-entering lane
mode where `config.parallel` says so, with every gate, budget cap, and brake it
always has. Nothing is special-cased for inbox-born goals; if the queue held
older ready goals, they get worked too — that is the factory working, not scope
creep. New captures dispatch appends DURING this drain are next sweep's input,
never this one's (the never-touch-unprocessed-lines rule). Under
`--triage-only`, skip this step and end at the report with the convert-list
handoff stated.

### 7. Report

One summary, counts first — `<N> items → <X> goals queued (<ids>) · <Y> fixed
directly (<commit>) · <Z> dropped dead · <K> kept · <P> production checks ·
<O> for you` — then, on a flagless drain, dispatch's own final report line
(`<done>/<total> done` + bar, blocked reasons, needs-you) — then each OWNER
item in one plain-language line with your recommendation. **That is the ENTIRE
message (v12.0.0):** the counts line, dispatch's line, one line per OWNER item —
no "What happened" section, no tables, no caveats, no epilogue; the detail lives
in the committed `## Triaged` ledger. `<O>` must EQUAL the number of OWNER lines
printed below it (a measured report said "6 for you" and listed 5). "Nothing else
needs the owner's eyes" is a hard envelope, not advice — the measured violations
ran to ~3,000 characters.

## Red flags — stop and get back on the path

- Converting or dropping an item no subagent verified THIS session → verify
  first.
- Writing a goal file or index entry here → that's define-goal's, always.
- A FIX-NOW item that changes behavior, touches test logic, or needs an
  explanation → CONVERT.
- A verification subagent asked to fix anything → read-only, always.
- Asking the owner about any bucket except OWNER → triage is yours.
- Deleting an OWNER line, deleting a KEEP line stamped THIS sweep, or editing
  lines outside the processed set (retiring a PREVIOUSLY-stamped KEEP to the
  ledger is step 5's job, not a deletion).
- Re-verifying or re-triaging a previously-stamped KEEP line → it retires
  unread; KEEP is one-cycle parole.
- Converting a caption/comment-wording item into a goal → FIX-NOW or DROP,
  never CONVERT.
- Skipping the verify fan-out because "the captures look obviously right" → the
  measured dead rate on a stale inbox is ~20%.
- Pausing a flagless drain to ask permission ("shall I convert?", "start
  dispatch?") → the drain invocation already answered; only OWNER items wait.
- Running dispatch after `--triage-only`, or skipping the red-team because the
  approval table is waived → the waiver covers the owner touch, never a review.
- Re-triaging lines dispatch captured during this run's drain → next sweep's
  input.
- Routing an item to OWNER without the read-only blast-radius check attached →
  run the check first; topic-matching is not the bar.
- Re-presenting a carried-over OWNER line without re-adjudicating it against the
  bar → the bucket is a decision queue, never a parking lot.
- A report with any section beyond the counts line, dispatch's line, and the
  OWNER lines → the envelope is hard.

## Related skills

- **define-goal** — owns conversion (contracts, red-team, line deletion; the
  approval table except under a drain's waiver); this skill is its verified
  front door.
- **dispatch** — appends captures at settle time; works the converted goals —
  invoked directly as a flagless drain's final step.
- **goals-status** — the queue view after conversion.
