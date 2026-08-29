# Hosted MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve the existing ten MCP tools over authenticated HTTP to two to five named users on Claude Desktop, without giving any of them a database credential.

**Architecture:** The official MCP Python SDK provides the StreamableHTTP transport and OAuth resource-server token validation; an external identity provider is the authorization server. The ten tool handlers, their schemas and their disclosure rules are reused unchanged from the stdio server — a second transport, never a second implementation. A thread-safe connection pool replaces the single-connection manager on the HTTP path only, and the server connects to PostgreSQL as a role that cannot write.

**Tech Stack:** Python 3.14, `mcp` SDK, psycopg 3, PostgreSQL (Supabase), Docker, Fly.io.

**Spec:** `docs/superpowers/specs/2026-08-27-hosted-mcp-server-design.md`

## Global Constraints

- **Python >= 3.14 is required.** `pyproject.toml` declares `requires-python = ">=3.14"`; ruff targets `py314`. PEP 758 syntax at `src/euroleague/mcp/db.py:63` will not parse on older interpreters.
- **All code, comments, names, commit messages and test names in English.** No exceptions.
- **Never sort play-by-play events.** Nothing in this plan touches event ordering; if a task appears to require it, stop and escalate.
- **The stdio path must not change behaviour.** `protocol.py`, `scripts/mcp_server.py` and `ReadOnlyConnectionManager` keep working exactly as they do. The full offline suite stays green.
- **Test before code.** Every task writes its failing test first.
- **`stdout` is the protocol channel on stdio.** Diagnostics go to stderr, always. This constraint carries into the HTTP server's logging.
- **Ruff:** line length 100, `select = ["E","F","I","UP","B","SIM","RUF"]`. Run `uv run ruff check .` and `uv run ruff format --check .` before every commit.
- **A bare `pytest` deselects `full_season`, `warehouse` and `network`.** Never pass `-m` on the command line for the default suite — that *replaces* the filter rather than adding to it.
- **Verify commands:** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`.
- **The seven views are `security_invoker`.** A role granted only views cannot read them; base-table grants are required. See spec section 6.3.
- **Never commit a credential.** Migration 0013 creates its role with no password.

## Relation inventory (used by Task 2)

The exact set the MCP server reads, derived from `src/euroleague/mcp/queries.py` and the view definitions.

**Seven views:** `v_game`, `v_team_game`, `v_player_game`, `v_lineup_player`, `v_possession`, `v_play_by_play`, `v_shot_data`

**Twelve base tables:** `game_event`, `game_quality`, `lineup`, `player`, `player_game_minutes`, `possession`, `raw_boxscore_player`, `raw_boxscore_team`, `raw_game`, `raw_shot`, `season_progress`, `team_season`

`season_progress` is read directly by `queries.py`, not only through a view. `lineup_stint` is deliberately absent — nothing the server serves reads it.

## File structure

| File | Responsibility |
|---|---|
| `src/euroleague/mcp/pool.py` (new) | Thread-safe pool of verified read-only connections |
| `src/euroleague/mcp/ratelimit.py` (new) | Per-subject request cap |
| `src/euroleague/mcp/http_app.py` (new) | Builds the ASGI app; registers tools; no queries, no SQL |
| `src/euroleague/mcp/logging_setup.py` (new) | Structured stderr logging with redaction |
| `scripts/mcp_http_server.py` (new) | Thin entry point: settings in, app out |
| `migrations/0013_readonly_role.{up,down}.sql` (new) | The read-only role and its grants |
| `Dockerfile`, `fly.toml` (new) | Deployment |
| `requirements-http.txt` (new) | The hosted dependency tree, fully pinned |
| `docs/OWNER_SETUP.md` (new) | Click-by-click for owner tasks O1–O7 |

**Dependency scoping decision.** The SDK goes in a new `requirements-http.txt`, not `requirements.txt`. This preserves the reason `protocol.py:8-11` gives for hand-rolling stdio — a light local install — while pinning the hosted tree fully. CI installs both so the parity tests run.

---

### Task 1: Record the transport decision

The spec makes this a gate: `CLAUDE.md` says "Transport: `stdio` for local use", and adding HTTP contradicts it. `CLAUDE.md` also forbids granting yourself an exemption silently. No code may land before this task.

**Files:**
- Modify: `DECISIONS.md` (append a new numbered item)
- Modify: `CLAUDE.md` (the MCP tool design section)
- Modify: `migrations/README.md` (add the 0013 row in Task 2, not here)

- [ ] **Step 1: Read the last decision number**

Run: `grep -nE '^## [0-9]+\.' DECISIONS.md | tail -3`
Note the highest number N. The new item is N+1.

- [ ] **Step 2: Append the decision to `DECISIONS.md`**

Use the file's existing heading style exactly as the previous item uses it. Content:

```markdown
**Decided 2026-08-27.** The MCP server gains an HTTP transport, served from a
single hosted container, alongside the existing stdio transport.

**What changes.** `scripts/mcp_http_server.py` serves the same ten tools over
StreamableHTTP using the official MCP Python SDK, authenticated as an OAuth 2.1
resource server against an external identity provider.

**What does not.** stdio remains the local default. `protocol.py`,
`scripts/mcp_server.py` and `ReadOnlyConnectionManager` are unchanged, and the
Order 7c latency evidence measured through them remains valid.

**Why the dependency argument does not carry over.** `protocol.py:8-11` rejects
the SDK because it triples a dependency tree for a locally installed server.
That reasoning holds for local installs and does not transfer to one container
built once: hand-rolling StreamableHTTP and OAuth 2.1 instead would put
conformance to a moving specification into code this project's owner cannot
read. The SDK is therefore scoped to `requirements-http.txt` and is not
installed by a local stdio user.

**Condition.** The HTTP path must publish a tool list byte-identical to the
stdio path, including the `readOnlyHint` annotation, enforced by test.

**Decided by:** the owner, 2026-08-27. Design:
`docs/superpowers/specs/2026-08-27-hosted-mcp-server-design.md`.
```

- [ ] **Step 3: Amend `CLAUDE.md`**

Find the line in the MCP tool design section reading:

```
- Transport: `stdio` for local use.
```

Replace it with:

```
- Transport: `stdio` for local use, and StreamableHTTP for the hosted server.
  Both serve the same tool registry; see `DECISIONS.md` item <N+1>.
```

Substitute the real number for `<N+1>`.

- [ ] **Step 4: Verify no test asserted the old wording**

Run: `uv run pytest tests/test_roadmap_consistency.py -v`
Expected: PASS. If it fails on the changed line, update the assertion to match the new wording — that test exists to keep documents honest, not to freeze them.

- [ ] **Step 5: Run the full offline suite**

Run: `uv run pytest`
Expected: PASS, no change in count.

- [ ] **Step 6: Commit**

```bash
git add DECISIONS.md CLAUDE.md
git commit -m "docs: record the decision to add an HTTP transport"
```

---

### Task 2: The read-only database role

**Files:**
- Create: `migrations/0013_readonly_role.up.sql`
- Create: `migrations/0013_readonly_role.down.sql`
- Modify: `migrations/README.md` (add a table row)
- Test: `tests/test_readonly_role.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a PostgreSQL role named `el_reader`. Later tasks assume a `DATABASE_URL` built on it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_readonly_role.py`:

```python
"""The tester-facing database role: it can read the served relations, and it cannot write.

Marked `warehouse` because it connects to the configured database. Excluded from
the default suite; run with `pytest -m warehouse`.
"""

from __future__ import annotations

import os

import psycopg
import pytest

from euroleague.config import DatabaseSettings

