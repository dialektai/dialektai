"""MCP server process health registry — v0.26 detect-and-surface only.

Sibling observer of MCPClientManager call outcomes; does NOT replace the
cache. No auto-restart, no polling. Manager's call_tool informs success
/ MCPServerUnavailableError; registry holds latest state in memory and
fires a persist callback to keep mcp_servers.last_test_* in sync.

Design: docs/M2_V026_PROCESS_RESILIENCE_DESIGN.md
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Literal, Optional

log = logging.getLogger(__name__)

HealthStatus = Literal["healthy", "crashed"]
PersistCallback = Callable[[str, HealthStatus, Optional[str]], Awaitable[None]]


@dataclass(frozen=True)
class HealthRow:
    status: HealthStatus
    error: Optional[str]
    since: datetime


class MCPHealthRegistry:
    """Per-process registry. asyncio.Lock serializes write+persist.
    Reads are lock-free dict snapshots. Cooperative single-event-loop;
    thread-pool callers must shim through call_soon_threadsafe.
    """

    def __init__(self, persist_callback: Optional[PersistCallback] = None) -> None:
        self._rows: dict[str, HealthRow] = {}
        self._persist = persist_callback
        self._lock = asyncio.Lock()

    def status(self, server_name: str) -> Optional[HealthRow]:
        return self._rows.get(server_name)

    async def mark_healthy(self, server_name: str) -> None:
        # Reset rule (mentor pass 1 Q4): only clears prior crashed
        # state. Don't overwrite a clean manual [Test] outcome with
        # redundant healthy pings. First-ever healthy is stamped
        # silently (no persist) so the live_status field can show
        # "healthy" without waiting for a crash+recovery.
        async with self._lock:
            prev = self._rows.get(server_name)
            if prev is not None and prev.status == "crashed":
                self._rows[server_name] = HealthRow("healthy", None, _now())
                await self._fire_persist(server_name, "healthy", None)
            elif prev is None:
                self._rows[server_name] = HealthRow("healthy", None, _now())

    async def mark_crashed(self, server_name: str, error_kind: str) -> None:
        # Always wins — re-stamps even if already crashed.
        async with self._lock:
            self._rows[server_name] = HealthRow("crashed", error_kind, _now())
            await self._fire_persist(server_name, "crashed", error_kind)

    async def _fire_persist(self, server_name: str, status: HealthStatus, error: Optional[str]) -> None:
        if self._persist is None:
            return
        try:
            await self._persist(server_name, status, error)
        except Exception:
            log.warning(
                "MCPHealthRegistry: persist_callback raised for %s — swallowing "
                "to keep tool execution path resilient",
                server_name, exc_info=True,
            )


def _now() -> datetime:
    return datetime.now(timezone.utc)
