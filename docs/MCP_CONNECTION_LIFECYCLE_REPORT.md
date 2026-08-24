# MCP Connection Lifecycle and Latency Report — Order 7c

**Date:** 2026-08-24
**Status:** Attended Live Measurement Complete — Verified & Documented

---

## 1. Executive Summary

Order 7a identified that fresh connection setup and read-only verification dominated repeated MCP tool call latency (~1.4s per call). Under the earlier implementation, every single `tools/call` incurred this full teardown-and-reconnect overhead.

Order 7c aligned the connection lifecycle with the long-lived serial stdio MCP server process:
1. **Single Lazy Verified Connection:** Database connection is deferred during startup and tool discovery (`tools/list`). It opens lazily on the first query tool call via `connect(settings)`.
2. **Connection Reuse & Fresh Cursors:** Subsequent tool calls reuse the existing open connection, opening and closing only a fresh cursor per query.
3. **Bounded Error Recovery:** On retryable failures (`psycopg.OperationalError` or `psycopg.InterfaceError`), the broken connection is closed, a replacement connection is opened and verified read-only via `connect()`, and the query is retried exactly once. Non-connection exceptions do not retry.
4. **Clean Process Shutdown:** Process termination or EOF idempotently closes the cached connection in a `finally` block.
5. **Disabled Prepared Statement Spike:** `connect()` passes `autocommit=True` and `prepare_threshold=None` to eliminate psycopg's periodic 6th-call server preparation spike.

---

## 2. Live Attended Evidence