pytestmark = pytest.mark.warehouse

VIEWS = (
    "v_game",
    "v_team_game",
    "v_player_game",
    "v_lineup_player",
    "v_possession",
    "v_play_by_play",
    "v_shot_data",
)


def _reader_connection() -> psycopg.Connection:
    """Connect as the read-only role, skipping if its URL is not configured."""
    url = os.environ.get("READER_DATABASE_URL")
    if not url:
        pytest.skip("READER_DATABASE_URL is not set; cannot exercise the reader role.")
    return psycopg.connect(DatabaseSettings.from_url(url).url(), autocommit=True)


@pytest.mark.parametrize("view", VIEWS)
def test_reader_can_select_from_every_served_view(view: str) -> None:
    """Security-invoker views need base-table grants; this proves they were given."""
    with _reader_connection() as connection, connection.cursor() as cursor:
        cursor.execute(f"select 1 from {view} limit 1")
        cursor.fetchall()


def test_reader_can_select_from_season_progress() -> None:
    """queries.py reads this table directly, not through a view."""
    with _reader_connection() as connection, connection.cursor() as cursor:
        cursor.execute("select 1 from season_progress limit 1")
        cursor.fetchall()


def test_reader_cannot_insert() -> None:
    """The refusal must come from the database, not from our own care."""
    with _reader_connection() as connection, connection.cursor() as cursor:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute("insert into game_quality (season_code) values ('E9999')")


def test_reader_cannot_create_a_table() -> None:
    """No DDL, so a compromised server cannot reshape the warehouse."""
    with _reader_connection() as connection, connection.cursor() as cursor:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute("create table el_reader_probe (id int)")
```

- [ ] **Step 2: Run the tests to verify they skip cleanly**

Run: `uv run pytest -m warehouse tests/test_readonly_role.py -v`
Expected: SKIPPED with "READER_DATABASE_URL is not set". A skip here is correct — the role does not exist yet.

- [ ] **Step 3: Write the up migration**

Create `migrations/0013_readonly_role.up.sql`:

```sql
-- migrations/0013_readonly_role.up.sql
--
-- The credential the hosted MCP server connects with. It is not given to any
-- person: the server holds it, and the server is the only thing that does.
--
-- WHY BASE TABLES ARE GRANTED. Migration 0011 made all seven warehouse views
-- security_invoker, so a view executes with the caller's permissions. A role
-- granted only the views would fail every query with a permission error on the
-- underlying table. Granting the tables is what makes the views usable; it is
-- not a widening of intent. The role still cannot write anything.
--
-- WHY EVERY RELATION IS NAMED. `grant select on all tables in schema public`
-- would silently extend to every table added later, including tables holding
-- data this role was never meant to reach. Adding a relation here is a
-- deliberate act.
--
-- NO PASSWORD IS SET HERE. The owner sets it separately, so it never enters
-- version control. Until then the role cannot log in.

create role el_reader with login;

grant connect on database postgres to el_reader;
grant usage on schema public to el_reader;

-- The seven served views.
grant select on table public.v_game to el_reader;
grant select on table public.v_team_game to el_reader;
grant select on table public.v_player_game to el_reader;
grant select on table public.v_lineup_player to el_reader;
grant select on table public.v_possession to el_reader;
grant select on table public.v_play_by_play to el_reader;
grant select on table public.v_shot_data to el_reader;

-- The twelve base tables those views read, plus season_progress, which
-- queries.py reads directly. lineup_stint is deliberately absent: nothing the
-- server serves reads it.
grant select on table public.game_event to el_reader;
grant select on table public.game_quality to el_reader;
grant select on table public.lineup to el_reader;
grant select on table public.player to el_reader;
grant select on table public.player_game_minutes to el_reader;
grant select on table public.possession to el_reader;
grant select on table public.raw_boxscore_player to el_reader;
grant select on table public.raw_boxscore_team to el_reader;
grant select on table public.raw_game to el_reader;
grant select on table public.raw_shot to el_reader;
grant select on table public.season_progress to el_reader;
grant select on table public.team_season to el_reader;
```

- [ ] **Step 4: Write the down migration**

Create `migrations/0013_readonly_role.down.sql`:

```sql
-- migrations/0013_readonly_role.down.sql
--
-- Remove the read-only role. Every grant must be revoked before the role can be
-- dropped; PostgreSQL refuses to drop a role that still owns privileges.
--
-- Applying this while the hosted server is running will break it at the next
-- connection attempt. That is the intended behaviour of a rollback, not a
-- defect.

revoke select on table public.v_game from el_reader;
revoke select on table public.v_team_game from el_reader;
revoke select on table public.v_player_game from el_reader;
revoke select on table public.v_lineup_player from el_reader;
revoke select on table public.v_possession from el_reader;
revoke select on table public.v_play_by_play from el_reader;
revoke select on table public.v_shot_data from el_reader;

revoke select on table public.game_event from el_reader;
revoke select on table public.game_quality from el_reader;
revoke select on table public.lineup from el_reader;
revoke select on table public.player from el_reader;
revoke select on table public.player_game_minutes from el_reader;
revoke select on table public.possession from el_reader;
revoke select on table public.raw_boxscore_player from el_reader;
revoke select on table public.raw_boxscore_team from el_reader;
revoke select on table public.raw_game from el_reader;
revoke select on table public.raw_shot from el_reader;
revoke select on table public.season_progress from el_reader;
revoke select on table public.team_season from el_reader;

revoke usage on schema public from el_reader;
revoke connect on database postgres from el_reader;

drop role el_reader;
```

- [ ] **Step 5: Rehearse up/down/up on a disposable database**

Do NOT rehearse against production. Use the local PostgreSQL 17 instance the project already uses for fresh-database gates (`ROADMAP.md`, Phase 2c, "Fresh-database gate now exists").

Run, against the disposable instance:
```bash
psql "$LOCAL_TEST_DATABASE_URL" -f migrations/0013_readonly_role.up.sql
psql "$LOCAL_TEST_DATABASE_URL" -f migrations/0013_readonly_role.down.sql
psql "$LOCAL_TEST_DATABASE_URL" -f migrations/0013_readonly_role.up.sql
```
Expected: all three succeed with no error. If the down fails on a dependent privilege, the revoke list is incomplete — fix it rather than forcing the drop.

- [ ] **Step 6: Add the row to `migrations/README.md`**

Add to the table, after the `0012_roster_registration` row:

```markdown
| `0013_readonly_role` | Adds `el_reader`, the login role the hosted MCP server connects as: `select` on the seven views and the twelve base tables they read, and nothing else. No password is set by the migration. |
```

- [ ] **Step 7: Apply to production through the Supabase MCP**

Use `mcp__claude_ai_Supabase__apply_migration` with name `0013_readonly_role` and the up SQL. This is how migrations 0004 onward were applied; see `DECISIONS.md` item 10.

- [ ] **Step 8: Hand off to the owner (O2)**

The owner sets the role's password. Until they do, `el_reader` cannot log in and the tests in Step 1 will keep skipping. State this explicitly in the handoff — a skip is not a pass.

- [ ] **Step 9: After the owner sets the password, run the warehouse tests**

Run: `READER_DATABASE_URL=<the reader URL> uv run pytest -m warehouse tests/test_readonly_role.py -v`
Expected: all 10 PASS — 7 view reads, 1 `season_progress` read, and 2 refusals.

- [ ] **Step 10: Commit**

```bash
git add migrations/0013_readonly_role.up.sql migrations/0013_readonly_role.down.sql migrations/README.md tests/test_readonly_role.py
git commit -m "feat: add the el_reader read-only database role"
```

---

### Task 3: The connection pool

**Files:**
- Create: `src/euroleague/mcp/pool.py`
- Test: `tests/test_mcp_pool.py`

**Interfaces:**
- Consumes: `euroleague.mcp.db.connect`, `euroleague.config.DatabaseSettings`.
- Produces:
  - `class ConnectionPool` with `__init__(self, factory: Callable[[], psycopg.Connection], size: int = 5, statement_timeout_ms: int = 15000)`
  - `ConnectionPool.run(query: Callable[[Any, dict], dict], arguments: dict) -> dict` — same signature as `ReadOnlyConnectionManager.run`, so it is a drop-in for `build_registry`.
  - `ConnectionPool.close() -> None` — closes every pooled connection.

**Why the signature must match.** `build_registry(runner)` in `tools.py:78` takes any callable with the shape `(query, arguments) -> dict`. Matching it is what lets both transports share one registry.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mcp_pool.py`:

