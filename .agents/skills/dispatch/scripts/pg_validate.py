"""Deterministic LOCAL validation gate for flywheel — no PRs, no network, no LLM.
dispatch runs this on the goal's <base>..<head> local diff before keeping its commit.
Emits a SHA-bound {PASS|FAIL_FIXABLE|FAIL_CONTRACT|INCONCLUSIVE} verdict.
Never edits, pushes, or merges — read-only + runs the goal's own commands."""

VERDICTS = ("PASS", "FAIL_FIXABLE", "FAIL_CONTRACT", "INCONCLUSIVE")


def aggregate(results):
    """Combine per-check results into one verdict. Precedence:
    contract-fail > fixable-fail > inconclusive > pass."""
    kinds = [r["kind"] for r in results if not r["pass"]]
    if any(k == "contract" for k in kinds):
        return "FAIL_CONTRACT"
    if any(k == "fixable" for k in kinds):
        return "FAIL_FIXABLE"
    if any(k == "inconclusive" for k in kinds):
        return "INCONCLUSIVE"
    return "PASS"


import fnmatch

# fnmatch '*' spans '/', so '.claude/*' matches nested paths too.
FORBIDDEN_PATHS = (".claude/*", ".factory/*", ".github/workflows/*", "*/deploy*.sh", "deploy*.sh")
LOCKFILES = ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "go.sum",
             "Gemfile.lock", "poetry.lock", "Cargo.lock", "composer.lock")

# Gitignored dependency dirs absent from a fresh checkout. The bug repro-direction
# best-effort symlinks these from the live checkout into the base worktree so a
# test-runner acceptance command (npm test / pytest) has a working environment on base.
DEP_DIRS = ("node_modules", ".venv", "venv", "vendor")


def _any_match(path, globs):
    return any(fnmatch.fnmatch(path, g) for g in globs)


# Cap only the RENDERED evidence string; `violations` always carries every hit.
_EVIDENCE_CAP = 20


def _render(violations):
    """One evidence line naming EVERY violation (elided past the cap).

    Reporting only the first hit makes a repair agent fix one, re-gate, discover the
    next, and repeat — a serial round per violation. Callers get the complete list in
    one pass so a single repair can close the whole class.
    """
    shown = "; ".join(violations[:_EVIDENCE_CAP])
    if len(violations) > _EVIDENCE_CAP:
        shown += f"; … and {len(violations) - _EVIDENCE_CAP} more"
    return shown


def blast_radius(changed_paths, touches):
    violations = []
    for p in changed_paths:
        name = p.rsplit("/", 1)[-1]
        if _any_match(p, FORBIDDEN_PATHS) and not _any_match(p, touches):
            violations.append(f"forbidden path changed: {p}")
            continue
        if name in LOCKFILES and not _any_match(p, touches):
            violations.append(f"lockfile/dep churn not in declared surfaces: {p}")
            continue
        # Test files are EXPECTED to land outside the product-surface `touches` globs:
        # TDD mandates the implementer add a proving test, and split-tree layouts
        # (tests/, __tests__/, spec/) sit outside routes/UI/schema globs. Exempt them from
        # the out-of-scope check only (they are still subject to the forbidden/lockfile
        # branches above), or every correct TDD goal FAIL_FIXABLEs on its own regression test.
        if is_test_path(p):
            continue
        # Plan docs are EXPECTED to land outside `touches` for the same structural
        # reason: the implementer brief MANDATES `writing-plans` for any change
        # spanning >2 files, so the plan is written DURING implementation and cannot
        # have existed when the contract declared its surfaces. define-goal can only
        # stamp the plan path for a goal already plan-backed at DRAFTING time; a goal
        # that BECOMES plan-backed had no way to declare it. Without this exemption
        # such a goal FAIL_FIXABLEs on a doc the factory told it to write, with every
        # other arm green — measured twice on real drains (2026-08-18, 2026-08-19).
        # Markdown under a plans/ directory only: never code, so the scope guard keeps
        # its teeth everywhere that matters.
        if is_plan_doc(p):
            continue
        if touches and not _any_match(p, touches):
            violations.append(f"changed path outside declared surfaces: {p}")
    if violations:
        return {"name": "blast-radius", "pass": False, "kind": "fixable",
                "evidence": f"{len(violations)} out-of-scope path(s): " + _render(violations),
                "violations": violations}
    return {"name": "blast-radius", "pass": True, "kind": "fixable",
            "evidence": f"{len(changed_paths)} path(s), all in scope", "violations": []}


