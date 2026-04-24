"""Tests for dialekt.mcp Streamable HTTP transport.

Pure-unit tests exercise the request-header assembly. The
integration tests spawn a FastMCP server over real HTTP on a
random local port and hit it through dialekt's MCPClient. This
mirrors how production will use the transport — real TCP, real
streaming HTTP — without assuming a particular remote MCP server
is reachable.
"""
import asyncio
import socket
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

import pytest

from dialekt.mcp import MCPClient
from dialekt.mcp.auth import BearerAuth, EnvVarsAuth, NoAuth
from dialekt.mcp.transport_http import _build_request_headers


FIXTURE = Path(__file__).parent / "fixtures" / "fastmcp_http_echo.py"


# ---------------------------------------------------------------------------
# Unit tests for header assembly.
# ---------------------------------------------------------------------------


def test_build_request_headers_no_auth():
    assert _build_request_headers(NoAuth()) == {}


def test_build_request_headers_bearer():
    headers = _build_request_headers(BearerAuth(token="sekret"))
    assert headers == {"Authorization": "Bearer sekret"}


def test_build_request_headers_env_vars_auth_ignored():
    """EnvVarsAuth is a stdio-only shape; an HTTP transport that
    somehow carries one should not leak it into headers."""
    headers = _build_request_headers(EnvVarsAuth(vars={"SECRET": "x"}))
    assert headers == {}


# ---------------------------------------------------------------------------
# Subprocess integration helper.
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    """Ask the OS for a free TCP port. Close immediately; race OK in tests."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 5.0) -> None:
    """Block until a TCP connect to 127.0.0.1:<port> succeeds."""
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError as e:
            last_err = e
            time.sleep(0.05)
    raise TimeoutError(f"port {port} never became ready: {last_err!r}")


class _FastMCPHttpSubprocess:
    """Context manager that spawns fastmcp_http_echo.py on a random port."""

    def __init__(self) -> None:
        self.port = _find_free_port()
        self.url = f"http://127.0.0.1:{self.port}/mcp"
        self._proc: subprocess.Popen | None = None

    def __enter__(self) -> "_FastMCPHttpSubprocess":
        self._proc = subprocess.Popen(
            [sys.executable, "-u", str(FIXTURE), str(self.port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            _wait_for_port(self.port, timeout=10.0)
        except Exception:
            self._teardown()
            raise
        return self

    def __exit__(self, *exc) -> None:
        self._teardown()

    def _teardown(self) -> None:
        if self._proc is None:
            return
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=1.0)


# ---------------------------------------------------------------------------
# Integration tests — real HTTP through random-port subprocess.
# ---------------------------------------------------------------------------


def test_http_list_tools_over_real_port():
    async def run(url: str):
        client = MCPClient.from_http_url(url)
        async with client:
            result = await client.list_tools()
            names = {t.name for t in result.tools}
            assert "add" in names
            assert "echo" in names

    with _FastMCPHttpSubprocess() as srv:
        asyncio.run(run(srv.url))


def test_http_call_tool_over_real_port():
    async def run(url: str):
        client = MCPClient.from_http_url(url)
        async with client:
            result = await client.call_tool("add", {"a": 11, "b": 4})
            assert result.isError is False
            assert getattr(result.content[0], "text", None) == "15"

    with _FastMCPHttpSubprocess() as srv:
        asyncio.run(run(srv.url))


def test_http_from_http_url_no_longer_raises_not_implemented():
    """Regression guard for Commit 5 — the dispatcher must route
    HttpTransportSpec into the real opener, not NotImplementedError.
    We point at an unreachable port so the test itself is fast; any
    exception besides NotImplementedError is acceptable."""
    async def run():
        client = MCPClient.from_http_url("http://127.0.0.1:1/mcp")
        try:
            async with client:
                pass
        except NotImplementedError:
            pytest.fail(
                "HTTP dispatcher still raises NotImplementedError — "
                "Commit 5 regression"
            )
        except Exception:
            # Any other exception means we reached the network layer.
            pass

    asyncio.run(run())
