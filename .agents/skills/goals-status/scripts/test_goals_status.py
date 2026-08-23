"""Tests for goals_status.py. Run: python3 test_goals_status.py  (or pytest).

Loads the target by path (no install needed), exercises the pure functions, and
runs the real CLI over a temp fixture queue.
"""
import importlib.util, os, subprocess, sys, tempfile

_here = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "gs", os.path.join(_here, "goals_status.py"))
gs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gs)

SCRIPT = os.path.join(_here, "goals_status.py")


# ---- fixtures ----------------------------------------------------------------

def _goal_md(title, gtype, model, outcome):
    return (
        "---\n"
        f"id: x\n"
        f"title: {title}\n"
        f"type: {gtype}   # bug | feature | chore\n"
        f"skills: []\n"
        f"model: {model}   # inherit | opus | sonnet | haiku\n"
        "---\n\n"
        "## Outcome (plain language)\n"
        f"{outcome}\n\n"
        "## Context / why\nsomething else entirely\n")


def _make_queue():
    """A temp docs/goals with one goal of each status + archive + a missing file."""
    d = tempfile.mkdtemp(prefix="goals-status-test-")
    index = (
        "config:\n"
        "  base: main\n"
        "  model: inherit\n"
        "  verify:\n"
        "    - python3 -m pytest -q\n"
        "goals:\n"
        "  001-done: {status: completed, priority: high}\n"
        "  002-rate-limit-api: {status: in_progress}\n"
        '  003-receipt-dupes: {status: blocked, reason: "gate FAIL — repro red after 3 tries"}\n'
        "  004-invoice-pdf: {status: not_started}\n"
        "  005-export-csv: {status: not_started, depends_on: [002-rate-limit-api]}\n"
        "  006-missing: {status: not_started}\n")
    with open(os.path.join(d, "index.yaml"), "w") as f:
        f.write(index)
    with open(os.path.join(d, "archive.yaml"), "w") as f:
        f.write("goals:\n  900-old: {status: completed}\n")
    files = {
        "002-rate-limit-api.md": _goal_md(
            "Rate-limit the public API", "feature", "sonnet",
            "Callers hitting /api/* more than 100x per minute get a 429 instead of "
            "silently degrading the service for everyone."),
        "003-receipt-dupes.md": _goal_md(
            "Stop duplicate receipt emails", "bug", "opus",
            "Some customers receive two receipts for a single payment."),
        "004-invoice-pdf.md": _goal_md(
            "Export invoices as a monthly PDF", "feature", "sonnet",
            "Finance can download one month of invoices as a single PDF."),
        "005-export-csv.md": _goal_md(
            "Export a transactions CSV", "feature", "sonnet",
            "Admins can export the month's transactions as a CSV."),
        # 006-missing.md deliberately absent
    }
    for name, body in files.items():
        with open(os.path.join(d, name), "w") as f:
            f.write(body)
    return d


# ---- index parsing -----------------------------------------------------------

def test_load_index_reads_entries():
    d = _make_queue()
    goals = gs.load_index(os.path.join(d, "index.yaml"))
    assert set(goals) == {"001-done", "002-rate-limit-api", "003-receipt-dupes",
                          "004-invoice-pdf", "005-export-csv", "006-missing"}
    assert goals["002-rate-limit-api"]["status"] == "in_progress"
    assert goals["005-export-csv"]["depends_on"] == ["002-rate-limit-api"]
    assert "gate FAIL" in goals["003-receipt-dupes"]["reason"]


def test_load_index_empty_and_missing():
    d = tempfile.mkdtemp(prefix="goals-status-empty-")
    with open(os.path.join(d, "index.yaml"), "w") as f:
        f.write("config:\n  base: main\ngoals: {}\n")
    assert gs.load_index(os.path.join(d, "index.yaml")) == {}
    assert gs.load_index(os.path.join(d, "nope.yaml")) == {}


def test_load_index_malformed_raises_queue_error():
    """A broken index must be loud: a partial queue read is worse than none."""
    d = tempfile.mkdtemp(prefix="goals-status-bad-")
    with open(os.path.join(d, "index.yaml"), "w") as f:
        f.write("goals:\n  001-x: {status: not_started\n  broken: [[[\n")
    try:
        gs.load_index(os.path.join(d, "index.yaml"))
    except gs.QueueError as e:
        assert "factory-doctor" in str(e)
    else:
        raise AssertionError("malformed index.yaml must raise QueueError")


# ---- frontmatter + brief -----------------------------------------------------

def test_parse_goal_file_fields_and_brief():
    d = _make_queue()
    gf = gs.parse_goal_file(os.path.join(d, "002-rate-limit-api.md"))
    assert gf["title"] == "Rate-limit the public API"
    assert gf["type"] == "feature"      # inline comment stripped by YAML
    assert gf["model"] == "medium"      # 'sonnet' stamp normalized to its tier
    assert gf["brief"].startswith("Callers hitting /api/*")
    assert "degrading the service" in gf["brief"]
    # brief stops at the blank line before the next section
    assert "something else entirely" not in gf["brief"]


def test_legacy_model_names_normalize_to_tiers():
    # goals stamped with the pre-v7 vocabulary must read as their tier
    d = _make_queue()
    gf = gs.parse_goal_file(os.path.join(d, "003-receipt-dupes.md"))  # model: opus
    assert gf["model"] == "heavy"
    out = gs.render_detailed(gs.build_report(d))
    assert "medium" in out          # 002 stamped sonnet
    assert "sonnet" not in out and "opus" not in out