```python
"""The HTTP transport's connection pool: concurrency safety and timeout enforcement."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from euroleague.mcp.pool import ConnectionPool


class FakeCursor:
    """Records the statements issued against it."""

    def __init__(self, owner: "FakeConnection") -> None:
        self.owner = owner

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.owner.statements.append(sql)


class FakeConnection:
    def __init__(self, index: int) -> None:
        self.index = index
        self.statements: list[str] = []
        self.closed = False
        self.in_use = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def close(self) -> None:
        self.closed = True


def _factory() -> Any:
    counter = {"n": 0}

    def make() -> FakeConnection:
        counter["n"] += 1
        return FakeConnection(counter["n"])

    return make


def test_pool_sets_a_statement_timeout_on_each_connection() -> None:
    """A runaway query must be cut off by the database, not held forever."""
    pool = ConnectionPool(_factory(), size=2, statement_timeout_ms=15000)

    def query(cursor: Any, arguments: dict) -> dict:
        return {"ok": True}

    pool.run(query, {})
    connection = pool._all[0]
    assert any("statement_timeout" in statement for statement in connection.statements)
    pool.close()


def test_two_concurrent_calls_never_share_a_connection() -> None:
    """The bug this pool exists to prevent: two callers on one cursor."""
    pool = ConnectionPool(_factory(), size=2)
    seen: list[int] = []
    overlap = threading.Event()
    failures: list[str] = []

    def query(cursor: Any, arguments: dict) -> dict:
        connection = cursor.owner
        if connection.in_use:
            failures.append(f"connection {connection.index} was already in use")
        connection.in_use = True
        seen.append(connection.index)
        overlap.wait(timeout=1.0)
        connection.in_use = False
        return {"ok": True}

    threads = [threading.Thread(target=lambda: pool.run(query, {})) for _ in range(2)]
    for thread in threads:
        thread.start()
    time.sleep(0.2)
    overlap.set()
    for thread in threads:
        thread.join(timeout=2.0)

    assert failures == []
    assert len(set(seen)) == 2, "the two concurrent calls used the same connection"
    pool.close()


def test_close_closes_every_connection() -> None:
    """Graceful shutdown must not leave connections dangling on the database."""
    pool = ConnectionPool(_factory(), size=2)

    def query(cursor: Any, arguments: dict) -> dict:
        return {"ok": True}

    pool.run(query, {})
    pool.close()
    assert all(connection.closed for connection in pool._all)


def test_close_is_idempotent() -> None:
    """Shutdown can be triggered twice; the second must not raise."""
    pool = ConnectionPool(_factory(), size=1)
    pool.close()
    pool.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_mcp_pool.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'euroleague.mcp.pool'`

- [ ] **Step 3: Write the implementation**

Create `src/euroleague/mcp/pool.py`:

```python
"""A pool of verified read-only connections, for the HTTP transport only.

WHY THIS EXISTS. `ReadOnlyConnectionManager` holds exactly one connection,
because it was built for the long-lived *serial* stdio server: one caller, one
question at a time. Under HTTP two people can ask questions at the same instant,
and a shared connection and cursor produce crossed or truncated answers with no
error anywhere. The stdio path keeps the single-connection manager; this is its
concurrent sibling.

WHY A `SET` AND NOT A STARTUP OPTION, AGAIN. `statement_timeout` is applied
after connecting, for the same reason `db.py` applies the read-only setting that
way: Supabase's shared pooler rejects startup parameters it does not recognise,
which fails on the pooler only and works everywhere else.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Any

DEFAULT_POOL_SIZE = 5
DEFAULT_STATEMENT_TIMEOUT_MS = 15000


class ConnectionPool:
    """Hands each in-flight request its own connection and takes it back afterwards."""

    def __init__(
        self,
        factory: Callable[[], Any],
        size: int = DEFAULT_POOL_SIZE,
        statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    ) -> None:
        self._factory = factory
        self._size = size
        self._statement_timeout_ms = statement_timeout_ms
        self._idle: queue.LifoQueue[Any] = queue.LifoQueue(maxsize=size)
        self._all: list[Any] = []
        self._lock = threading.Lock()
        self._closed = False

    def _new_connection(self) -> Any:
        """Open a connection and bound how long any single statement may run."""
        connection = self._factory()
        with connection.cursor() as cursor:
            cursor.execute(f"set session statement_timeout = {self._statement_timeout_ms}")
        with self._lock:
            self._all.append(connection)
        return connection

    def _acquire(self) -> Any:
        """Take an idle connection, or open one while the pool is not yet full."""
        try:
            return self._idle.get_nowait()
        except queue.Empty:
            pass
        with self._lock:
            may_grow = len(self._all) < self._size
        if may_grow:
            return self._new_connection()
        return self._idle.get()

    def _release(self, connection: Any) -> None:
        try:
            self._idle.put_nowait(connection)
        except queue.Full:
            connection.close()

    def run(
        self,
        query: Callable[[Any, dict[str, Any]], dict[str, Any]],
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute one query on one connection that nothing else is using."""
        connection = self._acquire()
        try:
            with connection.cursor() as cursor:
                return query(cursor, arguments)
        finally:
            self._release(connection)

    def close(self) -> None:
        """Close every connection the pool ever opened. Safe to call twice."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            connections = list(self._all)
        for connection in connections:
            try:
                connection.close()
            except Exception:
                pass
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_mcp_pool.py -v`
Expected: 4 PASSED

- [ ] **Step 5: Run the full offline suite**

Run: `uv run pytest`
Expected: PASS, previous count + 4.

