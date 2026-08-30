"""Run the attended R-7 concurrency measurement against the hosted MCP server.

The bearer credential is obtained through Auth0 Device Authorization Flow or
read from EL_MCP_TOKEN in this process. It is never accepted as a command-line
argument, printed, or written into the JSON result. The result contains timings,
row counts, content fingerprints and error class names, but no response payload.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import sys
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import httpx2
import requests
from check_hosted_token import discovery
from check_hosted_token import main as check_hosted_claims

from euroleague.measure_hosted_load import (
    DEFAULT_CONCURRENCY_LEVELS,
    DEFAULT_INTER_WAVE_SECONDS,
    DEFAULT_WARMUP_CONCURRENCY,
    DEFAULT_WAVE_COUNT,
    DeviceAuthorizationError,
    obtain_device_token,
    parse_sse_jsonrpc,
    run_load_suite,
)

DEFAULT_SERVER = "https://euroleague-analytics-mcp.fly.dev"
# This is the public identifier of the shared Native application recorded in
# docs/AUTH0_CONFIGURATION.md. Native client IDs are identifiers, not secrets.
DEFAULT_CLIENT_ID = "xc7tUVTYYK77nIG2Dp5brRU976MwiSlI"
DEFAULT_TOOL = "el_get_lineup_stats"
DEFAULT_ARGUMENTS = {"season": "E2024", "min_possessions": 25, "limit": 50}
TOKEN_VARIABLE = "EL_MCP_TOKEN"
SESSION_HEADER = "Mcp-Session-Id"
PROTOCOL_HEADER = "Mcp-Protocol-Version"


class HostedToolError(RuntimeError):
    """The hosted server returned an MCP tool error rather than structured rows."""


class HostedWorker:
    """One stateful MCP session without an optional persistent GET stream."""

    def __init__(
        self,
        *,
        client: httpx2.AsyncClient,
        endpoint: str,
        session_id: str,
        protocol_version: str,
    ) -> None:
        self._client = client
        self._endpoint = endpoint
        self._headers = {
            SESSION_HEADER: session_id,
            PROTOCOL_HEADER: protocol_version,
        }
        self._request_id = 1

    @classmethod
    async def open(cls, *, endpoint: str, credential: str) -> HostedWorker:
        client = httpx2.AsyncClient(
            headers={
                "Authorization": f"Bearer {credential}",
                "Accept": "application/json, text/event-stream",
            },
            follow_redirects=True,
            timeout=30.0,
        )
        try:
            response = await client.post(
                endpoint,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "r7-load-test", "version": "1.0"},
                    },
                },
            )
            response.raise_for_status()
            reply = parse_sse_jsonrpc(response.text)
            result = reply.get("result")
            session_id = response.headers.get(SESSION_HEADER, "")
            if not isinstance(result, dict) or not session_id:
                raise RuntimeError("MCP initialize response omitted its result or session id.")
            protocol_version = result.get("protocolVersion")
            if not isinstance(protocol_version, str) or not protocol_version:
                raise RuntimeError("MCP initialize response omitted its protocol version.")

            worker = cls(
                client=client,
                endpoint=endpoint,
                session_id=session_id,
                protocol_version=protocol_version,
            )
            initialized = await client.post(
                endpoint,
                headers=worker._headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            initialized.raise_for_status()
            return worker
        except Exception:
            await client.aclose()
            raise

    async def call(self) -> dict[str, Any]:
        self._request_id += 1
        response = await self._client.post(
            self._endpoint,
            headers=self._headers,
            json={
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": "tools/call",
                "params": {"name": DEFAULT_TOOL, "arguments": dict(DEFAULT_ARGUMENTS)},
            },
        )
        response.raise_for_status()
        reply = parse_sse_jsonrpc(response.text)
        if reply.get("id") != self._request_id or "error" in reply:
            raise HostedToolError
        result = reply.get("result")
        if not isinstance(result, dict) or result.get("isError", True):
            raise HostedToolError
        payload = result.get("structuredContent")
        if not isinstance(payload, dict):
            raise HostedToolError
        return payload

    async def close(self) -> None:
        try:
            await self._client.delete(self._endpoint, headers=self._headers)
        finally:
            await self._client.aclose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--client-id", default=DEFAULT_CLIENT_ID)
    parser.add_argument(
        "--levels",
        default=",".join(str(level) for level in DEFAULT_CONCURRENCY_LEVELS),
        help="Increasing comma-separated concurrency levels.",
    )
    parser.add_argument("--waves", type=int, default=DEFAULT_WAVE_COUNT)
    parser.add_argument("--inter-wave-seconds", type=float, default=DEFAULT_INTER_WAVE_SECONDS)
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path for the credential-free full JSON measurement.",
    )
    return parser


def _levels(text: str) -> tuple[int, ...]:
    try:
        levels = tuple(int(part.strip()) for part in text.split(",") if part.strip())
    except ValueError as failure:
        raise ValueError("--levels must be comma-separated integers.") from failure
    if not levels:
        raise ValueError("--levels must name at least one concurrency level.")
    return levels


def _base_server(value: str) -> str:
    server = value.rstrip("/")
    return server[:-4] if server.endswith("/mcp") else server


def _health(server: str) -> dict[str, Any]:
    response = requests.get(f"{server}/healthz", timeout=15)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise RuntimeError("Hosted health check did not return status=ok.")
    return payload


async def _close_workers(workers: list[HostedWorker]) -> None:
    for worker in workers:
        with suppress(Exception):
            await worker.close()


async def _open_workers(endpoint: str, credential: str, count: int) -> list[HostedWorker]:
    workers: list[HostedWorker] = []
    try:
        for index in range(count):
            workers.append(await HostedWorker.open(endpoint=endpoint, credential=credential))
            if (index + 1) % 10 == 0 or index + 1 == count:
                print(f"Prepared {index + 1}/{count} independent MCP sessions.")
        return workers
    except Exception:
        await _close_workers(workers)
        raise


async def _measure(
    *,
    server: str,
    credential: str,
    levels: tuple[int, ...],
    waves: int,
    inter_wave_seconds: float,
) -> dict[str, Any]:
    endpoint = f"{server}/mcp"
    workers = await _open_workers(endpoint, credential, max(levels))
    try:
        calls = [worker.call for worker in workers]
        report = await run_load_suite(
            calls,
            levels=levels,
            wave_count=waves,
            warmup_concurrency=DEFAULT_WARMUP_CONCURRENCY,
            inter_wave_seconds=inter_wave_seconds,
        )
        return report.to_dict()
    finally:
        await _close_workers(workers)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        levels = _levels(args.levels)
        server = _base_server(args.server)
        health = _health(server)
        issuer, resource = discovery(server)

        credential = os.environ.get(TOKEN_VARIABLE, "").strip()
        if not credential:
            credential = obtain_device_token(
                issuer=issuer,
                resource=resource,
                client_id=args.client_id,
            )
            os.environ[TOKEN_VARIABLE] = credential

        if check_hosted_claims([server]) != 0:
            return 1

        measurement = asyncio.run(
            _measure(
                server=server,
                credential=credential,
                levels=levels,
                waves=args.waves,
                inter_wave_seconds=args.inter_wave_seconds,
            )
        )
        result = {
            "observed_at": datetime.now(UTC).isoformat(),
            "server": server,
            "health": health,
            "client_environment": {
                "platform": platform.platform(),
                "python": platform.python_version(),
            },
            "tool": DEFAULT_TOOL,
            "arguments": DEFAULT_ARGUMENTS,
            "concurrency_levels": list(levels),
            "wave_count": args.waves,
            "inter_wave_seconds": args.inter_wave_seconds,
            "measurement": measurement,
        }
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            print(f"Full credential-free result written to {args.output.resolve()}.")

        summary = {
            "observed_at": result["observed_at"],
            "maximum_fully_successful_concurrency": measurement[
                "maximum_fully_successful_concurrency"
            ],
            "total_rows_returned": measurement["total_rows_returned"],
            "levels": measurement["levels"],
        }
        print("HOSTED_LOAD_TEST_SUMMARY=" + json.dumps(summary, separators=(",", ":")))
        return 0
    except (DeviceAuthorizationError, ValueError) as failure:
        print(f"ERROR: {failure}", file=sys.stderr)
        return 2
    except Exception as failure:
        print(
            f"ERROR: hosted measurement stopped with {type(failure).__name__}. "
            "No result was recorded; inspect the server and retry when it is idle.",
            file=sys.stderr,
        )
        return 1
    finally:
        os.environ.pop(TOKEN_VARIABLE, None)


if __name__ == "__main__":
    raise SystemExit(main())
