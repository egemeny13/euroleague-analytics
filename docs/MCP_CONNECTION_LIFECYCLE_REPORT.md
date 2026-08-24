# MCP Connection Lifecycle and Latency Report — Order 7c

**Date:** 2026-08-24
**Status:** Attended Live Measurement Complete — Verified & Documented

---

## 1. Executive Summary

Order 7a identified that fresh connection setup and read-only verification dominated repeated MCP tool call latency (~1.4s per call on direct psycopg). Under the earlier server implementation, every single `tools/call` incurred this full teardown-and-reconnect overhead.

Order 7c aligned the connection lifecycle with the long-lived serial stdio MCP server process:
1. **Single Lazy Verified Connection:** Database connection is deferred during startup and tool discovery (`tools/list`). It opens lazily on the first query tool call via `connect(settings)`.
2. **Connection Reuse & Fresh Cursors:** Subsequent tool calls reuse the existing open connection, opening and closing only a fresh cursor per query.
3. **Bounded Error Recovery:** On retryable failures (`psycopg.OperationalError` or `psycopg.InterfaceError`), the broken connection is closed, a replacement connection is opened and verified read-only via `connect()`, and the query is retried exactly once. Non-connection exceptions do not retry.
4. **Clean Process Shutdown:** Process termination or EOF idempotently closes the cached connection in a `finally` block.
5. **Disabled Prepared Statement Spike:** `connect()` passes `autocommit=True` and `prepare_threshold=None` to eliminate psycopg's periodic 6th-call server preparation spike.
6. **Deterministic 35-Response Verification:** Every tool call generates a SHA-256 fingerprint of its canonical structured content, asserting strict byte-level equality across all 35 calls (5 processes × 7 calls).

---

## 2. Live Attended Evidence

### Workflows & Commits
- **Initial Live Workflow Run:** [Run 32774709049](https://github.com/egemeny13/euroleague-analytics/actions/runs/32774709049)  
  **Measured Workflow Head SHA:** `4e78e83004967044ec5288294911afc157567752`  
  **Implementation Commit SHA:** `da6d33b`
- **Fingerprint-Verified Live Workflow Run:** [Run 32775446200](https://github.com/egemeny13/euroleague-analytics/actions/runs/32775446200)  
  **Measured Workflow Head SHA:** `acbdce0563e016380f04c5884e94221e5413e712`

- **Target:** Supabase Shared Pooler (port 5432, session mode)
- **Client Environment:** Linux x86_64, Python 3.14.7 (GitHub Actions Ubuntu Runner)
- **Workload:** 5 fresh child processes, each initialized over stdio JSON-RPC and executing 7 repeated calls for the E2024 clutch shape (`el_get_possessions` with `max_seconds_remaining=300, max_margin=5, aggregate=True`).

### Aggregated Latency Summary (Run 32775446200)

| Metric | Measured Duration (Median) | Notes |
|---|---:|---|
| **Process Startup + Initialized** | **104.4 ms** | Measured separately: includes process spawn + JSON-RPC `initialize` negotiation; **0 database queries / 0 connections**. |
| **First Tool Call** | **1,611.9 ms** | Lazy connect + read-only verification (`SET` + `SHOW`) + query execution over stdio JSON-RPC. |
| **Warm Tool Calls (Calls 2–7)** | **605.8 ms** | Reused connection, fresh cursor + stdio JSON-RPC round trip to Frankfurt. |
| **Call Six Duration** | **605.5 ms** | Matches warm median — **no call-six preparation spike was observed in this run.** |
| **Same-Run Warm Reduction** | **62.4%** | Same-run reduction from first call (1,611.9 ms) to warm median (605.8 ms). (Run 32774709049 showed a 61.9% reduction from 2,096.9 ms to 799.3 ms). |

### Detailed Per-Process Series (Run 32775446200) (ms)

| Process | Startup | Call 1 (First) | Call 2 | Call 3 | Call 4 | Call 5 | Call 6 | Call 7 | Warm Median |
|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **P1** | 1,085.1 | 1,658.3 | 605.4 | 604.8 | 602.3 | 604.5 | 603.3 | 603.1 | **603.9** |
| **P2** | 104.0 | 1,568.4 | 608.8 | 603.2 | 603.3 | 607.4 | 605.5 | 606.0 | **605.8** |
| **P3** | 110.7 | 1,615.4 | 628.7 | 630.4 | 627.0 | 631.3 | 634.3 | 632.5 | **630.8** |
| **P4** | 104.3 | 1,468.3 | 574.0 | 574.3 | 572.6 | 573.0 | 572.7 | 574.5 | **573.5** |
| **P5** | 104.4 | 1,611.9 | 614.1 | 614.1 | 616.2 | 614.3 | 613.1 | 614.3 | **614.2** |

### Response Equivalence & Deterministic Fingerprint Verification
- **35 / 35** tool calls succeeded (`isError = false`).
- **Canonical SHA-256 Content Fingerprint:** `f739f21319e8f0bc3d33dd6aceaf34fe3f499d82561de11badb760663da5efa4`
- **Equality Assertion:** Verified 100% identical across all 35 responses (5 processes × 7 calls).
- Every call returned all 18 teams for E2024 clutch possessions with identical row counts, points, possessions, and straddle metrics (PRS: 168 poss, PAN: 165 poss, ASV: 154 poss ... BER: 63 poss).
- Zero non-protocol output on stdout; JSON-RPC stream protocol remained completely pure.

---

## 3. Boundary Comparison Note

Order 7a measured direct Python `psycopg` execution against the live warehouse without child-process stdio JSON-RPC framing (established connection: 136–138 ms; fresh connection: 1,424 ms). 

Order 7c measures the **real end-to-end MCP boundary**: a child process launched over stdio, JSON-RPC serialization, and network round-trip overhead. In this end-to-end harness:
- The first tool call paid ~1.6–2.1s (connection establishment + read-only proof + query).
- Reusing the connection dropped subsequent calls to ~605–799 ms (**61.9% to 62.4% reduction** within the same measurement run).
- Decision 18's PostgreSQL-execution thresholds (403 / 98 / 24 ms) remain intact and unchanged.

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

All offline tests pass cleanly:
1. `tests/test_mcp_connection_lifecycle.py`
2. `tests/test_mcp_resolve.py`
3. `tests/test_mcp_tools.py`
4. `tests/test_mcp_protocol.py`
5. `tests/test_measure_mcp_lifecycle.py`
6. `pytest` (723 passed, 83 deselected)
7. `ruff check .` (0 errors)
8. `ruff format --check .` (110 files formatted)
9. `git diff --check` (clean)

---

## 6. Blind Spots

1. **Remote Network Latency Variance:** Runner-to-Frankfurt latency accounts for the majority of the ~600–800 ms warm duration (PostgreSQL execution itself is < 1 ms). Local execution closer to Frankfurt will experience lower round-trip times.
2. **Idle Inactivity Eviction:** The tests verify recovery when a connection drops during query execution; they do not measure the exact idle timeout before the Supabase shared pooler drops an inactive socket.
3. **Concurrency:** The single serial stdio server does not test concurrent clients hitting the warehouse simultaneously.
4. **Database Connection Limits:** Connection pool limits under multiple concurrent MCP clients are unmeasured by this single-client architecture.
