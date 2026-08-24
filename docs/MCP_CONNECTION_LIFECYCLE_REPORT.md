# MCP Connection Lifecycle and Latency Report — Order 7c

**Date:** 2026-08-24
**Status:** Offline Acceptance Passed — Awaiting Owner Authorization for Attended Live Run

---

## 1. Executive Summary

Order 7a proved that fresh connection setup dominated repeated MCP tool call latency:
- Fresh connection path: ~1,400 ms (816–864 ms connect + 406–422 ms read-only setup + 142–146 ms first query).
- Established connection path: 136–138 ms round-trip overhead on a persistent client, while PostgreSQL execution was only 0.599–0.810 ms.

In Order 7c, we aligned the connection lifecycle with the long-lived serial stdio MCP server process:
1. **Single Lazy Verified Connection:** The connection is not opened during server initialization or tool discovery (`tools/list`). It opens lazily on the first query via `connect(settings)`.
2. **Connection Reuse:** Subsequent tool calls reuse the open connection, creating only a new cursor per call.
3. **Bounded Error Recovery:** On retryable failures (`psycopg.OperationalError` or `psycopg.InterfaceError`), the broken connection is discarded, a fresh connection is opened via `connect()` (re-verifying read-only status), and the query is retried exactly once.
4. **Clean Process Shutdown:** Process termination or EOF idempotently closes the cached connection in a `finally` block.
5. **Disabled Prepared Statement Spike:** `connect()` passes `prepare_threshold=None` to eliminate psycopg's periodic 6th-call preparation spike.

---

## 2. Plain-Language Function Walkthrough

As required by `CLAUDE.md`, here is a plain-language explanation of the implementation for non-programmer audit:

### `src/euroleague/mcp/db.py`: `ReadOnlyConnectionManager`

```python
class ReadOnlyConnectionManager:
    def __init__(self, factory: Callable[[], psycopg.Connection]) -> None:
        self._factory = factory
        self._connection: psycopg.Connection | None = None
```
- **Line-by-line explanation:**
  - `__init__`: Sets up the connection manager. It stores a "recipe" (`factory`) for creating a new database connection, but does **not** call it yet.
  - `self._connection = None`: Starts with no database connection open.

```python
    def run(
        self,
        query: Callable[[Any, dict[str, Any]], dict[str, Any]],
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        for attempt in range(2):
            try:
                if self._connection is None:
                    self._connection = self._factory()
                with self._connection.cursor() as cursor:
                    return query(cursor, arguments)
            except (psycopg.OperationalError, psycopg.InterfaceError):
                self.close()
                if attempt == 1:
                    raise
```
- **Line-by-line explanation:**
  - `run`: Executes a given database query function with the provided tool arguments.
  - `for attempt in range(2):`: Allows at most two tries (initial attempt + one retry).
  - `if self._connection is None: self._connection = self._factory()`: If we don't have an active connection yet (or if the previous one broke), open a fresh, read-only verified connection.
  - `with self._connection.cursor() as cursor:`: Create a temporary cursor to run the query, ensuring the cursor is automatically closed as soon as the query finishes, while leaving the underlying connection alive.
  - `return query(cursor, arguments)`: Run the query and return the resulting data dictionary.
  - `except (psycopg.OperationalError, psycopg.InterfaceError):`: Catch only genuine network or connection-drop errors. Other errors (like bad arguments or syntax errors) are not caught and will not trigger a retry.
  - `self.close()`: Safely close and discard the broken connection.
  - `if attempt == 1: raise`: If this was already the second attempt, stop and let the error propagate to the MCP protocol layer.

```python
    def close(self) -> None:
        if self._connection is not None:
            conn = self._connection
            self._connection = None
            with contextlib.suppress(Exception):
                conn.close()
```
- **Line-by-line explanation:**
  - `close`: Closes the connection cleanly.
  - `if self._connection is not None:`: If a connection exists:
  - `self._connection = None`: Clear our reference first so subsequent calls know it is gone.
  - `conn.close()`: Close the network connection, suppressing any network teardown exceptions.

---

## 3. Offline Verification Gate Results

All offline tests passed cleanly:

1. **Focused MCP lifecycle and error recovery tests:**
   - `tests/test_mcp_connection_lifecycle.py`
   - `tests/test_mcp_resolve.py`
   - `tests/test_mcp_tools.py`
   - `tests/test_mcp_protocol.py`
   - `tests/test_measure_mcp_lifecycle.py`
   - **Result:** 57 passed in 0.19s.

2. **Full repository test suite:**
   - `pytest`
   - **Result:** 721 passed, 83 deselected, 0 failed in 11.84s.

3. **Code formatting and lint checks:**
   - `ruff check .` — Passed (0 errors).
   - `ruff format --check .` — Passed (110 files properly formatted).
   - `git diff --check` — Clean (no whitespace or conflict markers).

---

## 4. Blind Spots of Offline Tests

Offline tests use test doubles and local pipes. They cannot prove:
1. Exact network latency to the Frankfurt Supabase instance.
2. Pooler socket eviction behavior over minutes of inactivity.
3. Actual GitHub Actions IPv4 runner performance.
4. Database server-side concurrency limits under high load.

---

## 5. Next Step: Attended Live Measurement

A dedicated GitHub Actions workflow is ready:
- File: `.github/workflows/mcp-connection-lifecycle.yml`
- Script: `scripts/measure_mcp_lifecycle.py --season E2024 --repetitions 7 --processes 5`
- Safety: `workflow_dispatch` only, forced read-only, zero production writes.

Per project rules, no live workflow has been triggered yet. Awaiting owner authorization.