import re

# Only scan ADDED lines (start with '+' but not '+++').
_SECRET_PATTERNS = (
    re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}"),
    re.compile(r"gh[pousr]_[0-9A-Za-z]{36,}"),
    re.compile(r"sk-[0-9A-Za-z]{20,}"),  # OpenAI-style keys
)


def _added_lines(diff_text):
    """Yield (path, lineno, text) for every ADDED line in a unified diff.

    lineno is the line number in the NEW file, tracked off the hunk headers, so a
    violation can be reported as path:line the repair agent can open directly. A diff
    with no ``+++``/``@@`` framing (a bare fragment) still yields its ``+`` lines, with
    path None and a best-effort count.
    """
    path, lineno = None, 0
    for line in (diff_text or "").splitlines():
        if line.startswith("+++ "):
            p = line[4:].strip().split("\t", 1)[0]
            path = None if p == "/dev/null" else (p[2:] if p.startswith("b/") else p)
        elif line.startswith("@@"):
            # @@ -old[,cnt] +new[,cnt] @@ — take the new-file start, minus one so the
            # first body line increments onto it.
            try:
                lineno = int(line.split("+", 1)[1].split(" ", 1)[0].split(",", 1)[0]) - 1
            except (IndexError, ValueError):
                lineno = 0
        elif line.startswith("+"):
            lineno += 1
            yield path, lineno, line
        elif not line.startswith("-"):
            lineno += 1  # context line advances the new-file counter; removals do not


def forbidden_content(diff_text):
    violations = []
    for path, lineno, line in _added_lines(diff_text):
        for pat in _SECRET_PATTERNS:
            if pat.search(line):
                violations.append(f"{path or '(unknown file)'}:{lineno} matches /{pat.pattern}/")
    if violations:
        return {"name": "forbidden-content", "pass": False, "kind": "fixable",
                "evidence": f"secret-shaped string in {len(violations)} added line(s): "
                            + _render(violations),
                "violations": violations}
    return {"name": "forbidden-content", "pass": True, "kind": "fixable",
            "evidence": "no secret-shaped strings in added lines", "violations": []}


_RISK_PATH_KEYWORDS = ("auth", "billing", "payment", "migration", "deploy",
                       "prod", "secret", "credential", "password")
_RISK_FILENAMES = ("go.mod", "go.sum", "package.json", "package-lock.json",
                   "requirements.txt", "Cargo.toml", "Gemfile")
_FILE_THRESHOLD = 12


def chore_risk_flagged(changed_paths):
    if len(changed_paths) > _FILE_THRESHOLD:
        return True
    for p in changed_paths:
        low = p.lower()
        name = p.rsplit("/", 1)[-1]
        if any(k in low for k in _RISK_PATH_KEYWORDS):
            return True
        if name in _RISK_FILENAMES:
            return True
    return False


def in_scope(goal_type, changed_paths, mode):
    if mode == "off":
        return False
    if mode == "required":
        return True
    # risk_based (default)
    if goal_type in ("bug", "feature"):
        return True
    if goal_type == "chore":
        return chore_risk_flagged(changed_paths)
    return True  # unknown type → validate to be safe


def detect_gate_command(file_map):
    # Preference order: Makefile(test target) > go.mod > package.json(real test
    # script, run with the lockfile's package manager) > pytest. Blind picks are
    # guaranteed red gates: `make test` without a test target, `npm test` at a
    # pnpm/yarn workspace root, or the npm-init placeholder script.
    mk = file_map.get("Makefile")
    if mk is not None and re.search(r"(?m)^test\s*:", mk):
        return "make test"
    if "go.mod" in file_map:
        return "go test ./..."
    pj = file_map.get("package.json")
    if pj is not None:
        try:
            script = ((json.loads(pj) or {}).get("scripts") or {}).get("test")
        except (ValueError, AttributeError):
            # unparseable package.json: the old substring heuristic is the best signal left
            script = "test" if '"test"' in pj else None
        if script and "no test specified" not in script:
            pm = ("pnpm" if "pnpm-lock.yaml" in file_map else
                  "yarn" if "yarn.lock" in file_map else
                  "bun" if ("bun.lockb" in file_map or "bun.lock" in file_map) else
                  "npm")
            return f"{pm} test"
    if "pytest.ini" in file_map or "pyproject.toml" in file_map:
        return "pytest -q"
    return None


