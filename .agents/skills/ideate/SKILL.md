---
name: ideate
description: Use when the user has an idea or early want that isn't ready to define — "I have an idea", "what if we", "let's think through X", "/ideate" — or when goal definition stalls because the want needs design exploration first. Explores intent and design through dialogue and writes the plan (docs/goals/plans/) that define-goal contracts from; never implements and never writes goal files or queue entries (that's define-goal).
argument-hint: "[the idea to explore]"
---

# Ideate — explore an idea into an approved plan

## Overview

Turn a fuzzy want into a PLAN the user has approved, then hand it to `define-goal`
to become goal contracts. This is the pipeline's front door:

```
/ideate  →  /define-goal  →  /dispatch  →  /goals-status
(plan)      (contract)       (execute+gate)  (observe)
```

The plan (v11.0.0) is the factory's design tier: one document that resolves design
forks BEFORE contracts exist. Forensics across this factory's real repos
(2026-08-12) found the dominant cycle-time tail was never implementation — it was
contract defects surfacing at dispatch time: goals blocked on two-readable criteria
took 10–85 hours of block→amend→requeue thrash, with the owner dragged into every
round. Both of the estate's currently-blocked goals are design forks ("derive-it or
author-it") that a plan's Open-questions section settles in one attended minute.
The plan moves that resolution to the cheapest possible place.

The user may not be an engineer — plain language with them; the plan's Design
section carries the precision.

