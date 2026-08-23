---
name: factory-doctor
description: Use when setting up or troubleshooting the flywheel factory in a repo — before the first /dispatch, after a missing-queue or unauthenticated-gh error, or any time /dispatch or /define-goal behaves like the environment isn't ready. Preflights software, gh auth, CI, the local working tree, and the docs/goals queue, auto-fixing everything local. Diagnoses and fixes setup; never implements goals or merges PRs.
---

# Factory Doctor

Make a repo + machine factory-ready in one idempotent pass. You READ everything via the
shipped probe, AGGRESSIVELY auto-fix everything local and reversible, and REPORT (with the
exact command) everything you physically can't do safely. Running this twice yields the same
green report.

## Run order

1. **Resolve paths.** `$DC` = `doctor_checks.py`, in ONE bash block — the same shape
   goals-status and dispatch use (`find`, never a brace-glob: zsh aborts the whole
   command when any brace alternative fails to match):

   ```bash
   DC="$CLAUDE_PLUGIN_ROOT/skills/factory-doctor/scripts/doctor_checks.py"
   [ -f "$DC" ] || DC=$(find ~/.claude/plugins ~/.factory/plugins/cache -path '*/flywheel/*/skills/factory-doctor/scripts/doctor_checks.py' 2>/dev/null | sort -V | tail -1)
   [ -n "$DC" ] || echo "doctor_checks.py not found — reinstall/update the flywheel plugin"
   ```
2. **Read the queue config** (`docs/goals/index.yaml` `config:` if present) for `base`.
   Pass `--base <base>` ONLY when `config.base` is explicitly set. If it is absent, omit
   `--base` — dispatch defaults base to the checked-out branch, so there is no separate
   working branch to mismatch against (the probe reports INFO, not a spurious warning).
3. **Run the read-only probe:** `python3 "$DC" [--base <config.base>] [--skip-verify-run]`
   — it emits JSON `{checks:[{check,level,detail,fix}], result}` and
   exits 0/1/2. Never edit it.
   By DEFAULT the probe EXECUTES the repo's `config.verify` commands (POSIX shell, cwd = repo
   root, sequential, no short-circuit, per-command timeout from `PG_DOCTOR_VERIFY_TIMEOUT`,
   default 1800s) and reports the `verify-run` check — a *declared* gate is not a *working*
   gate, and a renamed script or wrong workspace filter makes every later dispatch PASS
   unearned. Pass `--skip-verify-run` when execution would be circular or unwanted: the probe
   is being invoked from inside that very gate (a `config.verify` command that itself runs the
   doctor), or the user asked for a fast read-only pass. Skipping is honest, not silent — the
   check then reports INFO `not run … it is unproven`.

## Apply local fixes (aggressive — these and ONLY these)

For each check whose `fix` begins with `FIX:`:

- **`pyyaml` (or any required python dep — BLOCKER with a `FIX:` install):** install it for the
  SAME `python3` dispatch invokes (the one on PATH), then re-import / re-run the probe to confirm
  → FIXED. Try in order, stopping at the first that succeeds: (1) `python3 -m pip install --user
  <pkg>`; (2) if the env is externally-managed (PEP 668 refuses `--user` — common with Homebrew
  python on macOS), `python3 -m pip install --user --break-system-packages <pkg>` — still
  user-scope, and this is the plugin's own pinned, tiny, pure-python dep, so forcing it at user
  scope is safe and IS in scope to auto-fix. Only if BOTH fail, report the manual command under
  needs-you (note any sibling `python3` that already has the dep, e.g. `/usr/bin/python3`, but
  remember dispatch uses the PATH one). A repo venv does NOT help unless dispatch runs under it,
  so don't rely on it. If the harness denies the install in an unattended session, surface it
  under needs-you and apply on the user's explicit "go".
- **`queue` (missing index.yaml):** scaffold `docs/goals/`, `docs/goals/done/`,
  `docs/goals/archive.yaml`, and an `index.yaml` with the default `config:` block:

  ```yaml
  config:
    base: <resolved-base>
    model: inherit
    skills: []
    verify:
      - npm ci
      - npm run build
      - npm test
    # budget:           # optional — uncomment to cap repeated dispatch fires
    #   max_goals_per_session: 1
  goals: {}
  ```

  Adjust `verify` to the repo's actual local build+test commands (inspect `package.json`,
  `Makefile`, `pyproject.toml`, etc.). Mark FIXED.