- [ ] **Step 6: Lint and format**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/euroleague/mcp/pool.py tests/test_mcp_pool.py
git commit -m "feat: add a concurrent connection pool for the HTTP transport"
```

---

### Task 4: The HTTP app and transport parity

**Files:**
- Create: `src/euroleague/mcp/http_app.py`
- Create: `requirements-http.txt`
- Modify: `.github/workflows/ci.yml` (install the HTTP requirements)
- Test: `tests/test_mcp_http_parity.py`

**Interfaces:**
- Consumes: `ConnectionPool.run` from Task 3; `build_registry` from `euroleague.mcp.tools`; `IDENTITY` from `euroleague.mcp.identity`.
- Produces:
  - `tool_fingerprint(published: list[dict]) -> str` — SHA-256 over canonical JSON of a normalised tool list.
  - `published_tools(registry: Mapping[str, Tool]) -> list[dict]` — the normalised wire shape, sorted by name.
  - `build_app(runner, *, verifier: Any = None, auth_settings: Any = None) -> Any` — the ASGI application. **Task 5 extends this signature with `cap: RequestCap | None = None`; Task 7 calls it with all four keywords.**
  - `_register(server: FastMCP, tool: Tool) -> None` — module-private. **Task 5 extends it to `_register(server, tool, cap)`.**

- [ ] **Step 1: Confirm the SDK's API surface before writing against it**

Run:
```bash
uv pip install "mcp>=1.13"
python -c "
import inspect, importlib.metadata as md
import mcp.server.fastmcp as f
print('version:', md.version('mcp'))
print('methods:', [n for n in dir(f.FastMCP) if not n.startswith('_')])
print('ctor:', inspect.signature(f.FastMCP.__init__))
print('add_tool:', inspect.signature(f.FastMCP.add_tool))
"
```
Expected: a method list including `add_tool`, `custom_route` and `streamable_http_app`; a constructor accepting auth and token-verifier arguments; and an `add_tool` accepting `name`, `title`, `description` and `annotations`.

**Record all four outputs.** The version is what `requirements-http.txt` pins in Step 7, and the two signatures are what Steps 4 and 6 must be written against. If any parameter name differs from what this plan shows, **use the real name** — this plan's SDK call sites were written from documentation, not from the installed package, and the installed package wins.

If `custom_route` is absent in the installed version, the health endpoint in Task 6 mounts a Starlette route around `streamable_http_app()` instead. Note which applies and carry it into Task 6.

- [ ] **Step 2: Write the failing parity tests**

Create `tests/test_mcp_http_parity.py`:

```python
"""The HTTP transport must publish exactly what the stdio transport publishes.

The risk this guards is drift: two transports slowly answering differently while
both look healthy. A response-only comparison is not enough — the readOnlyHint
annotation lives on the Tool dataclass in protocol.py, which the SDK path does
not use, so it can be lost silently.
"""

from __future__ import annotations

from typing import Any

from euroleague.mcp.http_app import published_tools, tool_fingerprint
from euroleague.mcp.tools import TOOL_NAMES, build_registry


def _registry() -> dict:
    def runner(query: Any, arguments: dict) -> dict:
        return {"unused": True}

    return build_registry(runner)


def test_every_published_tool_is_marked_read_only() -> None:
    """CLAUDE.md requires readOnlyHint, and the SDK path must not drop it."""
    for tool in published_tools(_registry()):
        assert tool["annotations"]["readOnlyHint"] is True, tool["name"]


def test_all_ten_tools_are_published() -> None:
    names = [tool["name"] for tool in published_tools(_registry())]
    assert sorted(names) == sorted(TOOL_NAMES)


def test_published_shape_matches_the_stdio_wire_shape() -> None:
    """published_tools must be derived from Tool.to_wire, never re-specified."""
    registry = _registry()
    expected = sorted(
        (tool.to_wire() for tool in registry.values()), key=lambda entry: entry["name"]
    )
    assert published_tools(registry) == expected


def test_fingerprint_is_stable_across_calls() -> None:
    assert tool_fingerprint(published_tools(_registry())) == tool_fingerprint(
        published_tools(_registry())
    )


def test_fingerprint_changes_when_an_annotation_is_lost() -> None:
    """The test that would catch a silently dropped readOnlyHint."""
    good = published_tools(_registry())
    damaged = [dict(tool) for tool in good]
    damaged[0] = {**damaged[0], "annotations": {}}
    assert tool_fingerprint(good) != tool_fingerprint(damaged)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_mcp_http_parity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'euroleague.mcp.http_app'`

- [ ] **Step 4: Write the implementation**

Create `src/euroleague/mcp/http_app.py`:

```python
"""The HTTP transport: the same ten tools, over StreamableHTTP.

THIS MODULE CONTAINS NO SQL AND DEFINES NO TOOL. It adapts the registry that
`tools.py` already builds. If a query or a tool description ever appears here,
the design has been violated: there would then be two definitions of the same
tool, and they would drift.

WHY THE HANDLERS RUN IN A WORKER THREAD. The SDK's HTTP server is async;
psycopg and every query function in this project are synchronous. Calling them
directly on the event loop would block every other request for the duration of
the query. `anyio.to_thread.run_sync` moves each call off the loop, which is
also why `pool.py` must be thread-safe.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Any

import anyio
from mcp.server.fastmcp import FastMCP

from euroleague.mcp.identity import SERVER_INFO, SERVER_INSTRUCTIONS
from euroleague.mcp.protocol import Tool
from euroleague.mcp.tools import build_registry


def published_tools(registry: Mapping[str, Tool]) -> list[dict[str, Any]]:
    """The wire shape of every tool, sorted by name.

    Derived from `Tool.to_wire` rather than re-specified, so the HTTP transport
    cannot describe a tool differently from the stdio transport.
    """
    return sorted((tool.to_wire() for tool in registry.values()), key=lambda entry: entry["name"])


def tool_fingerprint(published: list[dict[str, Any]]) -> str:
    """A stable SHA-256 over the published tool list.

    Same instrument as the Order 7c response fingerprints, applied to tools/list
    so a lost annotation fails a test instead of reaching a client unnoticed.
    """
    canonical = json.dumps(published, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_app(
    runner: Callable[[Callable[[Any, dict], dict], dict], dict],
    *,
    verifier: Any = None,
    auth_settings: Any = None,
) -> Any:
    """Assemble the ASGI application serving the ten tools over StreamableHTTP."""
    server = FastMCP(
        name=SERVER_INFO["name"],
        instructions=SERVER_INSTRUCTIONS,
        token_verifier=verifier,
        auth=auth_settings,
    )
    registry = build_registry(runner)

    for tool in registry.values():
        _register(server, tool)

    return server


def _register(server: FastMCP, tool: Tool) -> None:
    """Register one tool, preserving its schema and its annotations verbatim."""

    async def handler(**arguments: Any) -> dict[str, Any]:
        return await anyio.to_thread.run_sync(lambda: tool.handler(dict(arguments)))

    server.add_tool(
        handler,
        name=tool.name,
        title=tool.title or None,
        description=tool.description,
        annotations=tool.annotations,
        structured_output=True,
    )
```

- [ ] **Step 5: Run the parity tests**

Run: `uv run pytest tests/test_mcp_http_parity.py -v`
Expected: 5 PASSED

- [ ] **Step 6: Verify the SDK actually publishes the annotations**

Run:
```bash
python -c "
from euroleague.mcp.http_app import build_app
app = build_app(lambda q, a: {})
import asyncio
tools = asyncio.run(app.list_tools())
print([(t.name, t.annotations) for t in tools][:2])
"
```
Expected: every tool carries `readOnlyHint=True`. If the SDK drops or renames the field, fix `_register` until it does not — this is the exact failure Task 4 exists to prevent, and it must be settled here rather than discovered in Claude Desktop.

- [ ] **Step 7: Create `requirements-http.txt`**

Pin the version recorded in Step 1 and its resolved tree:

```bash
uv pip compile --output-file requirements-http.txt - <<'DEPS'
mcp==<version from Step 1>
DEPS
```

Then prepend this comment to the generated file:

```
# The hosted server's dependency tree, fully resolved and pinned.
#
# Deliberately separate from requirements.txt. protocol.py:8-11 rejects the MCP
# SDK for the stdio server because it triples a dependency tree for every local
# install. That reasoning still holds: a local stdio user installs
# requirements.txt and never sees this file. One container installs this one.
#
# Unlike requirements.txt, this pins the full transitive tree, because an
# internet-facing container is where an unpinned transitive dependency matters.
```

- [ ] **Step 8: Make CI install it**

In `.github/workflows/ci.yml`, find the dependency install step and add the HTTP requirements after the existing install:

```yaml
      - name: Install HTTP transport dependencies
        run: uv pip install --system -r requirements-http.txt
```

- [ ] **Step 9: Run the full offline suite**

Run: `uv run pytest`
Expected: PASS, previous count + 5. The stdio tests must be unchanged.

- [ ] **Step 10: Commit**

```bash
git add src/euroleague/mcp/http_app.py tests/test_mcp_http_parity.py requirements-http.txt .github/workflows/ci.yml
git commit -m "feat: serve the ten tools over StreamableHTTP with tool-list parity"
```

---

### Task 5: The request cap

**Files:**
- Create: `src/euroleague/mcp/ratelimit.py`
- Test: `tests/test_mcp_ratelimit.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `class RequestCap` with `__init__(self, limit: int = 120, window_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic)` and `check(subject: str) -> None`, raising `RateLimitExceeded` (a subclass of `RuntimeError`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mcp_ratelimit.py`:

```python
"""The per-subject request cap: enough to stop a looping client, and no more."""

from __future__ import annotations

import pytest

from euroleague.mcp.ratelimit import RateLimitExceeded, RequestCap


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_calls_under_the_limit_are_allowed() -> None:
    cap = RequestCap(limit=3, window_seconds=60.0, clock=FakeClock())
    for _ in range(3):
        cap.check("alice")


def test_the_call_over_the_limit_is_refused() -> None:
    cap = RequestCap(limit=3, window_seconds=60.0, clock=FakeClock())
    for _ in range(3):
        cap.check("alice")
    with pytest.raises(RateLimitExceeded):
        cap.check("alice")


def test_the_error_names_the_limit_and_a_next_step() -> None:
    """CLAUDE.md: error messages must suggest a concrete next step."""
    cap = RequestCap(limit=1, window_seconds=60.0, clock=FakeClock())
    cap.check("alice")
    with pytest.raises(RateLimitExceeded) as raised:
        cap.check("alice")
    message = str(raised.value)
    assert "1" in message
    assert "60" in message
    assert "wait" in message.lower()


def test_subjects_are_counted_separately() -> None:
    """One tester looping must not lock the others out."""
    cap = RequestCap(limit=1, window_seconds=60.0, clock=FakeClock())
    cap.check("alice")
    cap.check("bob")


def test_the_window_rolls_forward() -> None:
    clock = FakeClock()
    cap = RequestCap(limit=1, window_seconds=60.0, clock=clock)
    cap.check("alice")
    clock.now = 61.0
    cap.check("alice")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_mcp_ratelimit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'euroleague.mcp.ratelimit'`

- [ ] **Step 3: Write the implementation**

Create `src/euroleague/mcp/ratelimit.py`:

```python
"""A per-subject request cap.

