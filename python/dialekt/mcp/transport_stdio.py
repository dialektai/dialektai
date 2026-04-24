"""Stdio transport opener for dialekt's MCP client.

Spawns the MCP server as a subprocess and wires its stdin/stdout to
an ``mcp.ClientSession``. Lives in its own module so ``client.py``
stays transport-agnostic — the symmetric ``transport_http.py``
lands in Commit 5.

See ``docs/M2_MCP_DESIGN.md`` Decisions 1 (transport), 5 (subprocess
isolation), and 6 (errors).
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from dialekt.mcp.auth import Credentials, EnvVarsAuth
from dialekt.mcp.errors import MCPTimeoutError
from dialekt.mcp.transport import StdioTransportSpec

if TYPE_CHECKING:
    pass


# Parent env keys that are safe to inherit into the subprocess.
# Anything else the MCP server needs must be declared in the
# manifest's `mcp_servers[].env` or supplied via credentials. This
# is a pragmatic relaxation of Decision 5's "explicit env only" —
# strict inheritance of nothing breaks any server that exec's
# binaries via PATH (npx, uvx, python). Tightening this list is a
# future knob; loosening means loosening across all stdio MCP
# servers, so it stays short.
_ENV_SAFELIST = (
    "PATH",
    "HOME",
    "USER",
    "LANG",
    "LC_ALL",
    "SHELL",
    "TMPDIR",
    "TEMP",
    "TMP",
    "PYTHONHOME",
    "SYSTEMROOT",  # Windows: Python won't start without this.
)


def _build_subprocess_env(
    transport_env: dict[str, str],
    credentials: Credentials,
) -> dict[str, str]:
    """Assemble the subprocess env for a stdio MCP server.

    Merges three sources in precedence order (later wins):
      1. Safelisted slice of ``os.environ`` (PATH, HOME, ...).
      2. Manifest-declared ``mcp_servers[].env``.
      3. ``EnvVarsAuth`` credential values.

    Secrets come last so the credential store has the final say.
    """
    env: dict[str, str] = {}
    for key in _ENV_SAFELIST:
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    env.update(transport_env)
    if isinstance(credentials, EnvVarsAuth):
        env.update(credentials.vars)
    return env


DEFAULT_CONNECT_TIMEOUT_SECONDS = 10.0
"""How long ``session.initialize()`` may take before we give up.

A server that completes TCP / fd setup but never responds to the
initialize JSON-RPC request would otherwise wedge the client forever.
Connect timeout is separate from the per-call ``timeout_seconds``
on the transport spec because handshake latency and per-tool
latency are different order-of-magnitude concerns."""


@asynccontextmanager
async def open_stdio_session(
    transport: StdioTransportSpec,
    credentials: Credentials,
    *,
    connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
) -> AsyncIterator[ClientSession]:
    """Open an initialized ``ClientSession`` over a stdio subprocess.

    Composes two async contexts: the subprocess-managing
    ``mcp.client.stdio.stdio_client`` and the JSON-RPC
    ``mcp.ClientSession`` on top. Yields the ``ClientSession`` after
    ``initialize()`` completes.

    Subprocess args split: ``transport.command`` is a full argv list
    (``["npx", "-y", "@mcp/foo"]``) but ``StdioServerParameters``
    wants the binary and the args separately, so we split at
    index 0.

    ``initialize()`` is wrapped in ``asyncio.timeout`` so an MCP
    server that hangs mid-handshake surfaces as
    :class:`MCPTimeoutError` rather than hanging the chat turn.
    Default 10s; callers can tighten or loosen via
    ``connect_timeout_seconds``.

    Non-handshake errors bubble unwrapped at this layer — the
    ``MCPClientManager`` (Commit 7) classifies them into the
    ``MCPServerUnavailableError`` / ``MCPProtocolError`` taxonomy
    with audit emission on behalf of the caller.
    """
    params = StdioServerParameters(
        command=transport.command[0],
        args=list(transport.command[1:]),
        env=_build_subprocess_env(transport.env, credentials),
        cwd=transport.cwd,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            try:
                async with asyncio.timeout(connect_timeout_seconds):
                    await session.initialize()
            except asyncio.TimeoutError as exc:
                raise MCPTimeoutError(
                    f"stdio MCP server handshake (initialize) timed out "
                    f"after {connect_timeout_seconds}s — server accepted "
                    f"the subprocess pipes but never responded"
                ) from exc
            yield session
