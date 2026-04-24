"""Tests for the sync-to-async bridge.

These drive a real stdio subprocess through the sync namespace,
with the call originating from a worker thread while the MCPRuntime
lives on the main asyncio loop. This exercises the cross-loop
``run_coroutine_threadsafe`` dispatch that the OI runtime relies on.
"""
import asyncio
import sys
import threading
from pathlib import Path

import pytest

from dialekt.mcp import (
    AutoApproveProvider,
    MCPConsentDenied,
    NoAuth,
    AutoDenyProvider,
)
from dialekt.mcp.manager import MCPClientManager
from dialekt.mcp.runtime import MCPRuntime
from dialekt.mcp.sync_bridge import (
    SyncRuntimeAdapter,
    create_sync_mcp,
)
from dialekt.mcp.transport import StdioTransportSpec


FIXTURE = Path(__file__).parent / "fixtures" / "fastmcp_stdio_echo.py"


def _spawn_transport() -> StdioTransportSpec:
    return StdioTransportSpec(
        command=[sys.executable, "-u", str(FIXTURE)]
    )


def _build_runtime(audit_callback=None, consent_provider=None, autonomy="autonomous"):
    mgr = MCPClientManager(agent_id="sync-bridge", audit_callback=audit_callback)
    return MCPRuntime(
        manager=mgr,
        server_specs={"echo": (_spawn_transport(), NoAuth(), 30.0)},
        consent_provider=consent_provider or AutoApproveProvider(),
        audit_callback=audit_callback,
        autonomy=autonomy,
        agent_id="sync-bridge",
    )


def test_create_sync_mcp_requires_running_loop():
    """Called outside asyncio.run → RuntimeError from get_running_loop."""
    runtime = MCPRuntime(
        manager=MCPClientManager(agent_id="x"),
        server_specs={},
        consent_provider=AutoApproveProvider(),
    )
    with pytest.raises(RuntimeError):
        create_sync_mcp(runtime)


def test_sync_namespace_dispatches_to_owning_loop():
    """Sync call from a worker thread runs on the runtime's loop.

    The subprocess + ClientSession live on the main loop. The sync
    call from a thread must hop back via run_coroutine_threadsafe.
    """
    async def run():
        runtime = _build_runtime()
        adapter = create_sync_mcp(runtime)
        try:
            # Use asyncio.to_thread so the sync call genuinely runs
            # off-loop — faithful to how OI would invoke it.
            result = await asyncio.to_thread(
                lambda: adapter.namespace.echo.add(a=2, b=3)
            )
            assert getattr(result.content[0], "text", None) == "5"
        finally:
            await adapter.shutdown()

    asyncio.run(run())


def test_sync_namespace_propagates_exceptions():
    """Unknown tool raises MCPToolNotFoundError through the bridge."""
    from dialekt.mcp import MCPToolNotFoundError

    async def run():
        runtime = _build_runtime()
        adapter = create_sync_mcp(runtime)
        try:
            with pytest.raises(MCPToolNotFoundError):
                await asyncio.to_thread(
                    lambda: adapter.namespace.echo.nonexistent_tool()
                )
        finally:
            await adapter.shutdown()

    asyncio.run(run())


def test_sync_namespace_surfaces_consent_denial():
    """Denial must raise MCPConsentDenied through the sync path."""
    async def run():
        runtime = _build_runtime(
            consent_provider=AutoDenyProvider(),
            autonomy="manual",  # ask on every tool
        )
        adapter = create_sync_mcp(runtime)
        try:
            with pytest.raises(MCPConsentDenied):
                await asyncio.to_thread(
                    lambda: adapter.namespace.echo.add(a=1, b=2)
                )
        finally:
            await adapter.shutdown()

    asyncio.run(run())


def test_sync_namespace_private_attrs_raise():
    """Dunder/underscore prefixes are never server names."""
    async def run():
        runtime = _build_runtime()
        adapter = create_sync_mcp(runtime)
        try:
            with pytest.raises(AttributeError):
                _ = adapter.namespace._private
            # Same at the server proxy level.
            server = adapter.namespace.echo
            with pytest.raises(AttributeError):
                _ = server._secret
        finally:
            await adapter.shutdown()

    asyncio.run(run())


def test_sync_wrapper_attribute_chain_matches_async_shape():
    """ctx.mcp.<server>.<tool>(**kwargs) is the agent-author contract.

    Verifies the shape: namespace has __getattr__ for server, server
    has __getattr__ for tool, tool is callable. No surprises.
    """
    async def run():
        runtime = _build_runtime()
        adapter = create_sync_mcp(runtime)
        try:
            ns = adapter.namespace
            assert hasattr(ns, "echo")  # resolves via __getattr__
            server = ns.echo
            assert hasattr(server, "add")
            add = server.add
            assert callable(add)
            # Name reflects the tool so error messages are readable.
            assert add.__name__ == "add"
        finally:
            await adapter.shutdown()

    asyncio.run(run())
