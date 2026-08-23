"""Read-only readiness probes for the flywheel factory. Emits JSON; never
mutates. The factory-doctor skill interprets the output and applies fixes."""
import re


def version_ge(have, want):
    def parse(s):
        m = re.search(r"(\d+(?:\.\d+)+|\d+)", s or "")
        return [int(x) for x in m.group(1).split(".")] if m else [0]
    a, b = parse(have), parse(want)
    n = max(len(a), len(b)); a += [0] * (n - len(a)); b += [0] * (n - len(b))
    return a >= b


def validate_queue(index_obj):
    problems = []
    goals = (index_obj or {}).get("goals") or {}
    ids = set(goals)
    for gid, entry in goals.items():
        entry = entry or {}
        if "status" not in entry:
            problems.append(f"{gid}: index entry has no status")
        for dep in entry.get("depends_on", []) or []:
            if dep not in ids:
                problems.append(f"{gid}: depends_on points at missing entry {dep}")
    # simple cycle detection
    WHITE, GREY, BLACK = 0, 1, 2
    color = {g: WHITE for g in goals}

    def visit(g):
        color[g] = GREY
        for dep in (goals.get(g) or {}).get("depends_on", []) or []:
            if dep not in color:
                continue
            if color[dep] == GREY:
                problems.append(f"circular depends_on at {g}->{dep}"); return
            if color[dep] == WHITE:
                visit(dep)
        color[g] = BLACK

    for g in goals:
        if color[g] == WHITE:
            visit(g)
    return (len(problems) == 0, problems)


import argparse, glob, json, ntpath, os, posixpath, shutil, subprocess, sys, tempfile
try:
    import yaml
except ImportError:
    yaml = None


# ---- frontend / browser-verification detection (UI goals need a real browser check) ----
def _is_ui_dep(dep):
    return (dep in {"react", "react-dom", "vue", "next", "nuxt", "vite", "preact",
                    "solid-js", "lit", "@angular/core"}
            or dep.startswith(("react-", "@angular/", "@vue/", "@sveltejs/", "@lit/")))


def _pkg_has_ui(pkg):
    deps = {}
    deps.update((pkg or {}).get("dependencies") or {})
    deps.update((pkg or {}).get("devDependencies") or {})
    return any(_is_ui_dep(d) for d in deps)


def detect_frontend(repo_root):
    # root + immediate-child package.json (monorepo apps/frontend dirs)
    candidates = [os.path.join(repo_root, "package.json")]
    try:
        for name in os.listdir(repo_root):
            p = os.path.join(repo_root, name, "package.json")
            if os.path.isfile(p):
                candidates.append(p)
    except OSError:
        pass
    for p in candidates:
        try:
            if _pkg_has_ui(json.load(open(p))):
                return True
        except (FileNotFoundError, ValueError):
            continue
    return False


def goals_reference_browser(repo_root):
    goals_dir = os.path.join(repo_root, "docs", "goals")
    if not os.path.isdir(goals_dir):
        return False
    for f in glob.glob(os.path.join(goals_dir, "*.md")):
        try:
            if "agent-browser" in open(f).read():
                return True
        except OSError:
            continue
    return False


