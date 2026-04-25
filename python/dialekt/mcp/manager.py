"""Per-agent lifecycle and call-path wrapper for MCPClients.

MCPClientManager is where Decisions 4 (runtime integration), 5
(security: rate limit + timeout), 6 (error taxonomy), and 7 (audit
emission) converge. Agents do not touch MCPClient directly — they
hold a manager (one per agent) and call ``call_tool`` on it.

Responsibilities:

- **Lazy connection.** A client for a given ``server_name`` is
  opened on first use and cached until ``shutdown()``. Subsequent
  ``call_tool``s reuse the open ``ClientSession``.
- **Rate limiting.** A rolling 60-second window per manager bounds
  the total tool-call count across every connected server. Default
  60/min, configurable. Breach raises :class:`MCPRateLimitError`;
  the rolling window trims automatically on the next call.
- **Per-call timeout.** The ``timeout_seconds`` from the caller's
  spec is enforced with ``asyncio.timeout``. Timeout raises
  :class:`MCPTimeoutError`.
- **Error classification.** Anything the SDK or anyio raises gets
  routed through :func:`classify_sdk_error` into the dialekt
  taxonomy. Callers always see ``MCPError`` subclasses.
- **Audit emission.** Every call — success, tool-level error,
  transport failure, timeout, rate limit — emits one audit row via
  the injected ``audit_callback``. The callback runs in a worker
  thread so a slow audit sink does not block the call path.

See ``docs/M2_MCP_DESIGN.md``.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Optional

from dialekt.mcp.auth import Credentials, NoAuth
from dialekt.mcp.client import MCPClient
from dialekt.mcp.error_classify import classify_sdk_error
from dialekt.mcp.health import MCPHealthRegistry
from dialekt.mcp.errors import (
    MCPError,
    MCPRateLimitError,
    MCPServerUnavailableError,
    MCPTimeoutError,
)
from dialekt.mcp.transport import TransportSpec


log = logging.getLogger("dialekt.mcp.manager")


AuditCallback = Callable[..., Any]
"""Shape of the audit sink the manager calls after every tool invocation.

