---
name: goals-status
description: Use when the user runs "/goals-status" or asks what's in the docs/goals queue — what's left, what's blocked, what's in progress, or "show me the open goals". Prints a read-only view of the OPEN goals (in_progress, blocked, not_started), each with its title and brief; completed goals are hidden. Shows the queue only — never claims a goal, changes queue state, or implements anything (that's /dispatch).
---

# Goals Status

Show the open work in a repo's `docs/goals` queue: every goal that is
**in_progress**, **blocked**, or **not_started**, with its title and a one-line
brief. Completed goals are hidden (just counted), and so are `retired` goals
(v12.0.0 — dispatch's terminal disposition for a disproven-premise goal; counted
separately in the header, satisfied as a dependency). Read-only — it never writes to
`docs/goals/` (dispatch owns queue state).

## Run

One command, run from the target repo (the helper finds `docs/goals/` from the
git root). Run it as a single block — don't split the resolution into separate
calls:

```bash
GS="$CLAUDE_PLUGIN_ROOT/skills/goals-status/scripts/goals_status.py"
[ -f "$GS" ] || GS=$(find ~/.claude/plugins ~/.factory/plugins/cache -path '*/flywheel/*/skills/goals-status/scripts/goals_status.py' 2>/dev/null | sort -V | tail -1)
[ -n "$GS" ] && python3 "$GS" || echo "goals_status.py not found — reinstall/update the flywheel plugin"
```

To read a queue in another repo, append `--dir <path/to/docs/goals>` to the
`python3` call — with `--dir` you do NOT need to `cd` anywhere first.

**Print the output verbatim.** The helper's formatting is the deliverable — don't
re-summarize, reorder, or explain it.

Exit `0` means success (including an empty or all-completed queue). Exit `2`
means it could not read the queue at all — no `docs/goals/index.yaml`, a
malformed `index.yaml`, or PyYAML missing. Quote its stderr message back to the
user; each one already names the fix (`/factory-doctor`). Never present a
partial or empty view as if it were the real queue state.

One goal showing as `(untitled)` is not a failure of the view — that goal's own
frontmatter is unparseable, and only that row degrades.

## Boundaries

Read-only and reporting only. This skill never claims, completes, blocks, or
edits a goal, never touches `index.yaml`, and never starts implementation work —
that is `/dispatch`. To add goals use `/define-goal`; to fix a missing or broken
queue use `/factory-doctor`.
