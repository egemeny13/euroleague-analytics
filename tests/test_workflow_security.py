"""Tests asserting the GitHub Actions workflows keep their security posture.

WHY THIS FILE EXISTS. On 2026-08-30 `zizmor` was run against `.github/workflows/`
for the first time and returned 28 findings: 16 unpinned action references, 8
checkouts leaving a credential behind, 3 shell interpolations of a workflow
expression, and 1 workflow with no permissions block. Every one of them was
fixed. None of that stops the next workflow from reintroducing them.

These tests are the part that does. They are deliberately mechanical and read the
workflow files as text rather than as parsed YAML, for the same reason
`tests/test_ci_configuration.py` does: the repository's runtime dependency list
is two packages, and a test is a poor reason to grow it. PyYAML is currently
present transitively through the hosted-server tree, which is exactly the kind of
dependency that disappears without warning.

WHAT THESE TESTS DO NOT PROVE. They check the shape of the workflow files, not
the behaviour of the actions they name. A pinned SHA is proof that the reference
cannot move underneath us; it is not proof that the code at that SHA is safe.
Keeping the pins current is Dependabot's job, not this file's.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW_DIRECTORY = Path(".github") / "workflows"

# A pinned reference looks like `owner/repo@<40 hex characters>`, optionally with
# a subdirectory in the path and always followed by a comment naming the human
# readable version. The comment is not optional: a bare SHA is unreadable, and an
# unreadable pin is one nobody will ever update.
PINNED_USES = re.compile(r"^uses:\s+\S+@[0-9a-f]{40}\s+#\s*\S+")

USES_LINE = re.compile(r"^uses:\s+(\S+)")

EXPRESSION = re.compile(r"\$\{\{")


def workflow_files() -> list[Path]:
    """Every workflow file, sorted so a failure names the same file every run."""
    files = sorted(WORKFLOW_DIRECTORY.glob("*.yml"))
    assert files, f"No workflow files found under {WORKFLOW_DIRECTORY}"
    return files


def _uses_lines(text: str) -> list[tuple[int, str]]:
    """Return every `uses:` line as (line number, text with the leading dash gone).

    A step can write either `- uses: x` or, under a `- name:` step, a bare
    `uses: x`. Both are normalised to the same shape so one regex handles them.
    """
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip().removeprefix("- ").strip()
        if stripped.startswith("uses:"):
            found.append((number, stripped))
    return found


def _run_block_lines(text: str) -> list[tuple[int, str]]:
    """Return every line belonging to a `run:` block, with its line number.

    A `run:` whose value is written inline is one line and nothing more. Only a
    block scalar - `run: |` or `run: >` - continues onto the lines below it, and
    it ends at the first line indented no further than the `run:` itself.

    Getting this distinction right matters: a step written as `- run: command`
    can carry an `env:` block *underneath and indented further*, which a naive
    "everything more indented belongs to the command" rule would swallow. That
    rule reported `FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}` as a shell
    interpolation when an `env:` block is exactly the fix being asked for.
    """
    lines = text.splitlines()
    inside: list[tuple[int, str]] = []
    run_indent: int | None = None
    for number, line in enumerate(lines, start=1):
        stripped = line.strip().removeprefix("- ").strip()
        indent = len(line) - len(line.lstrip())
        if run_indent is not None:
            if not line.strip() or indent > run_indent:
                inside.append((number, line))
                continue
            run_indent = None
        if stripped.startswith("run:"):
            inside.append((number, line))
            value = stripped.removeprefix("run:").strip()
            if value.startswith(("|", ">")):
                run_indent = indent
    return inside


def test_every_action_reference_is_pinned_to_a_commit_sha() -> None:
    """A mutable tag or branch lets somebody else change what our workflows run.

    The sharp case this was written for: `superfly/flyctl-actions/setup-flyctl`
    was referenced at `@master` inside the only workflow that holds
    FLY_API_TOKEN. Whoever could move that branch could deploy to production.
    """
    offenders = []
    for path in workflow_files():
        for number, line in _uses_lines(path.read_text(encoding="utf-8")):
            if not PINNED_USES.match(line):
                offenders.append(f"{path.as_posix()}:{number}: {line}")
    assert not offenders, (
        "Every `uses:` must be pinned to a 40-character commit SHA followed by a "
        "`# version` comment. Unpinned or uncommented:\n  " + "\n  ".join(offenders)
    )


def test_every_workflow_declares_explicit_permissions() -> None:
    """Without a permissions block a workflow inherits the repository default.

    The repository default is a setting, not a property of the file, so a
    workflow with no block is one settings change away from holding a write
    token it never asked for. `fly-deploy.yml` was the one file missing this.
    """
    offenders = []
    for path in workflow_files():
        text = path.read_text(encoding="utf-8")
        if not any(line.startswith("permissions:") for line in text.splitlines()):
            offenders.append(path.as_posix())
    assert not offenders, (
        "These workflows declare no top-level `permissions:` block and therefore "
        "inherit the repository default:\n  " + "\n  ".join(offenders)
    )


def test_no_workflow_expression_is_interpolated_into_a_run_block() -> None:
    """`${{ ... }}` inside `run:` is substituted before the shell sees it.

    The value becomes shell source code rather than an argument, so an input
    containing a quote and a semicolon runs commands. Passing the value through
    `env:` instead makes it a variable the shell reads, never code it parses.
    """
    offenders = []
    for path in workflow_files():
        for number, line in _run_block_lines(path.read_text(encoding="utf-8")):
            if EXPRESSION.search(line):
                offenders.append(f"{path.as_posix()}:{number}: {line.strip()}")
    assert not offenders, (
        "Pass these through an `env:` block on the step and read them as shell "
        "variables instead of interpolating them into the command:\n  " + "\n  ".join(offenders)
    )


def test_checkout_never_persists_credentials() -> None:
    """`actions/checkout` leaves its token in `.git/config` unless told not to.

    Nothing here uploads artifacts today, so nothing leaks today. That is a fact
    about the current workflows, not a property of checkout, and it stops being
    true the first time somebody adds an upload step.
    """
    offenders = []
    for path in workflow_files():
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            match = USES_LINE.match(line.strip().removeprefix("- ").strip())
            if not match or not match.group(1).startswith("actions/checkout@"):
                continue
            # The setting belongs to this step, so only look as far as the next
            # `- ` step marker at the same indentation.
            following = "\n".join(lines[index + 1 : index + 8])
            block = following.split("\n      - ")[0]
            if "persist-credentials: false" not in block:
                offenders.append(f"{path.as_posix()}:{index + 1}")
    assert not offenders, (
        "These `actions/checkout` steps do not set `persist-credentials: false`:"
        "\n  " + "\n  ".join(offenders)
    )


def test_the_deploy_depends_on_the_tests() -> None:
    """A merge to master is a production release, so it must pass its tests first.

    The deploy used to be its own workflow triggered by `push`, which meant it
    and CI began at the same instant and neither waited for the other: the merge
    of pull request #25 stamps both runs 2026-08-29T21:10:31Z. A merge whose
    tests failed deployed anyway, because nothing asked.

    A `workflow_run` trigger was tried and rejected - it runs with secrets in the
    base repository's context and is the usual route by which a fork's pull
    request is handed a production token. `needs:` is a mechanism rather than a
    guard, so that is what this asserts.
    """
    assert not (WORKFLOW_DIRECTORY / "fly-deploy.yml").exists(), (
        "The deploy belongs to the CI workflow, where `needs: test` orders it "
        "after the tests. A separate workflow cannot express that dependency."
    )
    text = (WORKFLOW_DIRECTORY / "ci.yml").read_text(encoding="utf-8")
    assert "flyctl deploy" in text, "The deploy step is missing from ci.yml."
    deploy_job = text.split("  deploy:", 1)
    assert len(deploy_job) == 2, "ci.yml has no `deploy` job."
    assert "needs: test" in deploy_job[1], (
        "The deploy job must declare `needs: test`, or it runs alongside the "
        "tests rather than after them."
    )
    assert "github.event_name == 'push'" in deploy_job[1], (
        "The deploy job must refuse to run for a pull request; a pull request "
        "builds and tests, and deploys nothing."
    )
