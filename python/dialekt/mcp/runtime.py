"""Agent-facing runtime for MCP tool invocation.

MCPClientManager (Commit 7) handles transport + rate limit + audit.
This module sits on top and adds consent policy: destructive-tool
detection, prompting the user when autonomy requires it, and the
audit trail linking consent decisions back to the tool call they
authorized.

Shape:

    runtime = MCPRuntime(
        manager=manager,
        server_specs={"github": (transport, credentials, timeout)},
        consent_provider=provider,
        tool_metadata_fetcher=fetch,
        audit_callback=cb,
        agent_id="…",
        binding_id="…",
    )

Agents reach it through ``ctx.mcp`` which resolves (via a ContextVar)
to ``runtime.namespace``::

    result = await ctx.mcp.github.create_issue(repo="foo", title="…")

Agents consuming the namespace synchronously (OI Python blocks) need
the sync-to-async bridge at the call site; that bridge is a thin
wrapper over anyio portals and is out of scope for Commit 9 — tests
drive ``invoke_tool`` directly at the async level.

See ``docs/M2_MCP_DESIGN.md`` Decisions 4, 5, 7.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable, Optional

from dialekt.mcp.auth import Credentials, NoAuth
from dialekt.mcp.consent import (
    ConsentDecision,
    ConsentProvider,
    ConsentRequest,
    is_destructive_tool,
)
from dataclasses import dataclass, field
from dialekt.mcp.errors import (
    MCPConfigError,
    MCPConsentDenied,
    MCPToolNotAllowed,
    MCPToolNotFoundError,
)
from dialekt.mcp.manager import AuditCallback, MCPClientManager
from dialekt.mcp.transport import TransportSpec


@dataclass(frozen=True)
class ToolPolicy:
    """Static per-server allow/deny policy for tool dispatch.

    Built from the manifest's ``mcp_servers[].allow_tools`` and
    ``mcp_servers[].deny_tools`` fields by ws_chat at session start
    and threaded into ``MCPRuntime`` via ``tool_policies``.

    Semantics (per v0.22 design + mentor ruling §10.A):
        - ``allow is None`` → all tools advertised by the server allowed.
        - ``allow is not None`` → ONLY those tool names allowed.
        - ``deny`` is always subtracted: a tool name in both lists is
          denied (deny wins). This matches POSIX firewall conventions
          and lets admins say "allow the github_* family but blacklist
          github_delete_branch".
    """

    allow: Optional[frozenset[str]] = None
    deny: frozenset[str] = field(default_factory=frozenset)

    def permits(self, tool_name: str) -> bool:
        """Return True iff ``tool_name`` is dispatch-allowed under this
        policy. False means the runtime must raise
        :class:`MCPToolNotAllowed` and never reach consent or dispatch.
        """
        if tool_name in self.deny:
            return False
        if self.allow is not None and tool_name not in self.allow:
            return False
        return True


log = logging.getLogger("dialekt.mcp.runtime")


# A server spec bundles what ``invoke_tool`` needs to actually dispatch:
# transport + credentials + per-call timeout.
ServerSpec = tuple[TransportSpec, Credentials, float]

# Fetches the tool catalog for a server. Called lazily on first use
# and cached on the runtime. The signature matches
# ``MCPClientManager.get_client(...).list_tools()`` after unwrapping.
ToolMetadataFetcher = Callable[[str], Awaitable[list[Any]]]


# Autonomy levels under which EVERY tool call (not just destructive)
# requires consent.
_ASK_EVERYTHING_AUTONOMY = frozenset({"manual"})

# Autonomy levels where destructive tools are refused outright — no
# prompt, immediate MCPConsentDenied.
_BLOCK_DESTRUCTIVE_AUTONOMY = frozenset({"review-only"})


class MCPRuntime:
    """Session-scoped MCP orchestration.

    One instance per agent chat session. Owns:
      - reference to the :class:`MCPClientManager`
      - the consent provider (policy)
      - the tool-metadata cache (per server)
      - the audit callback (same sink the manager uses)
      - the autonomy level (for the manual/review-only exits)
      - server-spec lookup ({server_name: (transport, credentials, timeout)})

    Lifecycle is owned by the caller (ws_chat session handler):
    construct at session start, ``await runtime.shutdown()`` at
    disconnect. Does not register itself with PluginContext.
    """

    def __init__(
        self,
        *,
        manager: MCPClientManager,
        server_specs: dict[str, ServerSpec],
        consent_provider: ConsentProvider,
        audit_callback: Optional[AuditCallback] = None,
        autonomy: str = "ask-before-write",
        agent_id: str = "",
        binding_id: Optional[str] = None,
        clock: Callable[[], float] = time.monotonic,
        tool_policies: Optional[dict[str, ToolPolicy]] = None,
    ) -> None:
        self._manager = manager
        self._server_specs = dict(server_specs)
        self._consent_provider = consent_provider
        self._audit_callback = audit_callback
        self._autonomy = autonomy
        self._agent_id = agent_id
        self._binding_id = binding_id
        self._clock = clock
        # Per-server tool allow/deny policies. Empty dict / None → no
        # policy → all tools dispatch through consent + manager
        # normally (v0.20/v0.21 backwards-compat).
        self._tool_policies: dict[str, ToolPolicy] = dict(tool_policies or {})

        self._tool_cache: dict[str, dict[str, Any]] = {}
        self._shutdown = False

    # ── Tool metadata ────────────────────────────────────────────────────

    async def tool_metadata(self, server_name: str, tool_name: str) -> Any:
        """Return the cached tool metadata for a (server, tool) pair.

        Fetches + caches the full catalog on first access per server.
        Raises :class:`MCPToolNotFoundError` if the server doesn't
        advertise that tool — matches the Decision 6 taxonomy so
        callers always see an MCPError.
        """
        catalog = self._tool_cache.get(server_name)
        if catalog is None:
            spec = self._server_specs.get(server_name)
            if spec is None:
                raise MCPConfigError(
                    f"MCP server {server_name!r} not configured on runtime"
                )
            transport, credentials, _timeout = spec
            client = await self._manager.get_client(
                server_name, transport, credentials
            )
            result = await client.list_tools()
            catalog = {t.name: t for t in result.tools}
            self._tool_cache[server_name] = catalog

        tool = catalog.get(tool_name)
        if tool is None:
            raise MCPToolNotFoundError(
                f"MCP server {server_name!r} does not advertise tool "
                f"{tool_name!r}. Available: {sorted(catalog)}"
            )
        return tool

    # ── Agent-facing namespace ──────────────────────────────────────────

    @property
    def namespace(self) -> "MCPNamespace":
        """``ctx.mcp`` resolves to this.

        Agents then write ``ctx.mcp.<server>.<tool>(**kwargs)`` which
        returns a coroutine. Sync-from-OI bridging happens a layer up
        (PluginContext's portal).
        """
        return MCPNamespace(self)

    # ── Core invocation path ────────────────────────────────────────────

    async def invoke_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: Optional[dict[str, Any]] = None,
    ) -> Any:
        """The full consent-gated MCP tool call.

        1. Resolve the server spec; error if unknown.
        2. Fetch/cached tool metadata.
        3. Determine if consent is needed (destructive + autonomy).
        4. If needed, prompt consent; audit the request and the decision.
        5. If denied, raise :class:`MCPConsentDenied`; audit records
           "denied" without an error_kind (denial is not an error).
        6. If approved, call ``MCPClientManager.call_tool`` with
           ``extra={'consent_id': <decision row id>}`` so the audit
           entries can be joined.
        """
        if self._shutdown:
            raise RuntimeError("MCPRuntime has been shut down")

        spec = self._server_specs.get(server_name)
        if spec is None:
            raise MCPConfigError(
                f"MCP server {server_name!r} not configured on runtime"
            )
        transport, credentials, timeout_seconds = spec

        # Per-tool allow/deny gate (v0.22). Fast-fails before tool
        # metadata fetch so a denied call never spawns the MCP server
        # subprocess. Counts the attempt toward the manager's 60/min
        # rate limit so a runaway agent looping on a blocked tool
        # hits MCPRateLimitError at the ceiling and stops emitting
        # mcp_tool_blocked rows.
        policy = self._tool_policies.get(server_name)
        if policy is not None and not policy.permits(tool_name):
            self._manager._check_rate_limit()
            reason = (
                "denied by deny_tools" if tool_name in policy.deny
                else "not in allow_tools"
            )
            await self._emit_audit(
                kind="mcp_tool_blocked",
                action=tool_name,
                result="blocked",
                target=server_name,
                error_kind="MCPToolNotAllowed",
                extra={"reason": reason},
            )
            raise MCPToolNotAllowed(
                f"{server_name}.{tool_name}: {reason}"
            )

        tool = await self.tool_metadata(server_name, tool_name)
        destructive, source = is_destructive_tool(tool)

        must_ask = (
            self._autonomy in _ASK_EVERYTHING_AUTONOMY
            or (destructive and self._autonomy not in _NO_ASK_AUTONOMY)
        )
        auto_deny = destructive and self._autonomy in _BLOCK_DESTRUCTIVE_AUTONOMY

        consent_id: Optional[int] = None
        if must_ask or auto_deny:
            request = ConsentRequest(
                server_name=server_name,
                tool_name=tool_name,
                arguments=dict(arguments or {}),
                destructive=destructive,
                destructive_source=source,
            )
            decision, consent_id = await self._ask_and_audit(
                request, auto_deny=auto_deny
            )
            if decision is ConsentDecision.DENIED:
                raise MCPConsentDenied(
                    f"User denied {server_name}.{tool_name}"
                )

        extra: dict[str, Any] = {}
        if consent_id is not None:
            extra["consent_id"] = consent_id

        return await self._manager.call_tool(
            server_name,
            tool_name,
            arguments,
            transport=transport,
            credentials=credentials,
            timeout_seconds=timeout_seconds,
            binding_id=self._binding_id,
            extra=extra or None,
        )

    # ── Consent audit plumbing ──────────────────────────────────────────

    async def _ask_and_audit(
        self,
        request: ConsentRequest,
        *,
        auto_deny: bool,
    ) -> tuple[ConsentDecision, Optional[int]]:
        """Emit ``mcp_consent_requested``, prompt the provider, emit
        ``mcp_consent_decision``. Returns ``(decision, decision_row_id)``
        where ``decision_row_id`` is the id of the decision audit row
        (or ``None`` if audit was skipped)."""
        await self._emit_audit(
            kind="mcp_consent_requested",
            action=request.tool_name,
            result="asked",
            target=request.server_name,
            extra=request.to_dict(),
        )

        start = self._clock()
        if auto_deny:
            decision = ConsentDecision.DENIED
        else:
            try:
                decision = await self._consent_provider.request_consent(request)
            except BaseException:
                log.warning("consent provider raised — defaulting to DENIED", exc_info=True)
                decision = ConsentDecision.DENIED

        decision_row_id = await self._emit_audit(
            kind="mcp_consent_decision",
            action=request.tool_name,
            result=decision.value,
            target=request.server_name,
            duration_ms=int((self._clock() - start) * 1000),
            extra={
                "destructive": request.destructive,
                "destructive_source": request.destructive_source,
            },
        )
        return decision, decision_row_id

    async def _emit_audit(
        self,
        *,
        kind: str,
        action: str,
        result: str,
        target: Optional[str] = None,
        duration_ms: Optional[int] = None,
        error_kind: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> Optional[int]:
        """Send a single audit row; return the server-assigned row id
        if the callback provides one. Returns ``None`` on failure so
        audit issues never prevent an agent from functioning."""
        if self._audit_callback is None:
            return None
        payload = {
            "kind": kind,
            "action": action,
            "result": result,
            "agent_id": self._agent_id,
            "binding_id": self._binding_id,
            "target": target,
            "duration_ms": duration_ms,
            "error_kind": error_kind,
            "extra": extra,
        }
        try:
            import asyncio

            if asyncio.iscoroutinefunction(self._audit_callback):
                retval = await self._audit_callback(**payload)
            else:
                retval = await asyncio.to_thread(
                    self._audit_callback, **payload
                )
        except Exception:
            log.warning("MCPRuntime audit callback failed", exc_info=True)
            return None

        # The callback may return the audit row (``{"id": ...}``) or
        # an httpx.Response whose .json() does. Tolerate both shapes
        # + plain None / ints.
        return _extract_row_id(retval)

    # ── Lifecycle ───────────────────────────────────────────────────────

    async def shutdown(self) -> None:
        """Close the underlying manager and clear caches.

        Idempotent. After shutdown every call path raises.
        """
        if self._shutdown:
            return
        self._shutdown = True
        self._tool_cache.clear()
        await self._manager.shutdown()


# Autonomy levels that DON'T need consent for destructive tools.
_NO_ASK_AUTONOMY = frozenset({"autonomous"})


def _extract_row_id(retval: Any) -> Optional[int]:
    """Best-effort: pluck the inserted row id from a callback return value.

    The ``POST /audit/log`` endpoint returns ``{"id": <int>}``. httpx
    Response objects carry that under ``.json()``. Tests can return a
    bare int. Everything else (None, unexpected shape) → None.
    """
    if retval is None:
        return None
    if isinstance(retval, int):
        return retval
    if isinstance(retval, dict):
        val = retval.get("id")
        return int(val) if isinstance(val, int) else None
    # Duck-typed httpx.Response.
    json_method = getattr(retval, "json", None)
    if callable(json_method):
        try:
            body = json_method()
        except Exception:
            return None
        if isinstance(body, dict):
            val = body.get("id")
            return int(val) if isinstance(val, int) else None
    return None


# ── Namespace proxy ──────────────────────────────────────────────────────────


class MCPNamespace:
    """``ctx.mcp`` — first-level proxy.

    ``ctx.mcp.github`` returns a :class:`MCPServerProxy` bound to the
    ``"github"`` server. The server name is not validated here;
    downstream ``invoke_tool`` raises :class:`MCPConfigError` if the
    server isn't configured.
    """

    def __init__(self, runtime: MCPRuntime) -> None:
        self._runtime = runtime

    def __getattr__(self, server_name: str) -> "MCPServerProxy":
        # Private attributes bypass the proxy.
        if server_name.startswith("_"):
            raise AttributeError(server_name)
        return MCPServerProxy(self._runtime, server_name)


class MCPServerProxy:
    """``ctx.mcp.github`` — second-level proxy.

    ``ctx.mcp.github.create_issue`` returns an async callable. Calling
    it schedules ``runtime.invoke_tool("github", "create_issue", {...})``
    and returns the awaitable.
    """

    def __init__(self, runtime: MCPRuntime, server_name: str) -> None:
        self._runtime = runtime
        self._server_name = server_name

    def __getattr__(self, tool_name: str):
        if tool_name.startswith("_"):
            raise AttributeError(tool_name)

        async def _invoke(**kwargs):
            return await self._runtime.invoke_tool(
                self._server_name, tool_name, kwargs or None
            )

        _invoke.__name__ = tool_name
        return _invoke