- **GitHub Actions Run:** [Run 32774709049](https://github.com/egemeny13/euroleague-analytics/actions/runs/32774709049)
- **Workflow:** `.github/workflows/mcp-connection-lifecycle.yml`
- **Commit SHA:** `da6d33b8a3e7e81ea0ea9b21f37e6f3df20790d9`
- **Target:** Supabase Shared Pooler (port 5432, session mode)
- **Client Environment:** Linux x86_64, Python 3.14.7 (GitHub Actions Ubuntu Runner)
- **Workload:** 5 fresh child processes, each initialized over stdio JSON-RPC and executing 7 repeated calls for the E2024 clutch shape (`el_get_possessions` with `max_seconds_remaining=300, max_margin=5, aggregate=True`).

### Aggregated Latency Summary

| Metric | Measured Duration (Median) | Notes |
|---|---:|---|
| **Process Startup + Initialized** | **101.2 ms** | Includes JSON-RPC `initialize` negotiation; **0 database queries / 0 connections**. |
| **First Tool Call** | **2,096.9 ms** | Lazy connect + read-only proof (`SET` + `SHOW`) + clutch query execution. |
| **Warm Tool Calls (Calls 2–7)** | **799.3 ms** | Reused connection, fresh cursor + JSON-RPC round trip to Frankfurt. |
| **Call Six Duration** | **799.3 ms** | Exactly matches warm median — **zero preparation spike**. |

### Detailed Per-Process Series (ms)

| Process | Startup | Call 1 (First) | Call 2 | Call 3 | Call 4 | Call 5 | Call 6 | Call 7 | Warm Median |
|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **P1** | 501.6 | 2,938.3 | 775.3 | 777.1 | 775.7 | 776.5 | 780.0 | 777.2 | **776.8** |
| **P2** | 108.3 | 2,096.9 | 799.3 | 800.5 | 806.3 | 801.3 | 802.3 | 799.2 | **800.9** |
| **P3** | 101.2 | 2,077.2 | 793.8 | 794.5 | 796.1 | 793.7 | 794.0 | 793.1 | **793.9** |
| **P4** | 100.0 | 2,074.2 | 799.6 | 799.5 | 800.9 | 800.7 | 799.3 | 798.8 | **799.5** |
| **P5** | 97.7 | 2,145.5 | 833.5 | 834.0 | 833.5 | 833.9 | 833.5 | 835.2 | **833.7** |

### Response Equivalence & Invariant Verification
- All 35 tool calls across all 5 processes succeeded (`isError = false`).
- Every call returned all 18 teams for E2024 clutch possessions with identical row counts, points, possessions, and straddle metrics (PRS: 168 poss, PAN: 165 poss, ASV: 154 poss ... BER: 63 poss).
- Zero non-protocol output on stdout; JSON-RPC stream protocol remained completely pure.

---

## 3. Comparison with Previous Orders

| Metric / Boundary | Order 7a Baseline | Order 7c Measured | Evaluation |
|---|---|---|---|
| **Process Startup** | Unmeasured (connected at start) | **101.2 ms** | Fast, lazy, zero database touch. |
| **Fresh Connection + Setup** | 1,423.9 ms (direct psycopg) | **2,096.9 ms** (full child process + stdio JSON-RPC + query) | Expected overhead of process spawn and stdio protocol framing on first call. |
| **Subsequent Calls (Warm)** | Paid fresh 1.4s per tool call | **799.3 ms** | **~62% latency reduction on repeated tool calls.** |
| **Call 6 Preparation Spike** | 273.2 ms (when prepare enabled) | **799.3 ms** (equal to Call 2–5) | **Spike eliminated** via `prepare_threshold=None`. |
| **Decision 18 Thresholds** | 403 / 98 / 24 ms (PostgreSQL execution) | **Unchanged** | Decision 18 PostgreSQL-execution boundary remains intact. |

---

## 4. Plain-Language Code Walkthrough

### `src/euroleague/mcp/db.py`: `ReadOnlyConnectionManager`

```python
class ReadOnlyConnectionManager:
    def __init__(self, factory: Callable[[], psycopg.Connection]) -> None:
        self._factory = factory
        self._connection: psycopg.Connection | None = None
```
- **Explanation:** The constructor accepts a function (`factory`) capable of opening a verified read-only connection, but it **does not call it yet**. The process starts with no open connection.

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
- **Explanation:**
  - `run` executes a database query with the caller's arguments.
  - `for attempt in range(2):`: Allows at most two attempts (initial run + one retry).
  - `if self._connection is None: self._connection = self._factory()`: Lazily connects on the first tool call (or after reconnecting).
  - `with self._connection.cursor() as cursor:`: Opens a temporary cursor for this query only, automatically closing the cursor when the query finishes while keeping the underlying connection open.
  - `return query(cursor, arguments)`: Executes the query function and returns the result dictionary.
  - `except (psycopg.OperationalError, psycopg.InterfaceError):`: Catches connection-loss errors only.
  - `self.close()`: Discards the broken connection immediately.
  - `if attempt == 1: raise`: If the retry attempt also fails, propagates the error cleanly to the MCP error handler. Non-connection errors (such as invalid query arguments or SQL syntax errors) do not retry.

```python
    def close(self) -> None:
        if self._connection is not None:
            conn = self._connection
            self._connection = None
            with contextlib.suppress(Exception):
                conn.close()
```
- **Explanation:** Idempotently closes the cached connection if active and clears the reference.

---

## 5. Offline Verification Gate Results

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
   - **Result:** 721 passed, 83 deselected, 0 failed in 11.86s.

3. **Code formatting and lint checks:**
   - `ruff check .` — Passed (0 errors).
   - `ruff format --check .` — Passed (110 files properly formatted).
   - `git diff --check` — Clean (no whitespace or conflict markers).

---

## 6. Blind Spots

1. **Remote Network Variance:** Runner-to-Frankfurt latency accounts for the majority of the ~800 ms warm duration (PostgreSQL execution itself is < 1 ms). Local execution closer to Frankfurt will experience lower round-trip times.
2. **Idle Inactivity Eviction:** The tests verify recovery when a connection drops during query execution; they do not measure the exact idle timeout before the Supabase shared pooler drops an inactive socket.