WHAT THIS IS FOR. Not abuse: every user of this server is named and known. It is
for a client retrying in a loop, which can burn the Supabase free-tier compute
budget with nobody intending it.

WHAT IT IS NOT. A quota system. It does not measure or apportion usage, and it
will not notice sustained load that stays just under the limit. Counters live in
memory and reset when the container restarts, which is acceptable for a floor
and would not be for a quota.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

DEFAULT_LIMIT = 120
DEFAULT_WINDOW_SECONDS = 60.0


class RateLimitExceeded(RuntimeError):
    """Raised when a subject has exceeded its allowance for the current window."""


class RequestCap:
    """A rolling-window call counter, kept per subject."""

    def __init__(
        self,
        limit: int = DEFAULT_LIMIT,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._calls: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, subject: str) -> None:
        """Record one call, or refuse it if the subject is over the limit."""
        now = self._clock()
        with self._lock:
            history = self._calls.setdefault(subject, deque())
            while history and history[0] <= now - self._window:
                history.popleft()
            if len(history) >= self._limit:
                raise RateLimitExceeded(
                    f"Rate limit reached: {self._limit} calls per "
                    f"{int(self._window)} seconds. Please wait a moment and try again. "
                    f"If you are looping, stop and ask a single, more specific question."
                )
            history.append(now)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_mcp_ratelimit.py -v`
Expected: 5 PASSED

- [ ] **Step 5: Wire the cap into `http_app.py`**

In `src/euroleague/mcp/http_app.py`, extend both signatures so the cap reaches the handler:

```python
def build_app(
    runner: Callable[[Callable[[Any, dict], dict], dict], dict],
    *,
    verifier: Any = None,
    auth_settings: Any = None,
    cap: RequestCap | None = None,
) -> Any:
```

and

```python
def _register(server: FastMCP, tool: Tool, cap: RequestCap | None) -> None:
```

Update the loop in `build_app` to `_register(server, tool, cap)`, add `from euroleague.mcp.ratelimit import RequestCap` to the imports, and make the handler check the cap before doing any work:

```python
    async def handler(**arguments: Any) -> dict[str, Any]:
        if cap is not None:
            cap.check(_subject())
        return await anyio.to_thread.run_sync(lambda: tool.handler(dict(arguments)))
```

Add the subject helper, which prefers the authenticated identity and falls back to a shared bucket:

```python
def _subject() -> str:
    """Who to count this call against: the authenticated client, or everyone."""
    try:
        from mcp.server.auth.middleware.auth_context import get_access_token

        token = get_access_token()
    except Exception:
        return "anonymous"
    if token is None:
        return "anonymous"
    return token.client_id or "anonymous"
```

- [ ] **Step 6: Run the full offline suite**

Run: `uv run pytest`
Expected: PASS, previous count + 5.

- [ ] **Step 7: Lint, format, commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add src/euroleague/mcp/ratelimit.py src/euroleague/mcp/http_app.py tests/test_mcp_ratelimit.py
git commit -m "feat: cap requests per authenticated subject"
```

---

### Task 6: Logging, health and version

**Files:**
- Create: `src/euroleague/mcp/logging_setup.py`
- Modify: `src/euroleague/mcp/http_app.py`
- Test: `tests/test_mcp_logging.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `configure_logging(stream=sys.stderr, version: str = "") -> logging.Logger` and `redact(headers: Mapping[str, str]) -> dict[str, str]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mcp_logging.py`:

```python
"""Structured logging for the hosted server, and the redaction it must never skip."""

from __future__ import annotations

import io
import json

from euroleague.mcp.logging_setup import configure_logging, redact


def test_authorization_header_is_redacted() -> None:
    cleaned = redact({"authorization": "Bearer secret-token-value", "accept": "text/event-stream"})
    assert cleaned["authorization"] == "<redacted>"
    assert "secret-token-value" not in json.dumps(cleaned)
    assert cleaned["accept"] == "text/event-stream"


def test_redaction_is_case_insensitive() -> None:
    """A client may send Authorization, AUTHORIZATION, or authorization."""
    assert redact({"Authorization": "Bearer x"})["Authorization"] == "<redacted>"


def test_cookie_and_api_key_headers_are_redacted_too() -> None:
    cleaned = redact({"cookie": "session=abc", "x-api-key": "k"})
    assert cleaned["cookie"] == "<redacted>"
    assert cleaned["x-api-key"] == "<redacted>"


def test_logs_are_json_lines_carrying_the_version() -> None:
    stream = io.StringIO()
    logger = configure_logging(stream=stream, version="1.2.3")
    logger.info("tool_call", extra={"tool": "el_get_game", "outcome": "ok", "ms": 42})
    line = stream.getvalue().strip().splitlines()[-1]
    record = json.loads(line)
    assert record["message"] == "tool_call"
    assert record["tool"] == "el_get_game"
    assert record["outcome"] == "ok"
    assert record["ms"] == 42
    assert record["version"] == "1.2.3"