- **`config-drift` (removed v3 keys in `index.yaml` config — WARN with a `FIX:`):** a queue
  set up under the v3 model still carries keys the v4 one-goal/local-gate model removed
  (`merge`, `wip`, `execution`, `autonomy`); v4 dispatch silently ignores them, so the owner
  keeps thinking in the old PR/worktree/herdr model. **Auto-strip them:** edit
  `docs/goals/index.yaml` config to remove ONLY the keys the probe named, in one atomic edit —
  preserve every live key (`base`, `model`, `skills`, `verify`, `budget`), comments, and
  formatting; NEVER touch `goals:` entries or any goal file. Under `fixed:` echo each removed
  `key=value` (so any owner intent a dead key's value encoded is visible, not silently dropped).
  Mark FIXED. Drives the `queue: …drift` status token below.

Each fix is one atomic edit, named in the report. Like every factory-doctor local fix, leave
the edit in the working tree — do NOT commit or push it (committing is dispatch's job, not the
doctor's). The edits show up in the `working-tree` WARN as expected; the user reviews the
`fixed:` list and commits when ready, before the first `/dispatch`.

## Never (even though you're aggressive)

Push, open a PR, touch the remote, **edit or "repair" a repo's tests or its `config.verify`
list because `verify-run` came back red** (a failing verify command is REPORT-only — quote the
`detail` + `fix` under needs-you and let the human decide; silently rewriting the gate the
factory depends on, or the tests it runs, would manufacture the exact false green this check
exists to catch), edit a CI workflow, run `gh auth login`/`refresh`
(browser-blocking — report the exact command instead), run a SYSTEM/sudo/global install (`gh`,
`git`, `brew`/`apt`, OR `npm i -g agent-browser` + its Chromium download — report those; the
ONLY install you may run is the plugin's own python dep at `--user` scope, above), `git stash`,
delete branches/worktrees, or write to user-scope settings (`~/.claude/settings.json` or
`~/.factory/settings.json`). Anything not in the fix list above is REPORT-only.

## Report (always, last line is the status)

`fixed:` lists what you changed (one line each). `needs-you:` lists every BLOCKER/WARN the
probe reported that you did NOT auto-fix — copy its `detail` and `fix` fields verbatim; that
text IS the exact command or guidance for the human (the `gh auth refresh …` line, or any
install command for a missing system tool). The probe checks `browser-verify`: if the repo has
frontend/UI work (a UI framework in package.json, or any goal referencing `agent-browser`)
but `agent-browser` isn't installed, it WARNs with the install command — REPORT-only (a global
npm install + Chromium is a system-level change, never auto-run). On Windows the probe also
checks `symlink-privilege`: without Developer Mode or elevation, dispatch's bug-goal gate
cannot link dep dirs into its base worktree and every `type: bug` goal returns INCONCLUSIVE —
WARN carrying the enable-Developer-Mode fix (REPORT-only; an OS settings change is never
auto-run). The probe also emits four
REPORT-only loop-health checks (all read-only — never auto-fixed): `queue-liveness` (WARN naming
any `in_progress` goal with no work commits on the branch after its claim commit — a stale claim /
silent-death candidate dispatch will respawn or that needs unblocking), `lane-hygiene`
(v9 parallel lane model: WARN naming any orphan `lane/<id>` branch or worktree with no
matching `in_progress` claim, any stray directory under the runtime lanes dir, or a lane
branch whose worktree is missing — the fix text carries the exact `git worktree remove` +
`git branch -D` commands for orphans; INFO when no lanes exist or lanes match claims;
dispatch, never this probe, mutates lanes), `goal-contracts`
(WARN naming any active goal whose file lacks a checkable done-condition — tighten via
`/define-goal` before dispatch picks it up), and `limit-resilience` (WARN when a dispatch loop
demonstrably fires on this repo — heartbeat log lines exist — but no usage-limit rail is
present: no `StopFailure` hook (the probe checks settings in `.claude/` and `.factory/`,
project + user scope) and no pre-existing OS scheduler (still detected as a rail where
one exists). Its `fix` field carries loop-architect Step 5's current guidance:
window-timed attended drains — `/dispatch` (drains by default since v10.0.0) right after each limit reset —
rather than headless scheduling. INFO-only when no
loop has fired here or a rail is detected). The `verify` check WARNs if `config.verify` is
absent and there are active goals — copy its `fix` (add a `verify:` list to `index.yaml`). The
`verify-run` check reports whether those declared commands ACTUALLY run: BLOCKER naming the
failing or unresolvable command verbatim with its exit code, WARN on a timeout, INFO when all
exited 0, were skipped, or none are configured. It is REPORT-only — never auto-fix a red gate
(see Never, above); surface it under needs-you with its `detail` and `fix` verbatim. Then one
status line:

`[doctor] software: <ok|missing> · auth: <ok|n/a> · verify: <ran-green|⚠ ran-red|⚠ unresolved|⚠ timeout|configured (unrun)|⚠ missing|n/a> · working-tree: <clean|⚠ dirty> · working-branch: <ok|⚠ off-base> · ci: <present|none> · queue: <valid|scaffolded|drift> · health: <live|⚠ stale claims|⚠ underspecified goals|⚠ limit-exposed> · result: READY|WARN|BLOCKER`

The `verify:` token comes from both verify checks together: `ran-green` (all commands exited
0), `⚠ ran-red` (a command failed), `⚠ unresolved` (a command exited 127 — the shell could not
find it), `⚠ timeout` (a command hit `PG_DOCTOR_VERIFY_TIMEOUT`), `configured (unrun)`
(commands declared but execution skipped via `--skip-verify-run`), `⚠ missing` (no
`config.verify` with active goals), `n/a` (no `config.verify`, no active goals).

## Relationship to the other skills

- `define-goal` runs the queue subset of these checks before creating the first `index.yaml`.
- `dispatch` Phase 0 runs the read-only probe each fire and cites `/factory-doctor` on a
  failure it can't handle; its permission-stall fix is "run `/factory-doctor`".
- This skill never claims goals, spawns implementers, or merges — that's `dispatch`.