def _run(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", "not found"


def stale_claim_problems(goals, claim_info):
    # v4 (no goal/<id> branches, no PRs): an in_progress goal is stale ONLY if its claim
    # commit exists on the current branch but NO work commit (non-chore(goals)) follows it
    # — claimed but nothing worked, a silent-death candidate the next fire must respawn or
    # unblock. If the claim commit can't be located, treat as cannot-determine (INFO, not
    # a WARN). claim_info: {gid: {"claim_found": bool, "work_after": bool}}.
    out = []
    for gid, entry in (goals or {}).items():
        entry = entry or {}
        if entry.get("status") != "in_progress":
            continue
        info = (claim_info or {}).get(gid) or {}
        if not info.get("claim_found"):
            continue  # cannot determine — not flagged as stale
        if not info.get("work_after"):
            out.append(f"{gid}: in_progress, claim commit found but no work commits after it on the current branch — stale claim / silent-death candidate")
    return out


def _has_checkable_done(md_text):
    # True if a goal file carries a machine-checkable done-condition: a non-empty Acceptance
    # criteria section (>=1 checkbox) or a Goal contract section / a /goal line.
    text = md_text or ""
    has_accept = False
    m = re.search(r"(?im)^##\s*Acceptance criteria\s*$", text)
    if m:
        tail = text[m.end():]
        nxt = re.search(r"(?m)^##\s", tail)
        section = tail[:nxt.start()] if nxt else tail
        has_accept = bool(re.search(r"(?m)^\s*-\s*\[[ xX]\]\s*\S", section))
    has_contract = bool(re.search(r"(?im)^##\s*Goal contract\s*$", text)) or "/goal " in text
    return has_accept or has_contract


def goal_contract_problems(goals):
    # goals: list of {id, status, checkable}. Flags active goals (not_started/in_progress)
    # whose file lacks a checkable done-condition — "a loop without a goal is a slop cannon".
    return [f"{g['id']}: goal file has no checkable done-condition (acceptance criteria or goal contract)"
            for g in (goals or [])
            if g.get("status") in ("not_started", "in_progress") and not g.get("checkable")]


# ---- new local-gate check helpers ----

# v3.x queue config keys removed in the v4 one-goal/local-gate model. A stale index.yaml
# updated to the v4 plugin still carries them; v4 dispatch silently ignores them, so the
# owner keeps thinking in the old PR/worktree/herdr model. factory-doctor strips them.
# Extend this ONE set when future keys are removed.
DEPRECATED_V3_KEYS = ("merge", "wip", "execution", "autonomy")


def config_drift_check(config):
    present = [k for k in DEPRECATED_V3_KEYS if k in (config or {})]
    if present:
        keys = ", ".join(present)
        return {"check": "config-drift", "level": "WARN",
                "detail": f"index.yaml config carries removed v3 keys: {keys} — v4 dispatch silently ignores them",
                "fix": f"FIX: strip {keys} from docs/goals/index.yaml config "
                       "(v4 is one-goal, local-gated, direct-to-branch: no merge/wip/execution/autonomy)"}
    return {"check": "config-drift", "level": "INFO", "detail": "no deprecated v3 config keys", "fix": ""}


def verify_check(verify_cmds, active_goals):
    if not verify_cmds:
        if active_goals:
            return {"check": "verify", "level": "WARN",
                    "detail": "no config.verify commands — the loop has no local gate",
                    "fix": "add verify: [<build cmd>, <test cmd>] to docs/goals/index.yaml config"}
        return {"check": "verify", "level": "INFO", "detail": "no config.verify (no active goals)", "fix": ""}
    return {"check": "verify", "level": "INFO",
            "detail": f"verify: {len(verify_cmds)} command(s) configured", "fix": ""}


def _resolve_shell(environ=None, which=None, isfile=None, windows=None):
    """Full path to the POSIX shell that runs config.verify commands, or None.

    Duplicated from pg_validate.py deliberately: the two scripts live in different
    skill dirs, are not a package, and are resolved independently at runtime — this
    one must never import from that one. A bare-name ["bash", ...] argv is resolved by
    CreateProcess on Windows, which searches System32 BEFORE PATH, so with the WSL
    feature enabled the distro-less launcher stub %SystemRoot%\\System32\\bash.exe
    shadows Git Bash and every command exits nonzero — false-reddening the gate the
    doctor is probing. Order: $PG_BASH > which('bash') > which('sh') (both rejected
    under %SystemRoot%) > standard Git-for-Windows locations. None -> platform shell.
    The keyword args exist for cross-platform tests; production callers pass none.
    """
    env = os.environ if environ is None else environ
    look = shutil.which if which is None else which
    isf = os.path.isfile if isfile is None else isfile
    win = (os.name == "nt") if windows is None else windows
    p_ = ntpath if win else posixpath

    override = env.get("PG_BASH")
    if override:
        return override

    sysroot = p_.normcase(p_.normpath(env.get("SystemRoot") or "C:\\Windows")) if win else None

    def under_sysroot(path):
        return win and p_.normcase(p_.normpath(path)).startswith(sysroot + p_.sep)

    for name in ("bash", "sh"):
        found = look(name)
        if found and not under_sysroot(found):
            return found

    if win:
        bases = [env.get(k) for k in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)")]
        if env.get("LocalAppData"):
            bases.append(p_.join(env["LocalAppData"], "Programs"))
        for base in bases:
            if not base:
                continue
            for rel in (("Git", "usr", "bin", "bash.exe"), ("Git", "bin", "bash.exe")):
                cand = p_.join(base, *rel)
                if isf(cand):
                    return cand
    return None


_SHELL_MEMO = []  # resolved once per process; [None] means "no POSIX shell found"


def _run_verify_cmds(cmds, cwd):
    # Thin executor, kept separate from the verdict so tests can monkeypatch it away.
    # config.verify entries are shell STRINGS ("npm run build && npm test"), so they
    # need a shell — _run()'s argv-list form cannot express them. Sequential and never
    # short-circuiting: a red first command must not hide the shape of the rest.
    if not _SHELL_MEMO:
        _SHELL_MEMO.append(_resolve_shell())
    shell = _SHELL_MEMO[0]
    # Bounded so a hung suite reports a timeout instead of locking the doctor forever.
    timeout = float(os.environ.get("PG_DOCTOR_VERIFY_TIMEOUT", "1800"))
    exits = []
    for c in cmds:
        try:
            if shell:
                r = subprocess.run([shell, "-lc", c], capture_output=True, text=True,
                                   cwd=cwd, timeout=timeout)
            else:
                r = subprocess.run(c, shell=True, capture_output=True, text=True,
                                   cwd=cwd, timeout=timeout)
            exits.append(r.returncode)
        except subprocess.TimeoutExpired:
            exits.append(124)
    return exits


def verify_run_check(verify_cmds, results, skipped=False):
    # Pure verdict over already-computed results — runs nothing itself.
    # results: [(command, exit_code), ...] or None when nothing was executed.
    # `verify` says a gate is DECLARED; this says the declared gate actually RUNS.
    # Always REPORT-only: no `FIX:` prefix, because factory-doctor must never edit a
    # repo's test suite or its config.verify list in response to a red gate.
    if not verify_cmds:
        return {"check": "verify-run", "level": "INFO",
                "detail": "no config.verify commands to execute", "fix": ""}
    if skipped:
        return {"check": "verify-run", "level": "INFO",
                "detail": f"verify execution skipped (--skip-verify-run): the declared gate "
                          f"({len(verify_cmds)} command(s)) was not run — it is unproven",
                "fix": ""}
    results = results or []
    failed = [(c, rc) for c, rc in results if rc not in (0, 124)]
    timed_out = [(c, rc) for c, rc in results if rc == 124]
    if failed:
        parts = [f"`{c}` {'is unresolvable' if rc == 127 else 'failed'}, exit {rc}"
                 for c, rc in failed]
        return {"check": "verify-run", "level": "BLOCKER",
                "detail": "the declared local gate does not run: " + "; ".join(parts)
                          + " — every dispatch PASS gated on it is unearned",
                "fix": f"reproduce from the repo root: {failed[0][0]} — then fix the command "
                       "or correct config.verify in docs/goals/index.yaml yourself "
                       "(REPORT-only: factory-doctor never edits a repo's gate or tests)"}
    if timed_out:
        parts = [f"`{c}` timed out, exit {rc}" for c, rc in timed_out]
        return {"check": "verify-run", "level": "WARN",
                "detail": "the declared local gate did not finish: " + "; ".join(parts)
                          + f" (PG_DOCTOR_VERIFY_TIMEOUT="
                            f"{os.environ.get('PG_DOCTOR_VERIFY_TIMEOUT', '1800')}s)",
                "fix": f"run it yourself from the repo root: {timed_out[0][0]} — raise "
                       "PG_DOCTOR_VERIFY_TIMEOUT if the gate is legitimately this slow"}
    return {"check": "verify-run", "level": "INFO",
            "detail": f"verify-run: {len(results)} command(s) ran, all exited 0 — "
                      "the declared local gate really runs", "fix": ""}


def limit_resilience_check(active_goals, heartbeat_lines, signal_configured, scheduler_evidence):
    # Subscription usage limits (the 5-hour/weekly windows) block ALL turns until reset;
    # an in-session /loop dies with the session and nothing inside the CLI restarts it
    # — no hook fires on the limit banner. Recognized rails: a StopFailure hook
    # (rate_limit matcher) arming an external signal, or a pre-existing OS scheduler
    # (still detected as a rail where one exists, though the recommended pattern is
    # window-timed attended drains — /dispatch (drains by default) after each reset).
    # WARN only when a loop demonstrably fires on this repo (heartbeat lines exist)
    # yet no rail is present.
    if not active_goals:
        return {"check": "limit-resilience", "level": "INFO",
                "detail": "no active goals; usage-limit exposure not applicable", "fix": ""}
    if heartbeat_lines == 0:
        return {"check": "limit-resilience", "level": "INFO",
                "detail": "no dispatch loop has fired here yet; if you set up a long-running "
                          "loop, make it usage-limit-proof (see loop-architect Step 5)", "fix": ""}
    if signal_configured or scheduler_evidence:
        via = "external scheduler" if scheduler_evidence else "StopFailure hook"
        return {"check": "limit-resilience", "level": "INFO",
                "detail": f"loop is usage-limit-aware via {via}", "fix": ""}
    return {"check": "limit-resilience", "level": "WARN",
            "detail": "a dispatch loop fires on this repo but nothing survives an account "
                      "usage-limit stop (5-hour/weekly window): in-session loops die at the "
                      "limit and no hook fires on the banner",
            "fix": "drain in window-timed attended batches: run /dispatch right after each "
                   "limit reset (a flagless run drains by default since v10.0.0; "
                   "--unlimited is the explicit alias, --count N caps it) (statusline "
                   "rate_limits.*.resets_at gives the clock) instead of an open /loop; "
                   "optionally add a StopFailure hook (rate_limit matcher) as a mid-turn "
                   "death signal — see loop-architect Step 5 limit-proofing"}


def _heartbeat_line_count(repo_root):
    # dispatch appends one line per fire to ~/.local/state/pg-dispatch/<SLUG>/heartbeat
    # (<SLUG> = repo dir name). 0 = no loop has ever fired here (or unreadable).
    path = os.path.join(os.path.expanduser("~"), ".local", "state", "pg-dispatch",
                        os.path.basename(repo_root or ""), "heartbeat")
    try:
        with open(path) as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return 0


def _has_stop_failure_hook(repo_root):
    # A configured StopFailure hook = the machine gets a signal when a turn dies on an
    # API error (incl. rate_limit) and can arm an external resume. Read-only; checks
    # project + user settings for both harnesses (.claude/ = Claude Code,
    # .factory/ = Factory Droid). Parse errors count as absent.
    home = os.path.expanduser("~")
    candidates = [os.path.join(repo_root, d, f)
                  for d in (".claude", ".factory")
                  for f in ("settings.json", "settings.local.json")]
    candidates += [os.path.join(home, ".claude", "settings.json"),
                   os.path.join(home, ".factory", "settings.json")]
    for p in candidates:
        try:
            hooks = (json.load(open(p)) or {}).get("hooks") or {}
            if hooks.get("StopFailure"):
                return True
        except (OSError, ValueError):
            continue
    return False


def _external_scheduler_evidence():
    # Best-effort, read-only sweep for an OS-level scheduler that fires fresh CLI
    # sessions (the limit-proof loop shape): user crontab, macOS LaunchAgents, and
    # systemd user timers. Match only unambiguous patterns — a bare "claude" or
    # "droid" would false-positive on desktop-app agents.
    patterns = ("claude -p", "claude --print", "droid exec", "/dispatch")

    def hit(text):
        return any(p in (text or "") for p in patterns)

    rc, out, _ = _run(["crontab", "-l"])
    if rc == 0 and hit(out):
        return True
    home = os.path.expanduser("~")
    unit_globs = [os.path.join(home, "Library", "LaunchAgents", "*.plist"),
                  os.path.join(home, ".config", "systemd", "user", "*.service"),
                  os.path.join(home, ".config", "systemd", "user", "*.timer")]
    for g in unit_globs:
        for p in glob.glob(g):
            try:
                if hit(open(p, errors="ignore").read()):
                    return True
            except OSError:
                continue
    return False


def lane_hygiene_check(lane_branches, worktree_lane_paths, in_progress_ids, lanes_dir_entries):
    """Parallel-mode lane hygiene (v9.0.0 lane model). Pure function.

    lane_branches: ids parsed from local `lane/<id>` branches.
    worktree_lane_paths: ids of registered worktrees living under the lanes dir.
    in_progress_ids: goal ids currently in_progress in the index.
    lanes_dir_entries: directory names present under the runtime lanes dir.
    All read-only observations; dispatch (not this probe) mutates lanes.
    """
    lane_branches = set(lane_branches or [])
    worktree_lane_paths = set(worktree_lane_paths or [])
    in_progress_ids = set(in_progress_ids or [])
    lanes_dir_entries = set(lanes_dir_entries or [])
    if not (lane_branches | worktree_lane_paths | lanes_dir_entries):
        return {"check": "lane-hygiene", "level": "INFO",
                "detail": "no parallel lanes present", "fix": ""}
    probs = []
    orphans = sorted((lane_branches | worktree_lane_paths) - in_progress_ids)
    if orphans:
        probs.append("orphan lane(s) with no in_progress claim: " + ", ".join(orphans))
    missing_wt = sorted((lane_branches & in_progress_ids) - worktree_lane_paths)
    if missing_wt:
        probs.append("lane branch without a registered worktree (dispatch recreates it): "
                     + ", ".join(missing_wt))
    stray_dirs = sorted(lanes_dir_entries - worktree_lane_paths - lane_branches)
    if stray_dirs:
        probs.append("stray lane director(ies) not registered as worktrees: "
                     + ", ".join(stray_dirs))
    if not probs:
        return {"check": "lane-hygiene", "level": "INFO",
                "detail": "lanes consistent with in_progress claims", "fix": ""}
    return {"check": "lane-hygiene", "level": "WARN", "detail": "; ".join(probs),
            "fix": "orphans: git worktree remove <lanes-dir>/<id> && git branch -D lane/<id>; "
                   "stray dirs: remove the directory; missing worktrees need nothing"}


def working_tree_check(porcelain):
    if porcelain.strip():
        return {"check": "working-tree", "level": "WARN",
                "detail": "uncommitted changes present",
                "fix": "commit or stash before dispatch — goals commit onto the current branch"}
    return {"check": "working-tree", "level": "INFO", "detail": "working tree clean", "fix": ""}


def working_branch_check(current, base):
    # v4.1.x: dispatch commits DIRECTLY on config.base and hard-STOPS when the checked-out
    # branch != config.base. So being ON base is the healthy steady state; a mismatch is the
    # real problem to flag. (When no explicit config.base is set, dispatch defaults it to the
    # checked-out branch, so there is nothing to mismatch against — INFO.)
    if not base:
        return {"check": "working-branch", "level": "INFO",
                "detail": f"on '{current or 'detached'}' (no explicit config.base)", "fix": ""}
    if current and current == base:
        return {"check": "working-branch", "level": "INFO",
                "detail": f"on base '{base}' — dispatch works here", "fix": ""}
    return {"check": "working-branch", "level": "WARN",
            "detail": f"on '{current or 'detached'}' but config.base is '{base}' — dispatch will STOP",
            "fix": f"git checkout {base} before running /dispatch"}


def _probe_symlink():
    # Can this process create a directory symlink? On Windows that needs
    # SeCreateSymbolicLinkPrivilege — Developer Mode or elevation; off by default.
    try:
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "t"); os.mkdir(target)
            os.symlink(target, os.path.join(d, "l"), target_is_directory=True)
        return True
    except OSError:
        return False