def test_logging_writes_to_the_given_stream_and_not_stdout(capsys) -> None:
    """stdout purity is a hard rule on stdio; the habit carries over."""
    stream = io.StringIO()
    logger = configure_logging(stream=stream, version="1.2.3")
    logger.info("tool_call", extra={"tool": "el_find_games", "outcome": "ok", "ms": 1})
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "tool_call" in stream.getvalue()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_mcp_logging.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'euroleague.mcp.logging_setup'`

- [ ] **Step 3: Write the implementation**

Create `src/euroleague/mcp/logging_setup.py`:

```python
"""Structured logs for the hosted server, on stderr, with credentials removed.

WHY THERE IS NO LOGGING ON THE STDIO PATH, AND WHY THAT WAS RIGHT. stdout is the
protocol channel; one stray write corrupts every message after it, and Order 7c
verified zero non-protocol output. That reasoning does not extend to the hosted
server, which nobody is watching and which must be debuggable after the fact.

WHAT IS DELIBERATELY NOT LOGGED. Tool arguments and tool responses, wholesale.
They can be large, and the arguments name players and teams a tester asked
about. Tool name, outcome and duration answer the operational questions without
recording what anyone looked up.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Mapping
from typing import Any, TextIO

REDACTED = "<redacted>"

SENSITIVE_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key"}
)

_STANDARD_FIELDS = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
        "levelname", "levelno", "lineno", "module", "msecs", "msg", "name", "pathname",
        "process", "processName", "relativeCreated", "stack_info", "thread", "threadName",
        "taskName",
    }
)


def redact(headers: Mapping[str, str]) -> dict[str, str]:
    """Copy headers with every credential-bearing value replaced."""
    return {
        name: (REDACTED if name.lower() in SENSITIVE_HEADERS else value)
        for name, value in headers.items()
    }


class _JsonFormatter(logging.Formatter):
    """One JSON object per line, carrying whatever `extra` the caller supplied."""

    def __init__(self, version: str) -> None:
        super().__init__()
        self._version = version

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname.lower(),
            "message": record.getMessage(),
            "version": self._version,
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_FIELDS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(stream: TextIO = sys.stderr, version: str = "") -> logging.Logger:
    """Install a single JSON handler on the server's logger and return it."""
    logger = logging.getLogger("euroleague.mcp")
    logger.handlers.clear()
    logger.propagate = False
    handler = logging.StreamHandler(stream)
    handler.setFormatter(_JsonFormatter(version))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_mcp_logging.py -v`
Expected: 5 PASSED

- [ ] **Step 5: Log every tool call in `http_app.py`**

Wrap the handler body in `_register` so each call records its name, outcome and duration:

```python
    async def handler(**arguments: Any) -> dict[str, Any]:
        if cap is not None:
            cap.check(_subject())
        started = time.monotonic()
        try:
            result = await anyio.to_thread.run_sync(lambda: tool.handler(dict(arguments)))
        except Exception:
            _LOGGER.exception(
                "tool_call",
                extra={
                    "tool": tool.name,
                    "outcome": "error",
                    "ms": round((time.monotonic() - started) * 1000),
                },
            )
            raise
        _LOGGER.info(
            "tool_call",
            extra={
                "tool": tool.name,
                "outcome": "ok",
                "ms": round((time.monotonic() - started) * 1000),
            },
        )
        return result
```

Add `import time` and `_LOGGER = logging.getLogger("euroleague.mcp")` at module level.

- [ ] **Step 6: Add the health and version endpoint**

In `build_app`, after the tools are registered — using the API confirmed in Task 4 Step 1:

```python
    @server.custom_route("/healthz", methods=["GET"])
    async def healthz(request: Any) -> Any:
        from starlette.responses import JSONResponse

        return JSONResponse(
            {
                "status": "ok",
                "name": SERVER_INFO["name"],
                "version": SERVER_INFO["version"],
                "tools": len(registry),
            }
        )
```

If Task 4 Step 1 found `custom_route` absent, mount the route on the Starlette app returned by `streamable_http_app()` instead, keeping the same path and JSON body.

- [ ] **Step 7: Run the full offline suite**

Run: `uv run pytest`
Expected: PASS, previous count + 5.

- [ ] **Step 8: Lint, format, commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add src/euroleague/mcp/logging_setup.py src/euroleague/mcp/http_app.py tests/test_mcp_logging.py
git commit -m "feat: add structured logging, health and version to the HTTP server"
```

---

### Task 7: Token verification and the entry point

**Files:**
- Create: `scripts/mcp_http_server.py`
- Modify: `src/euroleague/mcp/http_app.py`
- Modify: `.env.example`
- Test: `tests/test_mcp_http_auth.py`

**Interfaces:**
- Consumes: `build_app` from Task 4; `ConnectionPool` from Task 3; `RequestCap` from Task 5.
- Produces: `auth_from_env(values: Mapping[str, str]) -> tuple[Any, Any]` returning `(verifier, auth_settings)`, raising `ValueError` naming the missing variable.

**Which identity provider.** Any provider offering dynamic client registration and a token introspection endpoint. Free tiers at five users: Auth0 (25,000 monthly users), Stytch (10,000), WorkOS AuthKit (1,000,000), Descope. The choice is configuration, not code — the three environment variables below are all that changes.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mcp_http_auth.py`:

```python
"""Auth configuration: it must fail loudly at startup, never silently open."""

from __future__ import annotations

import pytest

from euroleague.mcp.http_app import auth_from_env

COMPLETE = {
    "MCP_ISSUER_URL": "https://example-idp.com",
    "MCP_RESOURCE_URL": "https://euroleague.fly.dev/mcp",
    "MCP_INTROSPECTION_URL": "https://example-idp.com/oauth2/introspect",
    "MCP_CLIENT_ID": "client-abc",
    "MCP_CLIENT_SECRET": "shhh",
}


def test_complete_configuration_produces_a_verifier_and_settings() -> None:
    verifier, settings = auth_from_env(COMPLETE)
    assert verifier is not None
    assert settings is not None


@pytest.mark.parametrize("missing", sorted(COMPLETE))
def test_each_missing_variable_is_named_in_the_error(missing: str) -> None:
    values = {key: value for key, value in COMPLETE.items() if key != missing}
    with pytest.raises(ValueError) as raised:
        auth_from_env(values)
    assert missing in str(raised.value)


def test_an_empty_environment_never_yields_an_unauthenticated_server() -> None:
    """The dangerous failure is starting with auth silently disabled."""
    with pytest.raises(ValueError):
        auth_from_env({})


def test_the_error_suggests_a_next_step() -> None:
    """CLAUDE.md: error messages must suggest a concrete next step."""
    with pytest.raises(ValueError) as raised:
        auth_from_env({})
    assert ".env" in str(raised.value) or "environment" in str(raised.value).lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_mcp_http_auth.py -v`
Expected: FAIL with `ImportError: cannot import name 'auth_from_env'`

- [ ] **Step 3: Add `auth_from_env` to `http_app.py`**

```python
AUTH_VARIABLES = (
    "MCP_ISSUER_URL",
    "MCP_RESOURCE_URL",
    "MCP_INTROSPECTION_URL",
    "MCP_CLIENT_ID",
    "MCP_CLIENT_SECRET",
)