def test_tier_names_pass_through_verbatim():
    d = tempfile.mkdtemp(prefix="goals-status-tier-")
    with open(os.path.join(d, "index.yaml"), "w") as f:
        f.write("config:\n  base: main\ngoals:\n  001-t: {status: in_progress}\n")
    with open(os.path.join(d, "001-t.md"), "w") as f:
        f.write(_goal_md("Tiered goal", "feature", "heavy", "Brief."))
    gf = gs.parse_goal_file(os.path.join(d, "001-t.md"))
    assert gf["model"] == "heavy"
    assert "heavy" in gs.render_detailed(gs.build_report(d))


def test_parse_goal_file_missing():
    gf = gs.parse_goal_file("/no/such/goal.md")
    assert gf["title"] == "(goal file missing)"
    assert gf["brief"] == ""


def test_parse_goal_file_malformed_frontmatter_degrades_not_crashes():
    """One unparseable goal file must not take the whole view down."""
    d = tempfile.mkdtemp(prefix="goals-status-ugly-")
    p = os.path.join(d, "002-ugly.md")
    with open(p, "w") as f:
        f.write('---\nid: 002-ugly\ntitle: "unterminated\ntype: [[[broken\n---\n\n'
                "## Outcome (plain language)\nStill readable prose.\n")
    gf = gs.parse_goal_file(p)
    assert gf["title"] == "(untitled)"
    assert gf["brief"] == "Still readable prose."   # body still parses


def test_extract_brief_fallbacks():
    # no Outcome section → first `##` section's paragraph
    body = "## Summary\nA plain summary line.\n\n## Next\nignore\n"
    assert gs._extract_brief(body) == "A plain summary line."
    # no sections at all → empty
    assert gs._extract_brief("just text, no headings") == ""


# ---- report assembly ---------------------------------------------------------

def test_build_report_grouping_ordering_and_counts():
    d = _make_queue()
    rep = gs.build_report(d)
    assert rep["open"] == 5                     # 001 completed excluded
    assert rep["completed"] == 2                # 001-done + archived 900-old
    ids = [g["id"] for g in rep["goals"]]
    # in_progress → blocked → not_started, id-sorted within group
    assert ids == ["002-rate-limit-api", "003-receipt-dupes",
                   "004-invoice-pdf", "005-export-csv", "006-missing"]
    by = {g["id"]: g for g in rep["goals"]}
    assert by["003-receipt-dupes"]["status"] == "blocked"
    assert "gate FAIL" in by["003-receipt-dupes"]["reason"]
    assert by["005-export-csv"]["waiting_on"] == ["002-rate-limit-api"]
    assert by["005-export-csv"]["ready"] is False
    assert by["004-invoice-pdf"]["ready"] is True
    assert by["006-missing"]["title"] == "(goal file missing)"


def test_build_report_no_index_returns_none():
    d = tempfile.mkdtemp(prefix="goals-status-noindex-")
    assert gs.build_report(d) is None


def test_build_report_all_completed():
    d = tempfile.mkdtemp(prefix="goals-status-allo-")
    with open(os.path.join(d, "index.yaml"), "w") as f:
        f.write("config:\n  base: main\ngoals:\n  001-a: {status: completed}\n")
    rep = gs.build_report(d)
    assert rep["open"] == 0 and rep["completed"] == 1


# ---- rendering ---------------------------------------------------------------

def test_render_detailed_hides_completed_and_shows_title_brief():
    d = _make_queue()
    out = gs.render_detailed(gs.build_report(d))
    assert "IN PROGRESS" in out and "BLOCKED" in out and "NOT STARTED" in out
    assert "5 open" in out and "2 completed (hidden)" in out
    assert "Rate-limit the public API" in out            # title
    assert "Callers hitting /api/*" in out               # brief
    assert "reason: gate FAIL" in out                    # blocked reason
    assert "waiting on 002-rate-limit-api" in out        # dep-blocked
    assert "001-done" not in out                         # completed hidden
    # in_progress group is rendered before blocked
    assert out.index("IN PROGRESS") < out.index("BLOCKED") < out.index("NOT STARTED")


def test_empty_and_all_completed_messages():
    d = tempfile.mkdtemp(prefix="goals-status-msg-")
    with open(os.path.join(d, "index.yaml"), "w") as f:
        f.write("config:\n  base: main\ngoals: {}\n")
    assert "queue is empty" in gs.render_detailed(gs.build_report(d))
    with open(os.path.join(d, "index.yaml"), "w") as f:
        f.write("config:\n  base: main\ngoals:\n  001-a: {status: completed}\n")
    assert "nothing open" in gs.render_detailed(gs.build_report(d))


# ---- end-to-end CLI ----------------------------------------------------------

def _run_cli(*args):
    r = subprocess.run([sys.executable, SCRIPT, *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def test_cli_default_view_and_exit_codes():
    d = _make_queue()
    rc, out, _ = _run_cli("--dir", d)
    assert rc == 0 and "IN PROGRESS" in out and "Rate-limit the public API" in out

    # no queue → exit 2, pointing at the fix
    empty = tempfile.mkdtemp(prefix="goals-status-none-")
    rc, out, err = _run_cli("--dir", empty)
    assert rc == 2 and "factory-doctor" in err


def test_cli_malformed_index_exits_2_not_silently_empty():
    d = tempfile.mkdtemp(prefix="goals-status-badcli-")
    with open(os.path.join(d, "index.yaml"), "w") as f:
        f.write("goals:\n  001-x: {status: not_started\n  broken: [[[\n")
    rc, out, err = _run_cli("--dir", d)
    assert rc == 2, (rc, out, err)
    assert "factory-doctor" in err
    assert "not valid YAML" in err
    assert out == ""            # never print a half-view as if it were the queue


if __name__ == "__main__":
    fns = [g for n, g in sorted(globals().items()) if n.startswith("test_")]
    for fn in fns:
        fn(); print("ok ", fn.__name__)
    print(f"\n{len(fns)} passed")
