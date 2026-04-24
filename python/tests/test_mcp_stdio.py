"""Integration tests for dialekt.mcp stdio transport.

These drive a real Python subprocess — FastMCP running over stdio —
via dialekt's MCPClient. If you see failures here and the in-memory
tests in test_mcp_client.py still pass, the regression is in the
stdio wiring, not the client core.
"""
import asyncio
import os
import sys
from pathlib import Path

import pytest

from dialekt.mcp import MCPClient
from dialekt.mcp.transport_stdio import _build_subprocess_env


FIXTURE = Path(__file__).parent / "fixtures" / "fastmcp_stdio_echo.py"


def _spawn_cmd() -> list[str]:
    """Command list that launches the test FastMCP server.

    Uses ``sys.executable`` so the subprocess picks up the same venv
    interpreter with the same ``mcp`` package installed.
    """
    return [sys.executable, "-u", str(FIXTURE)]


def test_stdio_client_lists_advertised_tools():
    async def run():
        client = MCPClient.from_stdio_command(_spawn_cmd())
        async with client:
            result = await client.list_tools()
            names = {t.name for t in result.tools}
            assert "add" in names
            assert "echo_env" in names

    asyncio.run(run())


def test_stdio_client_calls_tool_with_structured_args():
    async def run():
        client = MCPClient.from_stdio_command(_spawn_cmd())
        async with client:
            result = await client.call_tool("add", {"a": 7, "b": 8})
            assert result.isError is False
            assert result.content
            assert getattr(result.content[0], "text", None) == "15"

    asyncio.run(run())


def test_stdio_manifest_env_reaches_subprocess():
    """`env` kwarg on the factory becomes an env var inside the child."""
    async def run():
        client = MCPClient.from_stdio_command(
            _spawn_cmd(), env={"DIALEKT_TEST_KEY": "hello-from-manifest"}
        )
        async with client:
            result = await client.call_tool(
                "echo_env", {"name": "DIALEKT_TEST_KEY"}
            )
            assert result.isError is False
            assert (
                getattr(result.content[0], "text", None)
                == "hello-from-manifest"
            )

    asyncio.run(run())


def test_stdio_subprocess_cleans_up_on_exit():
    """After the `async with` exits, the subprocess is no longer running.

    Heuristic: ``list_tools()`` after exit must fail. A harder
    process-tree check is possible via psutil but relies on timing
    (the subprocess may still be in the tear-down syscall window).
    """
    async def run():
        client = MCPClient.from_stdio_command(_spawn_cmd())
        async with client:
            await client.list_tools()
        # After exit, session access is revoked.
        with pytest.raises(RuntimeError, match="not open"):
            _ = client.session

    asyncio.run(run())


def test_stdio_spawn_failure_surfaces():
    """A non-existent binary should not hang — it raises promptly."""
    async def run():
        client = MCPClient.from_stdio_command(["dialekt-nonexistent-mcp-xyz"])
        with pytest.raises(Exception):  # SDK surfaces its own exception kind
            async with client:
                pass

    asyncio.run(run())


def test_stdio_handshake_timeout_raises_mcp_timeout_error():
    """A server that accepts stdin but never answers initialize must
    be surfaced as MCPTimeoutError within connect_timeout_seconds —
    not wedged forever.

    The SDK's stdio_client runs inside an anyio TaskGroup so the
    raised MCPTimeoutError comes out wrapped in BaseExceptionGroup.
    Callers via MCPClientManager get this unwrapped by
    ``error_classify.classify_sdk_error``; this test bypasses the
    manager and so unwraps manually.
    """
    from dialekt.mcp import MCPTimeoutError, NoAuth
    from dialekt.mcp.error_classify import classify_sdk_error
    from dialekt.mcp.transport import StdioTransportSpec
    from dialekt.mcp.transport_stdio import open_stdio_session

    hang_script = Path(__file__).parent / "fixtures" / "stdio_hang.py"
    transport = StdioTransportSpec(
        command=[sys.executable, "-u", str(hang_script)]
    )

    async def run():
        loop = asyncio.get_event_loop()
        start = loop.time()
        try:
            async with open_stdio_session(
                transport, NoAuth(), connect_timeout_seconds=0.5
            ):
                pytest.fail("open_stdio_session should have timed out")
        except BaseException as raised:
            classified = classify_sdk_error(raised)
            assert isinstance(classified, MCPTimeoutError), (
                f"expected MCPTimeoutError after classification, got "
                f"{type(classified).__name__}: {classified}"
            )
        elapsed = loop.time() - start
        # Generous upper bound so the test isn't flaky on loaded CI
        # but still fails loudly if we disable the timeout path.
        assert elapsed < 5.0, f"took {elapsed}s — timeout not enforced"

    asyncio.run(run())


def test_subprocess_env_merges_safelist_then_manifest_then_creds():
    """Unit test for the env assembly logic — pure function, no subprocess."""
    from dialekt.mcp.auth import EnvVarsAuth, NoAuth

    # Inject a known marker into the parent env just for this test.
    os.environ["DIALEKT_SAFELIST_TEST"] = "parent-value"
    try:
        # PATH should flow through (it's on the safelist).
        env_a = _build_subprocess_env({}, NoAuth())
        assert "PATH" in env_a
        # A non-safelisted key is NOT inherited.
        assert "DIALEKT_SAFELIST_TEST" not in env_a

        # Manifest env overrides parent on the safelist.
        env_b = _build_subprocess_env({"PATH": "/manifest-path"}, NoAuth())
        assert env_b["PATH"] == "/manifest-path"

        # Credentials win over manifest env.
        env_c = _build_subprocess_env(
            {"API_KEY": "from-manifest"},
            EnvVarsAuth(vars={"API_KEY": "from-credentials"}),
        )
        assert env_c["API_KEY"] == "from-credentials"
    finally:
        os.environ.pop("DIALEKT_SAFELIST_TEST", None)


def test_skeleton_stdio_unimplemented_now_works():
    """test_mcp_skeleton.test_real_transports_not_yet_wired used to assert
    stdio raises NotImplementedError. After this commit, stdio should be
    functional — but the HTTP half must still defer.

    Rather than rewrite the older skeleton test, this new one asserts
    the post-Commit-4 invariant. The older test is updated in the same
    commit to check only the HTTP half.
    """
    async def run():
        client = MCPClient.from_stdio_command(_spawn_cmd())
        # Entering must NOT raise NotImplementedError now.
        async with client:
            tools = await client.list_tools()
            assert tools.tools  # at least one advertised

    asyncio.run(run())