Signature matches dialekt.audit.log.log_event keyword arguments:
``kind, action, result, agent_id, binding_id, target, duration_ms,
error_kind, extra`` — all optional except kind/action/result. The
callback may be sync or async; the manager dispatches it via
``asyncio.to_thread`` to tolerate either.
"""


DEFAULT_RATE_LIMIT_PER_MINUTE = 60


class MCPClientManager:
    """One manager per agent session. Not thread-safe — a manager
    belongs to exactly one asyncio event loop."""

    def __init__(
        self,
        agent_id: str,
        *,
        audit_callback: Optional[AuditCallback] = None,
        rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE,
        clock: Callable[[], float] = time.monotonic,
        health_registry: Optional["MCPHealthRegistry"] = None,
    ) -> None:
        self.agent_id = agent_id
        self._audit_callback = audit_callback
        self._rate_limit = rate_limit_per_minute
        self._clock = clock
        self._health = health_registry

        self._clients: dict[str, MCPClient] = {}
        self._specs: dict[str, tuple[TransportSpec, Credentials]] = {}
        self._rate_window: list[float] = []
        self._shutdown = False

    # ── Client lifecycle ─────────────────────────────────────────────────

    async def get_client(
        self,
        server_name: str,
        transport: TransportSpec,
        credentials: Credentials | None = None,
    ) -> MCPClient:
        """Open (if needed) and return the cached MCPClient for this
        server. Subsequent calls with the same ``server_name`` reuse
        the open client; the transport + credentials are checked-in
        once and not re-read."""
        if self._shutdown:
            raise RuntimeError("MCPClientManager has been shut down")
        if server_name in self._clients:
            return self._clients[server_name]

        creds = credentials or NoAuth()
        self._specs[server_name] = (transport, creds)
        client = MCPClient(transport=transport, credentials=creds)
        await client.__aenter__()
        self._clients[server_name] = client
        return client

    async def shutdown(self) -> None:
        """Close every open client. Idempotent; safe to call twice."""
        if self._shutdown:
            return
        self._shutdown = True
        for name, client in list(self._clients.items()):
            try:
                await client.__aexit__(None, None, None)
            except Exception:
                log.warning(
                    "MCPClientManager: error closing client for %s",
                    name,
                    exc_info=True,
                )
        self._clients.clear()

    # ── Call path ────────────────────────────────────────────────────────

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        transport: TransportSpec,
        credentials: Credentials | None = None,
        timeout_seconds: float = 30.0,
        binding_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Any:
        """Invoke an MCP tool with rate limit, timeout, audit, and
        classified errors. Returns the raw ``CallToolResult`` from
        the SDK so callers can inspect ``.content`` / ``.isError``.

        ``extra`` is an opaque JSON-serializable dict merged into the
        audit row. The runtime layer uses it to inject
        ``consent_id`` — the audit row id of the consent decision
        that authorized this call — so audit rows can be joined back
        to their consent event in SQL queries.
        """
        self._check_rate_limit()

        start = self._clock()
        result_kind = "success"
        error_kind: str | None = None
        exception_to_raise: BaseException | None = None
        result: Any = None

        try:
            client = await self.get_client(server_name, transport, credentials)
            async with asyncio.timeout(timeout_seconds):
                result = await client.call_tool(tool_name, arguments or {})
            if getattr(result, "isError", False):
                result_kind = "error"
                error_kind = "MCPToolError"  # server-reported, not ours
        except MCPRateLimitError:
            # Already audited by _check_rate_limit; re-raise.
            raise
        except asyncio.TimeoutError as e:
            result_kind = "timeout"
            error_kind = "MCPTimeoutError"
            exception_to_raise = MCPTimeoutError(
                f"{server_name}.{tool_name} timed out after "
                f"{timeout_seconds}s"
            )
            exception_to_raise.__cause__ = e
        except BaseException as e:
            classified = classify_sdk_error(e)
            result_kind = (
                "server_unavailable"
                if isinstance(classified, MCPServerUnavailableError)
                else "error"
            )
            error_kind = type(classified).__name__
            exception_to_raise = classified
            exception_to_raise.__cause__ = e

        duration_ms = int((self._clock() - start) * 1000)
        await self._emit_audit(
            kind="mcp_tool_call",
            action=tool_name,
            result=result_kind,
            target=server_name,
            binding_id=binding_id,
            duration_ms=duration_ms,
            error_kind=error_kind,
            extra=extra,
        )

        # v0.26 process-health observer (sibling registry, never raises
        # — _fire_persist swallows callback failures internally).
        if self._health is not None:
            if result_kind == "server_unavailable":
                await self._health.mark_crashed(server_name, error_kind or "unknown")
            elif result_kind == "success":
                await self._health.mark_healthy(server_name)

        if exception_to_raise is not None:
            raise exception_to_raise
        return result

    # ── Rate limiter ─────────────────────────────────────────────────────

    def _check_rate_limit(self) -> None:
        now = self._clock()
        cutoff = now - 60.0
        # Prune older entries.
        self._rate_window = [ts for ts in self._rate_window if ts > cutoff]
        if len(self._rate_window) >= self._rate_limit:
            # Record the audit event for the rate-limit breach so the
            # user can see it in audit history. Fire-and-forget —
            # guarded because the method can also be invoked from a
            # sync test harness without a running loop; in that case
            # the breach itself still raises, just without the audit
            # side-effect.
            try:
                asyncio.get_running_loop().create_task(
                    self._emit_audit(
                        kind="mcp_tool_call",
                        action="<rate-limited>",
                        result="rate_limited",
                        error_kind="MCPRateLimitError",
                    )
                )
            except RuntimeError:
                pass
            raise MCPRateLimitError(
                f"MCP rate limit {self._rate_limit}/min exceeded for agent "
                f"{self.agent_id!r}"
            )
        self._rate_window.append(now)

    # ── Audit ────────────────────────────────────────────────────────────

    async def _emit_audit(
        self,
        *,
        kind: str,
        action: str,
        result: str,
        target: str | None = None,
        binding_id: str | None = None,
        duration_ms: int | None = None,
        error_kind: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Push one audit row to the injected callback. Never raises —
        a failing audit sink must not take down a tool call."""
        if self._audit_callback is None:
            return
        payload = {
            "kind": kind,
            "action": action,
            "result": result,
            "agent_id": self.agent_id,
            "binding_id": binding_id,
            "target": target,
            "duration_ms": duration_ms,
            "error_kind": error_kind,
            "extra": extra,
        }
        try:
            if asyncio.iscoroutinefunction(self._audit_callback):
                await self._audit_callback(**payload)
            else:
                # Dispatch sync callbacks through a worker so a slow
                # HTTP round-trip to /audit/log doesn't block the
                # calling task's event loop.
                await asyncio.to_thread(self._audit_callback, **payload)
        except Exception:
            log.warning("MCPClientManager audit callback failed", exc_info=True)