def repro_direction(base_exits, head_exits, already_correct, overlaid_tests=None,
                    cmds=None):
    # overlaid_tests: the PR head's changed test files that were copied onto the base
    # checkout before running acceptance. In standard TDD the proving test is ADDED by the
    # fix PR, so it does not exist on base — running the bare base suite can never go red
    # and every good TDD fix would FAIL_CONTRACT. Overlaying the head's tests onto base
    # product code is the canonical red-on-base proof: a real regression test fails there
    # (bug still present) and passes on head (bug fixed). None = no overlay performed.
    # cmds: the acceptance commands (parallel to the exit lists) — lets the failure
    # evidence name the red command instead of leaving the operator to dig for it.
    overlaid = list(overlaid_tests or [])
    head_all_green = all(x == 0 for x in head_exits)
    base_any_red = any(x != 0 for x in base_exits)
    if not head_all_green:
        return {"name": "repro-direction", "pass": False, "kind": "fixable",
                "evidence": "an acceptance command is still red on the PR head"
                            + _name_red(head_exits, cmds)}
    if base_any_red:
        how = (f"with the PR's {len(overlaid)} test file(s) overlaid onto base, "
               if overlaid else "")
        return {"name": "repro-direction", "pass": True, "kind": "fixable",
                "evidence": f">=1 command red on base {how}all green on head — "
                            "the test reproduces the bug, the fix resolves it (real fix)"}
    # nothing was red on base: the change fixed nothing observable
    if already_correct:
        return {"name": "repro-direction", "pass": True, "kind": "fixable",
                "evidence": "nothing red on base; goal documents code was already correct (locking test)"}
    if overlaid:
        return {"name": "repro-direction", "pass": False, "kind": "contract",
                "evidence": f"the PR's test file(s) {overlaid} were overlaid onto base product "
                            "code and still passed — the test does not reproduce the bug "
                            "(tautology/already-fixed). Write a test that fails on base, or "
                            "document 'already correct' with a locking test."}
    return {"name": "repro-direction", "pass": False, "kind": "contract",
            "evidence": "nothing red on base and the PR adds no recognizable test file, so the "
                        "fix can't be proven to reproduce->resolve a real bug. Add a failing "
                        "regression test (whose command is in acceptance:), or document "
                        "'already correct' with a locking test."}


def _name_red(exits, cmds):
    """': [i] <command> (exit N)' fragment for the red entries, '' when cmds unknown."""
    if not cmds:
        return ""
    red = [i for i, x in enumerate(exits) if x != 0 and i < len(cmds)]
    if not red:
        return ""
    return ": " + "; ".join(f"[{i}] {cmds[i]} (exit {exits[i]})" for i in red)


def acceptance_green(head_exits, cmds=None):
    if not head_exits:
        return {"name": "acceptance-green", "pass": False, "kind": "inconclusive",
                "evidence": "no acceptance command could be resolved for this goal"}
    if all(x == 0 for x in head_exits):
        return {"name": "acceptance-green", "pass": True, "kind": "fixable",
                "evidence": f"all {len(head_exits)} acceptance command(s) green on a fresh head checkout"}
    red = [i for i, x in enumerate(head_exits) if x != 0]
    return {"name": "acceptance-green", "pass": False, "kind": "fixable",
            "evidence": "acceptance command(s) red on fresh head checkout"
                        + (_name_red(head_exits, cmds) or f": index {red}")}


def queue_untouched(changed_paths):
    """The implementer must never edit docs/goals/ — the orchestrator owns queue state.
    v4.1.x is direct-to-branch (no goal/<id> branch, no PR), so the old branch-name /
    PR-body-marker / PR-base sub-checks are gone; this is the only integrity check with
    meaning on a local gate_base..HEAD diff."""
    for p in changed_paths:
        if p.startswith("docs/goals/"):
            return {"name": "queue-untouched", "pass": False, "kind": "fixable",
                    "evidence": f"implementer edited queue file {p!r}; the orchestrator owns docs/goals/"}
    return {"name": "queue-untouched", "pass": True, "kind": "fixable",
            "evidence": "implementer left docs/goals/ untouched"}


import argparse, glob, json, ntpath, os, posixpath, shutil, subprocess, tempfile
try:
    import yaml  # PyYAML — primary frontmatter parser; the factory already requires it