def symlink_capability_check(can_symlink, windows):
    # Windows-only: dispatch's gate proves type: bug goals by running acceptance in a
    # base worktree whose dep dirs are SYMLINKED from the live checkout. Without the
    # privilege every bug goal gates INCONCLUSIVE (safe, but the whole class blocks).
    if not windows:
        return None
    if can_symlink:
        return {"check": "symlink-privilege", "level": "INFO",
                "detail": "symlinks available — bug-goal base worktrees can link deps",
                "fix": ""}
    return {"check": "symlink-privilege", "level": "WARN",
            "detail": "no symlink privilege (WinError 1314) — every type: bug goal will gate "
                      "INCONCLUSIVE because the base worktree cannot link deps",
            "fix": "enable Windows Developer Mode (Settings → Privacy & security → "
                   "For developers) or run elevated"}


def run_checks(base, skip_verify_run=False):
    C = []

    def add(check, level, detail, fix=""):
        C.append({"check": check, "level": level, "detail": detail, "fix": fix})

    rc, out, _ = _run(["git", "rev-parse", "--show-toplevel"])
    repo_root = out.strip() if rc == 0 else os.getcwd()

    # working-tree check (before everything else — dirty tree is important to flag early)
    _, porcelain, _ = _run(["git", "status", "--porcelain"])
    wt = working_tree_check(porcelain or "")
    C.append(wt)

    # working-branch check
    _, head_ref, _ = _run(["git", "symbolic-ref", "--short", "HEAD"])
    wb = working_branch_check((head_ref or "").strip(), base)
    C.append(wb)

    # software
    rc, out, _ = _run(["gh", "--version"])
    add("gh", "INFO", out.splitlines()[0] if rc == 0 and out.strip() else "gh not found or old")

    rc, out, _ = _run(["git", "--version"])
    add("git", "INFO" if rc == 0 and version_ge(out, "2.20") else "BLOCKER", out.strip() or "git missing")

    add("python3", "INFO", sys.version.split()[0])
    sl = symlink_capability_check(_probe_symlink() if os.name == "nt" else True,
                                  os.name == "nt")
    if sl:
        C.append(sl)
    if yaml is None:
        add("pyyaml", "BLOCKER", "pyyaml not importable (dispatch + this probe parse the queue with it)",
            "FIX: python3 -m pip install --user pyyaml  (if PEP-668 externally-managed, add --break-system-packages — still user-scope)")

    # auth (INFO-only)
    rc, out, err = _run(["gh", "auth", "status"])
    add("gh-auth", "INFO",
        "authenticated" if rc == 0 else "not authenticated — gh features unavailable",
        "" if rc == 0 else "gh auth login -h github.com")

    # CI (INFO-only)
    wf = os.path.join(repo_root, ".github", "workflows")
    has_wf = os.path.isdir(wf) and any(f.endswith((".yml", ".yaml")) for f in os.listdir(wf))
    add("ci", "INFO", "CI workflow present" if has_wf else "no CI workflow found")

    # browser verification (only when frontend/UI work is present)
    if detect_frontend(repo_root) or goals_reference_browser(repo_root):
        rc, out, _ = _run(["agent-browser", "--version"])
        if rc == 0:
            add("browser-verify", "INFO",
                "frontend/UI work present; agent-browser available "
                f"({out.splitlines()[0] if out.strip() else 'ok'})")
        else:
            add("browser-verify", "WARN",
                "frontend/UI work detected but agent-browser is not installed — "
                "UI goals can't run their scripted browser check",
                "npm i -g agent-browser && agent-browser install  "
                "(then add 'agent-browser' to config.skills in docs/goals/index.yaml)")
    else:
        add("browser-verify", "INFO", "no frontend/UI work detected; browser verification not required")

    # queue
    idx = os.path.join(repo_root, "docs", "goals", "index.yaml")
    goals_dir = os.path.join(repo_root, "docs", "goals")
    active_goals = 0
    verify_cmds = []
    if not os.path.exists(idx):
        add("queue", "WARN", "no docs/goals/index.yaml", "FIX: scaffold a default index.yaml")
    elif yaml is not None:
        try:
            index_obj = yaml.safe_load(open(idx)) or {}
            ok, probs = validate_queue(index_obj)
            add("queue", "INFO" if ok else "WARN",
                "queue valid" if ok else "; ".join(probs), "" if ok else "report drift")
            goals = index_obj.get("goals") or {}
            config = index_obj.get("config") or {}
            C.append(config_drift_check(config))
            verify_cmds = config.get("verify") or []
            active_goals = sum(1 for e in goals.values()
                               if (e or {}).get("status") in ("not_started", "in_progress"))
            # queue liveness (v4: no goal/<id> branches, no PRs): an in_progress goal is
            # stale only if its claim commit exists but no work commit follows it on the
            # current branch. Find the claim commit, then count non-chore(goals) commits after it.
            claim_info = {}
            for gid, e in goals.items():
                if (e or {}).get("status") != "in_progress":
                    continue
                rc_c, claim_sha, _ = _run(["git", "log",
                                           f"--grep=chore(goals): claim {gid}",
                                           "--format=%H", "-1"])
                claim_sha = (claim_sha or "").strip()
                if rc_c != 0 or not claim_sha:
                    claim_info[gid] = {"claim_found": False, "work_after": False}
                    continue
                # any non-chore(goals) commit subject after the claim == real work
                _, subjects, _ = _run(["git", "log", "--format=%s",
                                       f"{claim_sha}..HEAD"])
                work_after = any(s.strip() and not s.strip().startswith("chore(goals):")
                                 for s in (subjects or "").splitlines())
                claim_info[gid] = {"claim_found": True, "work_after": work_after}
            stale = stale_claim_problems(goals, claim_info)
            add("queue-liveness", "WARN" if stale else "INFO",
                "; ".join(stale) if stale else "no stale in_progress claims",
                "dispatch will respawn or it needs unblocking" if stale else "")
            # parallel-lane hygiene (v9 lane model): observe lane/<id> branches,
            # registered worktrees under the runtime lanes dir, and the dir itself
            in_prog = [g for g, e in goals.items()
                       if (e or {}).get("status") == "in_progress"]
            _, br_out, _ = _run(["git", "branch", "--list", "lane/*", "--format=%(refname:short)"])
            lane_brs = [b.strip()[len("lane/"):] for b in (br_out or "").splitlines()
                        if b.strip().startswith("lane/")]
            slug = os.path.basename(repo_root)
            lanes_dir = os.path.expanduser(os.path.join("~", ".local", "state",
                                                        "pg-dispatch", slug, "lanes"))
            _, wt_out, _ = _run(["git", "worktree", "list", "--porcelain"])
            wt_lanes = []
            for line in (wt_out or "").splitlines():
                if line.startswith("worktree ") and lanes_dir in line:
                    wt_lanes.append(os.path.basename(line.split(" ", 1)[1].strip()))
            dir_entries = (os.listdir(lanes_dir)
                           if os.path.isdir(lanes_dir) else [])
            C.append(lane_hygiene_check(lane_brs, wt_lanes, in_prog, dir_entries))
            # goal contracts: active goals must carry a checkable done-condition
            gc = []
            for gid, e in goals.items():
                e = e or {}
                if e.get("status") not in ("not_started", "in_progress"):
                    continue
                try:
                    text = open(os.path.join(goals_dir, f"{gid}.md")).read()
                except OSError:
                    continue  # a missing goal file is a different concern
                gc.append({"id": gid, "status": e.get("status"), "checkable": _has_checkable_done(text)})
            cprobs = goal_contract_problems(gc)
            add("goal-contracts", "WARN" if cprobs else "INFO",
                "; ".join(cprobs) if cprobs else "active goals carry a checkable done-condition",
                "tighten via /define-goal before dispatch picks it up" if cprobs else "")
        except yaml.YAMLError as e:
            add("queue", "BLOCKER", f"index.yaml parse error: {e}")

    # verify check (local gate) — needs active_goals + verify_cmds from queue parse above
    vc = verify_check(verify_cmds, active_goals)
    C.append(vc)

    # verify-run: a DECLARED gate is not a WORKING gate. Execute the commands (unless
    # suppressed) and report whether they actually run. Skipped or empty -> no execution.
    if verify_cmds and not skip_verify_run:
        exits = _run_verify_cmds(verify_cmds, repo_root)
        C.append(verify_run_check(verify_cmds, list(zip(verify_cmds, exits))))
    else:
        C.append(verify_run_check(verify_cmds, None, skipped=skip_verify_run))

    # usage-limit resilience — needs active_goals from the queue parse above
    C.append(limit_resilience_check(active_goals,
                                    _heartbeat_line_count(repo_root),
                                    _has_stop_failure_hook(repo_root),
                                    _external_scheduler_evidence()))

    levels = {c["level"] for c in C}
    result = "BLOCKER" if "BLOCKER" in levels else "WARN" if "WARN" in levels else "READY"
    return C, result


def main(argv=None):
    ap = argparse.ArgumentParser(prog="doctor_checks.py")
    ap.add_argument("--base", default=None,
                    help="config.base if explicitly set; omit when the queue has no config.base "
                         "(dispatch then defaults base to the checked-out branch)")
    ap.add_argument("--self-test", action="store_true", help="run the test suite and exit")
    ap.add_argument("--skip-verify-run", action="store_true",
                    help="do not execute config.verify; report the gate as unrun (use when "
                         "the caller is already running inside that gate)")
    a = ap.parse_args(argv)
    if a.self_test:
        test_file = os.path.join(os.path.dirname(__file__), "test_doctor_checks.py")
        rc = subprocess.run([sys.executable, "-m", "pytest", test_file, "-v"]).returncode
        return rc
    checks, result = run_checks(a.base, skip_verify_run=a.skip_verify_run)
    print(json.dumps({"checks": checks, "result": result}, indent=2))
    return {"READY": 0, "WARN": 1, "BLOCKER": 2}[result]


if __name__ == "__main__":
    sys.exit(main())