def auth_from_env(values: Mapping[str, str]) -> tuple[Any, Any]:
    """Build the token verifier and auth settings, or refuse to start.

    There is deliberately no unauthenticated mode. A server that quietly starts
    without auth because a variable was mistyped is the worst outcome available,
    and it looks exactly like a working server.
    """
    missing = [name for name in AUTH_VARIABLES if not values.get(name)]
    if missing:
        raise ValueError(
            f"Cannot start the HTTP server: missing {', '.join(missing)}. "
            f"Set them in the environment or in .env; see .env.example for the shape. "
            f"The server has no unauthenticated mode."
        )

    from mcp.server.auth.provider import TokenVerifier  # noqa: F401
    from mcp.server.auth.settings import AuthSettings
    from mcp.server.auth.token_verifier import IntrospectionTokenVerifier

    verifier = IntrospectionTokenVerifier(
        introspection_endpoint=values["MCP_INTROSPECTION_URL"],
        server_url=values["MCP_RESOURCE_URL"],
        client_id=values["MCP_CLIENT_ID"],
        client_secret=values["MCP_CLIENT_SECRET"],
        validate_resource=True,
    )
    settings = AuthSettings(
        issuer_url=values["MCP_ISSUER_URL"],
        resource_server_url=values["MCP_RESOURCE_URL"],
        required_scopes=[],
    )
    return verifier, settings
```

Confirm the import paths and `IntrospectionTokenVerifier` parameter names against the version pinned in Task 4:

```bash
python -c "import mcp.server.auth.token_verifier as t; help(t.IntrospectionTokenVerifier.__init__)"
```
Adjust the call to match the real signature. Do not guess.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_mcp_http_auth.py -v`
Expected: 8 PASSED (1 + 5 parametrised + 2)

- [ ] **Step 5: Write the entry point**

Create `scripts/mcp_http_server.py`:

```python
"""Launch the EuroLeague MCP server over StreamableHTTP.

For the hosted deployment only. Local use stays on stdio via
scripts/mcp_server.py, which needs none of this file's dependencies.

Configuration, all required:
    DATABASE_URL             the el_reader connection string
    MCP_ISSUER_URL           the identity provider's issuer
    MCP_RESOURCE_URL         this server's own public URL, ending /mcp
    MCP_INTROSPECTION_URL    the provider's token introspection endpoint
    MCP_CLIENT_ID            this server's client id at the provider
    MCP_CLIENT_SECRET        this server's client secret at the provider
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

MINIMUM_PYTHON_VERSION = (3, 14)

if sys.version_info[:2] < MINIMUM_PYTHON_VERSION:
    print(
        f"euroleague-analytics requires Python >= 3.14 "
        f"(running {sys.version_info[0]}.{sys.version_info[1]}).",
        file=sys.stderr,
    )
    raise SystemExit(1)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from euroleague.config import DatabaseSettings  # noqa: E402
from euroleague.mcp.db import connect  # noqa: E402
from euroleague.mcp.http_app import auth_from_env, build_app  # noqa: E402
from euroleague.mcp.identity import SERVER_INFO  # noqa: E402
from euroleague.mcp.logging_setup import configure_logging  # noqa: E402
from euroleague.mcp.pool import ConnectionPool  # noqa: E402
from euroleague.mcp.ratelimit import RequestCap  # noqa: E402


def main() -> int:
    """Assemble the app and serve until terminated, draining the pool on the way out."""
    logger = configure_logging(version=SERVER_INFO["version"])
    try:
        settings = DatabaseSettings.from_env()
        verifier, auth_settings = auth_from_env(os.environ)
    except ValueError as failure:
        logger.error("startup_failed", extra={"reason": str(failure)})
        return 1

    pool = ConnectionPool(lambda: connect(settings))
    app = build_app(pool.run, verifier=verifier, auth_settings=auth_settings, cap=RequestCap())
    logger.info("server_ready", extra={"host": settings.host, "port": settings.port})
    try:
        app.run(transport="streamable-http")
    finally:
        pool.close()
        logger.info("server_stopped", extra={})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Document the new variables in `.env.example`**

Append, keeping the file free of the real project reference:

```
# The hosted HTTP server only. A local stdio user needs none of these.
# MCP_RESOURCE_URL is this server's own public URL and must end in /mcp.
MCP_ISSUER_URL=https://<your-identity-provider>
MCP_RESOURCE_URL=https://<your-app>.fly.dev/mcp
MCP_INTROSPECTION_URL=https://<your-identity-provider>/oauth2/introspect
MCP_CLIENT_ID=
MCP_CLIENT_SECRET=
```

- [ ] **Step 7: Confirm the redaction test still holds against `.env.example`**

Run: `uv run pytest tests/test_ci_configuration.py -v`
Expected: PASS. That file asserts `.env.example` carries no twenty-lowercase-letter project reference; the placeholders above must not introduce one.

- [ ] **Step 8: Run the full offline suite, lint, commit**

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
git add scripts/mcp_http_server.py src/euroleague/mcp/http_app.py tests/test_mcp_http_auth.py .env.example
git commit -m "feat: add the authenticated HTTP entry point"
```

---

### Task 8: Container image and Fly configuration

**Files:**
- Create: `Dockerfile`
- Create: `fly.toml`
- Create: `.dockerignore`

**Interfaces:**
- Consumes: `requirements-http.txt` from Task 4; `scripts/mcp_http_server.py` from Task 7.
- Produces: an image serving on port 8080 with `GET /healthz`.

- [ ] **Step 1: Write the `.dockerignore`**

```
.git
.venv
.tmp
.pytest_cache
.ruff_cache
__pycache__
exploration/cache
docs
tests
*.md
.env
```

- [ ] **Step 2: Write the `Dockerfile`**

```dockerfile
# Python 3.14 is required: src/euroleague/mcp/db.py uses PEP 758 exception
# syntax, which older interpreters cannot parse. A platform's default runtime
# is not new enough, so the version is pinned in the image.
FROM python:3.14-slim

# Run as a non-root user. Nothing here needs root, and a container that cannot
# write to its own filesystem is one less thing to reason about.
RUN useradd --create-home --uid 10001 appuser

WORKDIR /app

COPY requirements.txt requirements-http.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-http.txt

COPY src/ ./src/
COPY scripts/mcp_http_server.py ./scripts/
COPY pyproject.toml ./

USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

EXPOSE 8080

CMD ["python", "scripts/mcp_http_server.py"]
```

- [ ] **Step 3: Write `fly.toml`**

Frankfurt, co-located with the `eu-central-1` Supabase project, always on.

```toml
app = "euroleague-analytics-mcp"
primary_region = "fra"

[build]

[http_service]
  internal_port = 8080
  force_https = true
  # Always on. docs/MCP_CONNECTION_LIFECYCLE_REPORT.md measured 1,612 ms for a
  # first call against 606 ms warm; scaling to zero makes every question a
  # first call, and adds container start on top.
  auto_stop_machines = false
  auto_start_machines = true
  min_machines_running = 1

  [http_service.concurrency]
    type = "requests"
    soft_limit = 20
    hard_limit = 40

  [[http_service.checks]]
    grace_period = "10s"
    interval = "30s"
    method = "GET"
    path = "/healthz"
    timeout = "5s"

[[vm]]
  size = "shared-cpu-1x"
  memory = "256mb"
```

- [ ] **Step 4: Build the image locally and verify it starts**

```bash
docker build -t euroleague-mcp .
docker run --rm -e DATABASE_URL=postgresql://u:p@localhost:5432/x euroleague-mcp
```
Expected: it exits 1 with a `startup_failed` JSON log naming the missing `MCP_*` variables. That is the correct behaviour — Task 7 Step 3 guarantees there is no unauthenticated mode.

- [ ] **Step 5: Verify the image runs as non-root**