except ImportError:  # stdlib-only environment: the hand parser in _parse_goal takes over
    yaml = None
EXIT = {"PASS": 0, "FAIL_FIXABLE": 3, "FAIL_CONTRACT": 3, "INCONCLUSIVE": 4}


def _make_link(src, dst):
    """Create a dep-share link into the base worktree. Real symlink only — a directory
    junction is deliberately NOT a fallback (see the cleanup in run_validation for the
    data-loss chain). On Windows this needs Developer Mode or elevation (else
    WinError 1314), which the caller reports actionably instead of swallowing."""
    os.symlink(src, dst, target_is_directory=True)


def _remove_link(path):
    """Remove a link we created — the link/reparse point itself, never the target.
    Windows refuses unlink on directory symlinks; rmdir there removes just the link
    (and on a real non-empty dir it fails loudly instead of deleting content)."""
    try:
        os.unlink(path)
    except OSError:
        try:
            os.rmdir(path)
        except OSError:
            pass


def _dep_link_pairs(repo_root, basewt):
    """(src, dst) dep dirs to share with a base worktree: the top-level DEP_DIRS plus
    each workspace package's node_modules one or two levels deep (apps/*/node_modules,
    packages/*/node_modules). Workspace packages (pnpm/yarn/npm workspaces) resolve
    their runner bins from their OWN node_modules/.bin, so root-only linking leaves
    'jest' & co unresolvable on base. Skips node_modules nested inside another
    node_modules and packages that don't exist at the base SHA."""
    pairs = []
    for d in DEP_DIRS:
        src = os.path.join(repo_root, d)
        if os.path.isdir(src):
            pairs.append((src, os.path.join(basewt, d)))
    for pat in ("*", os.path.join("*", "*")):
        for src in glob.glob(os.path.join(repo_root, pat, "node_modules")):
            rel = os.path.relpath(src, repo_root)
            parts = rel.split(os.sep)
            if "node_modules" in parts[:-1] or parts[0] == ".git" or not os.path.isdir(src):
                continue
            dst = os.path.join(basewt, rel)
            if os.path.isdir(os.path.dirname(dst)):
                pairs.append((src, dst))
    return pairs


def _run(cmd, **kw):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, **kw)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", "not found"


def _git(args, **kw):
    out = subprocess.run(["git", *args], capture_output=True, text=True, **kw)
    return out.returncode, out.stdout, out.stderr


def _changed_paths(base_ref, head_ref="HEAD"):
    rc, out, _ = _git(["diff", "--name-only", f"{base_ref}..{head_ref}"])
    return [p for p in out.splitlines() if p.strip()] if rc == 0 else []


def is_test_path(p):
    """Heuristic test-file detector spanning JS/TS, Python, Go, Ruby, Rust, etc."""
    base = p.rsplit("/", 1)[-1]
    low = p.lower()
    if any(seg in low for seg in
           ("/__tests__/", "/test/", "/tests/", "/spec/", "/specs/", "/e2e/")):
        return True
    if any(t in base for t in (".test.", ".spec.", "_test.", "-test.", ".tests.")):
        return True
    if base.startswith("test_") and base.endswith(".py"):
        return True
    if base.endswith("_test.go") or base.endswith("_spec.rb") or base.endswith("Test.java"):
        return True
    return False


def is_plan_doc(p):
    """A markdown plan doc under a plans/ directory.

    Covers both conventions the factory writes: `docs/goals/plans/` (ideate's
    design tier) and a repo's own `writing-plans` output (e.g.
    `docs/superpowers/plans/`), plus their `done/` archives. Deliberately narrow —
    `.md` only, and only under a path segment literally named `plans` — so this
    can never exempt source, config, or a generated artifact.
    """
    low = p.lower()
    if not low.endswith(".md"):
        return False
    return low.startswith("plans/") or "/plans/" in low


def _changed_test_files(base_ref, head_ref="HEAD"):
    return [p for p in _changed_paths(base_ref, head_ref) if is_test_path(p)]


def _diff_text(base_ref, head_ref="HEAD"):
    rc, out, _ = _git(["diff", f"{base_ref}..{head_ref}"])
    return out if rc == 0 else ""