**When a plan, when not.** A plan is for work that will become a CHAIN (2+ goals)
or a design-heavy single goal. An already-shaped want ("add rate limiting to
/api/orders, 429 over 100 req/min") skips this skill entirely — send it straight
to `define-goal`; ideating on it is ceremony. A simple single-goal outcome
explored here stays fileless: the design flows into that goal's Context and no
plan file is written. When a define-goal question round reveals the want is really
a design problem (answers keep re-opening what to build), hand off here.

**HARD GATE.** The ONLY terminal states of this skill are (a) invoking
`define-goal` with the approved plan (or fileless design), or (b) the user parking
or dropping the idea. Never write goal files, `index.yaml` entries, or code; never
scaffold; never implement "just the obvious part"; never draft goal contracts here
to skip define-goal's contract review. This holds regardless of how simple the
idea seems.

## The process

Work through these in order; scale each step to the idea's size.

### 1. Context first

Orient in the current system before asking anything — files, docs, recent commits,
where similar features already live. For a bigger unknown, spawn 1–2 read-only
subagents on the medium tier — Claude Code: the plugin's recon agents when the
runtime lists them (`flywheel:recon-locator` for where things live,
`flywheel:recon-analyzer` for how an area works, `flywheel:recon-patterns` for
existing implementations to model the Design section on), each on the
medium tier (`model: sonnet`) at spawn; else `general-purpose` on the same
medium tier (`model: sonnet`) —
never the built-in Explore type, whose model cannot be pinned. Droid:
`explorer` with `complexity: medium` — reporting `path:line` summaries, never
file dumps. The
judgment stays with you: weighing what they found, the approaches, and the design
happen in your session-model context. define-goal's recon still runs later,
narrowed by what you found.

### 2. Scope check — vertical slices, before any detail question

If the idea spans multiple independently shippable pieces, surface the
decomposition FIRST — and cut it VERTICALLY. Each piece must be independently
verifiable end-to-end on its own. A decomposition ordered by layer — "all schema,
then all services, then all API, then all UI" — is horizontal: it produces nothing
testable until the last piece and every piece's verification depends on a later
one. Cut through the layers instead: the thinnest end-to-end path first, then
widen. The test: **if a piece cannot be verified without a LATER piece existing,
it is not a slice — re-cut.** The decomposition maps 1:1 onto future goals and
their `depends_on` chain; say so in plain language ("this is really three
deliverables; the second needs the first").

### 3. Explore — a progressive dialogue, not an interrogation

Derive everything the repo can answer yourself — never ask the owner a question
the repo answers. For what the repo CANNOT answer, this is the ONE skill in the
pipeline where asking is the tool, not a failure (owner decision 2026-08-13: the
factory-wide question diet — "don't ask me questions, you decide" — stands in
every other skill; here the owner wants to shape the idea in dialogue). Three
rules govern the dialogue:

- **Owner-language questions only.** Ask about intent, audience, scope, taste —
  what it should do, who it's for, what matters, what to cut — in plain
  language. Every question goes through AskUserQuestion as 2–4 concrete options
  with your recommended option FIRST, labeled "(Recommended)"; `multiSelect`
  when the choices aren't mutually exclusive. Free text is the built-in "Other"
  escape hatch, never the question's default shape.
- **Progressive, not a batch interview.** One short round (1–2 questions) at a
  time; let each answer shape the next round. There is no fixed round cap — the
  cap is usefulness: stop when a round's answers stop changing the design, and
  leave the rest to the approval touch in step 5.
- **Re-orient when an answer opens new ground.** When an answer names or
  implies territory your current context doesn't cover — a flow, system,
  constraint, or repo area orientation never read — spawn recon again (step 1's
  agents, tiers, and read-only rules) BEFORE the next round or any design
  writing. Never ask the owner to explain what the repo can tell you; never
  keep designing on ground you haven't seen.

TECHNICAL forks stay out of the dialogue. A fork about implementation —
derive-it or author-it, storage choice, library pick — becomes an **Open
question** in the plan (options, one recommendation with its why), and you keep
designing on the recommended branch; ask one mid-dialogue only if the design
cannot be written at all without the answer, and even then translate it to
owner language. The owner decides those at the plan, recommendation in front
of them.

YAGNI ruthlessly: propose cutting features from every design. A cut piece can
always be ideated later. Genuinely different DIRECTIONS (2–3, recommendation
first) — forks that change what the owner gets, not how it's built — belong in
the dialogue in owner language; the losing direction and why it lost gets one
line in the plan's Design or Open-questions section.

### 4. Write the plan

For a chain (2+ goals) or design-heavy work: write the plan file per
`references/plan-template.md` (Read it — the template is canonical) to
`docs/goals/plans/YYYY-MM-DD-<topic>.md`. The template's two writing rules govern
everything you write in it:

- **Headers state the takeaway** — "Sessions persist to Postgres before the
  daemon acks", never "Session storage".
- **Code-shaped where it touches existing code, at signature altitude** — exact
  type/method signatures with bodies elided, a created/modified file-tree diff
  with one line of responsibility each, a call-flow sketch only where control
  flow is non-obvious. Never function bodies: if implementations appear, the plan
  has dropped a level.

For a simple single-goal outcome: no file — present the same content inline,
scaled down.

### 5. Present — ONE approval touch

Present the plan once: what we're doing, the design's takeaway headers, the
phases, and the Open questions with your recommendations. When showing beats
telling, use the smallest adequate view — pseudocode, a call tree, a file tree,
a small mermaid diagram — never a bigger artifact than the point needs
(riptide's show-me doctrine, folded in here).

**The plan page (v11.3.0 — only when the session's tools include the Artifact
tool).** For a plan-FILE design (chains — never fileless single-goal outcomes),
also publish the plan as a designed artifact page and lead the presentation
with its link: the owner-language summary, the Design section rendered with
real diagrams, each Open question as its options + your recommendation, and
the phases. Follow the built-in artifact design guidance that loads with the
tool; stamp the page "design for approval · <date> — the repo plan file is
canonical and carries live progress". Approval still happens IN THIS
CONVERSATION exactly as below — the page is a reading surface, never a second
approval channel. Record the published URL in the plan frontmatter `artifact:`
field so a later iteration updates the SAME page. Boundaries that keep this
honest: ONE publish per approval touch; the page is the design as approved,
never a live dashboard — dispatch's phase mirror and define-goal's amends
never republish it (live progress lives in the plan file, `/goals-status`,
and dispatch's report lines). The Artifact tool is a Claude Code feature that
requires a claude.ai login, can be disabled, and does not exist on Droid or
in headless runs — when it is absent, present in chat exactly as below and
skip nothing else: the chat presentation is the norm and the fallback, never
a degraded mode.

The user then either
answers any subset, says "go with your recommendations" (which resolves ALL open
questions — record each as resolved with that provenance), asks for changes, or
parks the idea. Iterate only on what they push back on; do not re-present
sections they didn't question. A plan may proceed to define-goal with questions
still OPEN — an unresolved design question is information, not a blocker, and a
goal that later trips over one has somewhere to point.

### 6. Self-review, inline

Before handoff, re-read the plan with fresh eyes:

- **Placeholders:** any "TBD", "handle edge cases", "appropriate X"? Fix them.
- **Verify commands are real (v11.3.1):** every file path named in a phase's
  Verify line exists — check each with `test -f` (or the equivalent) before
  presenting. A copy-pasteable command that points at a wrong path ships a
  defect into the plan (first field batch shipped `test/unit/…` for a file
  living in `test/integration/`).
- **Consistency:** do sections contradict each other?
- **Ambiguity:** could a requirement be read two materially different ways?
  Two-readable requirements come back as `CONTRACT_AMBIGUOUS` stops at dispatch
  time — kill them here, the cheapest place.
- **Slices:** does any phase fail the slice test (unverifiable without a later
  phase)? Re-cut it now — define-goal's red-team blocks horizontal cuts.
- **Headers:** does every heading state its takeaway?

Fix inline and move on — no re-review loop.

### 7. Handoff to define-goal

On approval, stamp the plan's frontmatter `status: approved` (a plan may still
carry OPEN questions — approval is about the design, not every fork), then
invoke `define-goal` with the plan (or the fileless design). A plan
is the interview already done: define-goal's plan-backed fast path runs ZERO
question rounds, narrows recon to verify-and-complete, uses the phases as the
batch item list, and links the plan from each goal's Context. define-goal still
runs its own contract review and confirmation — the plan is input, never a
bypass.

## Iterating an existing plan

Re-invoking this skill on an idea that already has a plan file UPDATES that plan
in place (same path, never a second file): fold in what changed, move
newly-answered questions to RESOLVED with their why, add new open questions, and
re-present only the changed sections for the same single approval touch. Never
rewrite resolved questions — they are the design's decision history. If the
plan's frontmatter carries an `artifact:` URL and the session has the Artifact
tool, republish the updated plan to that SAME URL as part of re-presenting
(never a second page); no tool in this session → chat presentation as usual,
and the URL stays for the next session that has it.

## Red flags — stop and get back on the path

- Writing a goal file, index entry, or code "while it's fresh" → HARD GATE
  violation.
- A batch interview — every question fired up front in one round → progressive:
  one short round, then let the answer shape the next.
- A technical fork asked mid-dialogue (jargon, implementation choices) → Open
  questions with a recommendation; the dialogue stays in the owner's language.
- A question without options and a recommended default → shape it before
  asking.
- Designing past an answer that named territory your context doesn't cover →
  spawn step 1's recon again first.
- Asking a question the repo can answer → read the repo.
- A layer-ordered decomposition presented as phases → horizontal cut; re-cut
  vertically before presenting.
- A heading that names a topic instead of stating its takeaway.
- Function bodies in the Design section → wrong altitude; delete the bodies,
  keep the signatures.
- A design section that says "TBD" or "we'll figure that out during
  implementation".
- Resolving an open question yourself without the user's answer or their
  "go with your recommendations".

## Related skills

- Shaped want, or plan approved → **define-goal** (single or batch mode; the
  plan-backed fast path).
- Recurring/unattended execution of the result → **loop-architect** (reached
  through define-goal, which owns the goal contract).
- Working the resulting queue → **dispatch** (it flips the plan's phase
  checkboxes as goals complete — the plan doubles as the progress view).