```bash
docker run --rm --entrypoint id euroleague-mcp
```
Expected: `uid=10001(appuser)`. A root container here would be a finding.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile fly.toml .dockerignore
git commit -m "build: add the container image and Fly.io configuration"
```

---

### Task 9: The owner setup document

Spec decision D9. Written before the owner is asked to do O3 through O7, so no step is improvised.

**Files:**
- Create: `docs/OWNER_SETUP.md`
- Modify: `README.md` (link it from the "Running the MCP server" section)

- [ ] **Step 1: Write `docs/OWNER_SETUP.md`**

Cover O1 through O7 in order. For each: what to click, in which menu, what to type, and **what a correct result looks like** so a wrong turn is visible immediately. Structure:

1. **O1 — repaste the `DATABASE_URL` secret.** `gh secret set DATABASE_URL`, then `gh workflow run e2026-live.yml`. Correct result: the run goes green and the fetch step reports zero new games. Warn explicitly: the value must begin `postgresql://postgres.<project-ref>:`, and it must not be pasted into any chat.
2. **O2 — set the `el_reader` password.** Supabase dashboard, SQL editor, `alter role el_reader with password '<generated>'`. Correct result: `psql` with the reader URL connects, `select 1 from v_game limit 1` succeeds, and `insert into game_quality ...` fails with "permission denied".
3. **O3 — create the Fly.io account.** Card required; no free allowance since 2024, new accounts get $5 trial credit. Expected steady cost ~$1.94/month.
4. **O4 — create the identity provider account.** Enable dynamic client registration. Record issuer URL, introspection URL, client id and client secret.
5. **O5 — store the secrets.** `fly secrets set DATABASE_URL=... MCP_CLIENT_SECRET=...` and so on. Correct result: `fly secrets list` shows the names with no values.
6. **O6 — add the connector in Claude Desktop.** Settings, Connectors, Add custom connector, paste `https://<app>.fly.dev/mcp`, click Connect, sign in. Correct result: ten tools listed, each marked read-only.
7. **O7 — invite the testers.** Send the provider's signup link. Correct result: each tester completes the same O6 flow and sees the same ten tools.

Each step states what to do if the result does not match, and says plainly when to stop and ask rather than improvise.

- [ ] **Step 2: Link it from the README**

In the "Running the MCP server" section, after the stdio instructions:

```markdown
The hosted server, and the owner steps that stand it up, are documented in
[`docs/OWNER_SETUP.md`](docs/OWNER_SETUP.md).
```

- [ ] **Step 3: Check the README's own consistency tests**

Run: `uv run pytest tests/test_roadmap_consistency.py -v`
Expected: PASS. That file asserts the README carries no absolute owner path; the new text must not introduce one.

- [ ] **Step 4: Commit**

```bash
git add docs/OWNER_SETUP.md README.md
git commit -m "docs: add the owner setup guide for the hosted server"
```

---

### Task 10: Deploy and verify end to end

Owner-gated. Do not start until Tasks 1 through 9 are merged, O2 is done, and the Task 2 warehouse tests pass.

**Files:** none created. This task produces evidence.

- [ ] **Step 1: Deploy**

```bash
fly launch --no-deploy --copy-config --name euroleague-analytics-mcp --region fra
fly secrets set DATABASE_URL="..." MCP_ISSUER_URL="..." MCP_RESOURCE_URL="..." \
  MCP_INTROSPECTION_URL="..." MCP_CLIENT_ID="..." MCP_CLIENT_SECRET="..."
fly deploy
```

- [ ] **Step 2: Verify health**

```bash
curl -s https://euroleague-analytics-mcp.fly.dev/healthz
```
Expected: `{"status":"ok","name":"euroleague-analytics","version":"0.1.0","tools":10}`

- [ ] **Step 3: Verify the server refuses an unauthenticated call**

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  https://euroleague-analytics-mcp.fly.dev/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```
Expected: `401`, with a `WWW-Authenticate` header naming the protected-resource metadata URL. A `200` here is a release blocker — stop and fix before going further.

- [ ] **Step 4: Verify the discovery document**

```bash
curl -s https://euroleague-analytics-mcp.fly.dev/.well-known/oauth-protected-resource
```
Expected: JSON naming the resource and its authorization server.

- [ ] **Step 5: Owner connects from Claude Desktop (O6)**

Follow `docs/OWNER_SETUP.md` step 6. Expected: the OAuth sign-in completes, and ten tools appear, each marked read-only.

- [ ] **Step 6: Compare a live answer against the stdio server**

Call `el_get_possessions` with `season_code=E2024, max_seconds_remaining=300, max_margin=5, aggregate=True` through the hosted connector, and run the same call locally over stdio. Expected: identical numbers. Order 7c's fingerprint for that exact call is
`f739f21319e8f0bc3d33dd6aceaf34fe3f499d82561de11badb760663da5efa4` — the response content should still reduce to it.

- [ ] **Step 7: Verify the write refusal in production**

Run the Task 2 warehouse tests against the production reader credential:
```bash
READER_DATABASE_URL="..." uv run pytest -m warehouse tests/test_readonly_role.py -v
```
Expected: 10 PASSED.

- [ ] **Step 8: Record the evidence**

Create `docs/HOSTED_MCP_DEPLOYMENT_REPORT.md` in the style of the other reports in `docs/`: what was deployed, the health output, the 401 evidence, the fingerprint comparison, the reader-role test result, and the measured latency of a warm call against Order 7c's 606 ms baseline. State what the deployment does **not** establish — that it says nothing about correctness beyond consistency with stdio, and nothing about behaviour under load.

- [ ] **Step 9: Commit**

```bash
git add docs/HOSTED_MCP_DEPLOYMENT_REPORT.md
git commit -m "docs: record the hosted MCP server deployment evidence"
```

---

## Owner tasks, extracted

These appear inline above; collected here so the owner can see their whole commitment in one place. Roughly thirty minutes total.

| ID | Task | Appears in | Time |
|---|---|---|---|
| O1 | Repaste the `DATABASE_URL` secret and re-run the workflow | Before everything; urgent and independent | 5 min |
| O2 | Set the `el_reader` password in Supabase | Task 2, Step 8 | 2 min |
| O3 | Create the Fly.io account and add a card | Before Task 10 | 10 min |
| O4 | Create the identity provider account | Before Task 7 configuration | 5 min |
| O5 | Store the six secrets with `fly secrets set` | Task 10, Step 1 | 3 min |
| O6 | Add the connector in Claude Desktop and sign in | Task 10, Step 5 | 5 min |
| O7 | Send the testers their signup link | After Task 10 | 2 min |
| O8 | Review and approve this plan | Now | — |

## Test inventory

The ten tests the spec requires, and where they land.

| Spec test | Task | File |
|---|---|---|
| 1. Transport equality | 4 | `tests/test_mcp_http_parity.py` |
| 2. Write refusal | 2 | `tests/test_readonly_role.py` |
| 3. View reachability | 2 | `tests/test_readonly_role.py` |
| 4. Concurrency | 3 | `tests/test_mcp_pool.py` |
| 5. Unauthenticated rejection | 7, 10 | `tests/test_mcp_http_auth.py`, Task 10 Step 3 |
| 6. Existing suite unchanged | 3–7 | every task's full-suite step |
| 7. Tool list equality | 4 | `tests/test_mcp_http_parity.py` |
| 8. Timeout enforcement | 3 | `tests/test_mcp_pool.py` |
| 9. Request cap | 5 | `tests/test_mcp_ratelimit.py` |
| 10. Log redaction | 6 | `tests/test_mcp_logging.py` |
