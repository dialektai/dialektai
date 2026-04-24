"""Sync-to-async bridge for the agent-facing MCP namespace.

Agents run inside Open Interpreter. OI executes Python blocks
synchronously — no ``await``. The async ``MCPRuntime.invoke_tool``
call path, wrapped by ``MCPNamespace.<server>.<tool>(**kwargs)``,
therefore needs a sync-callable shim.

Design

We dispatch from a worker thread (where OI runs) back to the
event loop the MCP manager was created on, via
``asyncio.run_coroutine_threadsafe``. Cross-loop asyncpg-style
issues are avoided because every MCP ``ClientSession`` lives on
the manager's loop and never migrates; the bridge only ferries
the call *back* to that loop.

Shape mirrors ``MCPNamespace`` / ``MCPServerProxy`` from
``runtime.py`` so the ``ctx.mcp`` attribute chain feels identical
to async and sync callers — only the return type differs
(coroutine vs value).

Usage inside a ``ws_chat`` session handler::

    from dialekt.llm._plugin_context import bind_mcp_runtime
    from dialekt.mcp.sync_bridge import create_sync_mcp

    runtime = MCPRuntime(...)                     # async
    adapter = create_sync_mcp(runtime)            # wraps for OI
    token = bind_mcp_runtime(adapter)
    try:
        await asyncio.to_thread(run_agent_sync)   # OI call
    finally:
        bind_mcp_runtime(None) if token is None else bind_mcp_runtime.__self__ # (restore)
        await runtime.shutdown()

Inside ``run_agent_sync`` the agent writes idiomatic Python::

    result = ctx.mcp.github.create_issue(
        repo="dialektai/dialektai", title="…",
    )

``result`` is the actual ``CallToolResult``; ``MCPConsentDenied``
and the other MCP errors bubble as normal exceptions.

See ``docs/MCP_CLIENT_USAGE.md`` for the agent-author view and
``docs/PLUGIN_ARCHITECTURE.md`` for why we use cross-loop
dispatch instead of a fresh portal per call.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from dialekt.mcp.runtime import MCPRuntime


log = logging.getLogger("dialekt.mcp.sync_bridge")


class SyncMCPServerProxy:
    """``ctx.mcp.<server>`` — sync view.

    Attribute access returns a plain sync callable. Calling it
    schedules ``runtime.invoke_tool(server, tool, kwargs)`` on the
    bound loop and blocks until it finishes.
    """

    def __init__(
        self,
        runtime: MCPRuntime,
        loop: asyncio.AbstractEventLoop,
        server_name: str,
    ) -> None:
        self._runtime = runtime
        self._loop = loop
        self._server_name = server_name

    def __getattr__(self, tool_name: str):
        if tool_name.startswith("_"):
            raise AttributeError(tool_name)

        def _sync_call(**kwargs) -> Any:
            coro = self._runtime.invoke_tool(
                self._server_name, tool_name, kwargs or None
            )
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            return future.result()

        _sync_call.__name__ = tool_name
        _sync_call.__qualname__ = f"{self._server_name}.{tool_name}"
        return _sync_call


class SyncMCPNamespace:
    """``ctx.mcp`` when running inside a sync OI block.

    Otherwise equivalent to :class:`dialekt.mcp.runtime.MCPNamespace`
    — same attribute chain, same error taxonomy — but the leaf
    callable returns the ``CallToolResult`` directly instead of a
    coroutine.
    """

    def __init__(
        self,
        runtime: MCPRuntime,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._runtime = runtime
        self._loop = loop

    def __getattr__(self, server_name: str) -> SyncMCPServerProxy:
        if server_name.startswith("_"):
            raise AttributeError(server_name)
        return SyncMCPServerProxy(self._runtime, self._loop, server_name)


class SyncRuntimeAdapter:
    """Runtime-shaped adapter that exposes a sync namespace.

    ``bind_mcp_runtime(adapter)`` + ``ctx.mcp`` hands OI agent code
    a :class:`SyncMCPNamespace`. The adapter forwards ``.shutdown()``
    so the caller can ``await adapter.shutdown()`` at session end.
    """

    def __init__(
        self,
        runtime: MCPRuntime,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._runtime = runtime
        self._loop = loop
        self._namespace = SyncMCPNamespace(runtime, loop)

    @property
    def namespace(self) -> SyncMCPNamespace:
        return self._namespace

    async def shutdown(self) -> None:
        await self._runtime.shutdown()


def create_sync_mcp(runtime: MCPRuntime) -> SyncRuntimeAdapter:
    """Convenience: build a :class:`SyncRuntimeAdapter` bound to the
    currently running event loop.

    Must be called from inside that loop — it uses
    ``asyncio.get_running_loop`` to capture the dispatch target.
    Calling from a purely sync context raises ``RuntimeError``.
    """
    loop = asyncio.get_running_loop()
    return SyncRuntimeAdapter(runtime, loop)