def _unquote(tok):
    """Strip ONE balanced pair of surrounding quotes — never a lone trailing quote
    that belongs to the command itself (`pnpm test -- --testPathPatterns '(a|b)'`) —
    then decode the quote style's own escapes: `\\"` / `\\\\` inside double quotes
    (other backslash sequences pass through untouched), `''` inside single quotes."""
    if not (len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'"):
        return tok
    body, q = tok[1:-1], tok[0]
    if q == "'":
        return body.replace("''", "'")
    out, esc = [], False
    for ch in body:
        if esc:
            out.append(ch if ch in "\\\"" else "\\" + ch)
            esc = False
        elif ch == "\\":
            esc = True
        else:
            out.append(ch)
    if esc:
        out.append("\\")
    return "".join(out)


def _flow_closes(s):
    """True if the line contains a `]` OUTSIDE quotes — the flow-array terminator.
    A backslash-escaped quote inside a double-quoted element doesn't close it."""
    quote, esc = None, False
    for ch in s:
        if esc:
            esc = False
        elif quote == '"' and ch == "\\":
            esc = True
        elif quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "]":
            return True
    return False


def _split_flow_items(fragment):
    """Split one YAML flow-array fragment (`["a", "b",` / `"c"]` / `[`) into cleaned
    items. Commas inside quotes don't split — real acceptance commands carry them
    (`python -c 'print(1, 2)'`) — and a `\\"` inside a double-quoted element doesn't
    close it. Bracket punctuation and comment tokens are dropped; each item then
    loses one balanced pair of quotes (with escape decoding, see _unquote)."""
    parts, buf, quote, esc = [], [], None, False
    for ch in fragment:
        if esc:
            buf.append(ch)
            esc = False
        elif quote == '"' and ch == "\\":
            buf.append(ch)
            esc = True
        elif quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf)); buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    out = []
    for tok in parts:
        t = _unquote(tok.strip().strip("[]").strip())
        if t and not t.startswith("#"):
            out.append(t)
    return out


def _as_str_list(v):
    """Coerce a YAML-parsed value to a clean list of strings (scalar → 1-item list)."""
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    s = str(v).strip()
    return [s] if s else []


def _parse_goal(path):
    """Return (type, touches, acceptance_cmds, already_correct).

    already_correct comes ONLY from an explicit frontmatter key
    (`already_correct: true`), never a substring scan of the body — a prose mention
    of the phrase (even negated, "was not already correct") must not flip an unproven
    bug fix into a PASS.

    Frontmatter is parsed with PyYAML when importable (the factory already requires
    it) — full YAML, escapes included. The hand parser below is the fallback for
    stdlib-only environments and for frontmatter PyYAML can't read; it accepts all
    three list shapes real goal files carry: inline flow (`acceptance: ["a", "b"]`),
    block sequence (`- "a"` lines), and multi-line flow — `[` opening on the key
    line or on its own line, one element per line, closing `]` — the shape YAML
    formatters reflow long arrays into. Missing the last shape silently parsed []
    and false-failed the gate.
    """
    text = open(path).read() if os.path.exists(path) else ""
    gtype, touches, cmds, already_correct = "feature", [], [], False
    if text.startswith("---"):
        parts = text.split("---", 2)
        fm = parts[1] if len(parts) >= 3 else ""
        if yaml is not None:
            try:
                data = yaml.safe_load(fm)
            except Exception:  # any scan/parse error → hand parser below
                data = None
            if isinstance(data, dict):
                gtype = str(data.get("type") or "feature").split()[0]
                ac = data.get("already_correct")
                already_correct = (ac is True or
                                   str(ac or "").strip().lower() in ("true", "yes", "1"))
                return (gtype, _as_str_list(data.get("touches")),
                        _as_str_list(data.get("acceptance")), already_correct)
        _collecting = None  # tracks which list field we're accumulating into
        _flow = False       # True while inside a multi-line [ … ] flow array
        for line in fm.splitlines():
            field = line.split(":", 1)[1].strip() if ":" in line else ""
            ls = line.strip()
            if _collecting and ls.startswith("#"):
                continue  # YAML comment inside the list — skip, keep collecting
            if _flow:
                target = touches if _collecting == "touches" else cmds
                target.extend(_split_flow_items(ls))
                if _flow_closes(ls):
                    _collecting, _flow = None, False
            elif ls.startswith("type:") and field:
                gtype = field.split()[0]
                _collecting = None
            elif ls.startswith("already_correct:") and field:
                already_correct = field.split()[0].strip().lower() in ("true", "yes", "1")
                _collecting = None
            elif ls.startswith("touches:") or ls.startswith("acceptance:"):
                _collecting = "touches" if ls.startswith("touches:") else "acceptance"
                items = _split_flow_items(field)
                if _collecting == "touches":
                    touches = items
                else:
                    cmds = items
                _flow = field.startswith("[") and not _flow_closes(field)
                if field and not _flow:
                    _collecting = None  # complete value on the key line
            elif _collecting and ls.startswith("-"):
                item = _unquote(ls.lstrip("- \t"))
                if _collecting == "acceptance":
                    cmds.append(item)
                elif _collecting == "touches":
                    touches.append(item)
            elif _collecting and ls.startswith("["):
                _flow = True  # flow array opens on its own line below the key
                target = touches if _collecting == "touches" else cmds
                target.extend(_split_flow_items(ls))
                if _flow_closes(ls):
                    _collecting, _flow = None, False
            elif ls and not ls.startswith("-"):
                _collecting = None  # non-list-item line ends collection
    return gtype, touches, cmds, already_correct


def _resolve_cmds(goal_file, repo_root):
    gtype, touches, goal_cmds, ac = _parse_goal(goal_file)
    if goal_cmds:
        return gtype, touches, goal_cmds, ac
    fm = {}
    for name in ("Makefile", "go.mod", "package.json", "pytest.ini", "pyproject.toml"):
        p = os.path.join(repo_root, name)
        if os.path.exists(p):
            try:
                fm[name] = open(p).read()
            except OSError:
                pass
    # Lockfiles pick the package manager; existence is the signal — never read a
    # potentially multi-MB lockfile.
    for name in ("pnpm-lock.yaml", "yarn.lock", "bun.lockb", "bun.lock"):
        if os.path.exists(os.path.join(repo_root, name)):
            fm[name] = ""
    det = detect_gate_command(fm)
    return gtype, touches, ([det] if det else []), ac


def _resolve_shell(environ=None, which=None, isfile=None, windows=None):
    """Full path to the POSIX shell that runs acceptance commands, or None.

    A bare-name ["bash", ...] argv is resolved by CreateProcess on Windows, which
    searches System32 BEFORE PATH — so with the WSL feature enabled, the distro-less
    launcher stub %SystemRoot%\\System32\\bash.exe shadows Git Bash and every command
    exits nonzero (execvpe(/bin/bash) failure), false-FAILing the gate. A full path
    bypasses that precedence. Order: $PG_BASH override > which('bash') > which('sh')
    (both rejected when they live under %SystemRoot%) > standard Git-for-Windows
    install locations built from env vars. None -> caller uses the platform shell.
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


def _run_cmds(cmds, cwd):
    if not _SHELL_MEMO:
        _SHELL_MEMO.append(_resolve_shell())
    shell = _SHELL_MEMO[0]
    # Bounded so a hung suite reds the gate instead of locking it forever.
    timeout = float(os.environ.get("PG_VALIDATE_TIMEOUT", "1800"))
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


def _self_test():
    # Pure-logic sweep only: skip the subprocess-driven self-test reentry and the
    # local-mode integration tests (test_local_*), which spawn the CLI end-to-end and
    # belong to the pytest run, not the in-process pure-check sweep.
    import test_pg_validate as t
    fns = [g for n, g in sorted(vars(t).items())
           if n.startswith("test_")
           and n != "test_self_test_exits_zero_and_announces"
           and not n.startswith("test_local_")]
    for fn in fns:
        fn()
    print(f"self-test: {len(fns)} pure check cases passed")
    return 0


def run_validation(head, goal_id, base, goal_file, repo_root):
    checks = []
    rc_head, sha_head, err_head = _git(["rev-parse", head]); sha_head = sha_head.strip()
    rc_base, sha_base, err_base = _git(["rev-parse", base]); sha_base = sha_base.strip()
    # Fail loud on unresolved refs: an empty/failed rev-parse must never flow into the
    # diffs and summary as a silent degrade. The v4 gate returns INCONCLUSIVE, never a
    # default PASS, when it cannot establish the SHAs it is validating.
    if rc_head != 0 or not sha_head or rc_base != 0 or not sha_base:
        bad = []
        if rc_head != 0 or not sha_head:
            bad.append(f"head {head!r} ({(err_head or '').strip() or 'empty SHA'})")
        if rc_base != 0 or not sha_base:
            bad.append(f"base {base!r} ({(err_base or '').strip() or 'empty SHA'})")
        evidence = "could not resolve ref(s): " + "; ".join(bad)
        return {
            "verdict": "INCONCLUSIVE",
            "sha_head": sha_head,
            "sha_base": sha_base,
            "checks": [{"name": "resolve-refs", "pass": False, "kind": "inconclusive",
                        "evidence": evidence}],
            "summary": f"INCONCLUSIVE: {evidence}",
        }
    gtype, touches, cmds, already_correct = _resolve_cmds(goal_file, repo_root)
    changed = _changed_paths(sha_base, sha_head)

    checks.append(queue_untouched(changed))
    checks.append(blast_radius(changed, touches))
    checks.append(forbidden_content(_diff_text(sha_base, sha_head)))

    if gtype == "bug":
        # Overlay the head's changed test files onto the base checkout so a TDD test
        # ADDED by the fix can still reproduce the bug on base product code (red-on-base).
        # Without this, every standard TDD fix (test introduced by the fix) is structurally
        # un-provable and FAIL_CONTRACTs. Overlay is monotonic: it only adds tests, never
        # removes the bug, so it can only move base toward red (the PASS direction).
        #
        # A fresh base worktree has NO installed deps (node_modules/.venv are gitignored), so
        # a test-runner acceptance (npm test / pytest) would red on base for ENVIRONMENT
        # reasons, not the bug — and be mistaken for a reproduction (false PASS). Two guards:
        # (a) best-effort symlink the live checkout's dep dirs into the base worktree; and
        # (b) when the proving test is a separate overlaid file, run a BARE-BASE control
        # FIRST (no overlay) — if base can't run the acceptance clean before the proving
        # test exists, the red is environment/pre-existing noise → INCONCLUSIVE, never PASS.
        # (Direct-probe acceptance — no overlaid test file, e.g. `grep` — needs no deps, so
        # the control is skipped and base-red is the legitimate bug signal.)
        test_files = _changed_test_files(sha_base, sha_head)
        bare_base_exits = []
        with tempfile.TemporaryDirectory() as basewt:
            rc_wt, _wt_out, wt_err = _git(["worktree", "add", "--detach", basewt, sha_base])
            if rc_wt != 0:
                # Could not populate the base checkout: acceptance would run in an
                # empty/incomplete dir, go red, and forge a false repro PASS. Return
                # INCONCLUSIVE (never PASS) rather than proceed. The temp dir is cleaned
                # by the context manager; no worktree was registered, so no remove needed.
                evidence = ("could not create base worktree for repro-direction: "
                            + ((wt_err or "").strip() or "git worktree add failed"))
                return {
                    "verdict": "INCONCLUSIVE",
                    "sha_head": sha_head,
                    "sha_base": sha_base,
                    "checks": checks + [{"name": "repro-direction", "pass": False,
                                         "kind": "inconclusive", "evidence": evidence}],
                    "summary": f"INCONCLUSIVE: {evidence}",
                }
            links, link_errors = [], []
            worktree_removed = False
            try:
                # (a) best-effort: share the live checkout's installed dep dirs (root +
                # per-workspace-package). We only ever create/remove the link itself —
                # never touch the real target dirs. Failures are RECORDED, not swallowed:
                # on Windows without Developer Mode/elevation os.symlink raises
                # WinError 1314, and a dep-less base run must never be mistaken for a
                # bug reproduction (see the link_errors guard below).
                for src, dst in _dep_link_pairs(repo_root, basewt):
                    if os.path.lexists(dst):
                        continue
                    try:
                        _make_link(src, dst)
                        links.append(dst)
                    except OSError as e:
                        link_errors.append(e)
                # (b) control: bare base (only meaningful when a separate proving test is
                # overlaid — otherwise base_exits IS the bare run).
                if test_files:
                    bare_base_exits = _run_cmds(cmds, basewt) if cmds else []
                    _git(["-C", basewt, "checkout", sha_head, "--", *test_files])
                base_exits = _run_cmds(cmds, basewt) if cmds else []
            finally:
                # NO junction fallback here, ever: a recursive delete that runs while a
                # dir link is live traverses it on Windows (junction — and cleanup-order
                # bugs make real symlinks just as dangerous) into the live dep store and
                # the workspace sources its inner links point at; a field report lost 41
                # tracked files this way. So: remove every link we created FIRST (the
                # link only), and if any survives, SKIP `git worktree remove --force`
                # entirely — TemporaryDirectory's rmtree removes links without following
                # them (Python >=3.8), and the stale registration is pruned after.
                for link in links:
                    _remove_link(link)
                if not any(os.path.lexists(l) for l in links):
                    _git(["worktree", "remove", basewt, "--force"])
                    worktree_removed = True
        if not worktree_removed:
            _git(["worktree", "prune"])
        # Dep links could not be created AND a base run is red: missing-deps noise is
        # indistinguishable from a bug reproduction — and on the direct-probe path (no
        # overlaid test, control skipped) it would forge a false repro PASS. INCONCLUSIVE,
        # with the cause and the operator fix named instead of a generic base-red message.
        if cmds and link_errors and (any(x != 0 for x in bare_base_exits)
                                     or any(x != 0 for x in base_exits)):
            e = link_errors[0]
            hint = (" — enable Windows Developer Mode (Settings → Privacy & security → "
                    "For developers) or run elevated so the gate can link deps into the "
                    "base worktree" if getattr(e, "winerror", None) == 1314 else "")
            evidence = (f"dependency dir(s) could not be linked into the base worktree "
                        f"({e}){hint}; the base run is red, which cannot be distinguished "
                        "from missing-deps noise — never counted as a bug reproduction. "
                        "Verify the fix manually.")
            return {
                "verdict": "INCONCLUSIVE",
                "sha_head": sha_head,
                "sha_base": sha_base,
                "checks": checks + [{"name": "repro-direction", "pass": False,
                                     "kind": "inconclusive", "evidence": evidence}],
                "summary": f"INCONCLUSIVE: {evidence}",
            }
        # If the bare base (pre-overlay) couldn't run the acceptance clean, the base "red" is
        # environment/setup noise or a pre-existing failure, not a bug reproduction — never
        # let that forge a PASS.
        if test_files and cmds and any(x != 0 for x in bare_base_exits):
            evidence = ("base checkout could not run the acceptance command(s) clean before "
                        "the proving test was overlaid (missing deps/setup in the base "
                        "checkout, a pre-existing base failure, or an acceptance command that "
                        "names a test file added by this fix — scope acceptance at a stable "
                        "runner, not the new file) — cannot prove repro-direction. "
                        "Verify the fix manually.")
            return {
                "verdict": "INCONCLUSIVE",
                "sha_head": sha_head,
                "sha_base": sha_base,
                "checks": checks + [{"name": "repro-direction", "pass": False,
                                     "kind": "inconclusive", "evidence": evidence}],
                "summary": f"INCONCLUSIVE: {evidence}",
            }
        head_exits = _run_cmds(cmds, repo_root) if cmds else []
        checks.append(repro_direction(base_exits, head_exits, already_correct,
                                      test_files, cmds=cmds))
    else:
        head_exits = _run_cmds(cmds, repo_root) if cmds else []
        checks.append(acceptance_green(head_exits, cmds=cmds))

    verdict = aggregate(checks)
    return {
        "verdict": verdict,
        "sha_head": sha_head,
        "sha_base": sha_base,
        "checks": checks,
        "summary": f"{verdict} @ {sha_head[:12]} (base {sha_base[:12]})",
    }


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pg_validate.py")
    ap.add_argument("--head", help="git ref or SHA of the head to validate (default HEAD)", default="HEAD")
    ap.add_argument("--base", required=False)   # git ref/SHA of the gate base (the post-claim HEAD)
    ap.add_argument("--goal"); ap.add_argument("--goal-file")
    ap.add_argument("--worktree-root")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not (a.head and a.goal and a.base and a.goal_file):
        ap.error("--head, --goal, --base, --goal-file are required")
    repo_root = a.worktree_root or os.getcwd()
    try:
        result = run_validation(a.head, a.goal, a.base, a.goal_file, repo_root)
    except Exception as e:  # environment/infra failure -> INCONCLUSIVE, never default-PASS
        print(json.dumps({"verdict": "INCONCLUSIVE", "checks": [],
                          "summary": f"environment error: {e}"}, indent=2))
        return 4
    print(json.dumps(result, indent=2))
    return EXIT[result["verdict"]]


if __name__ == "__main__":
    import sys
    sys.exit(main())
