"""Stdio transport opener for dialekt's MCP client.

Spawns the MCP server as a subprocess and wires its stdin/stdout to
an ``mcp.ClientSession``. Lives in its own module so ``client.py``
stays transport-agnostic — the symmetric ``transport_http.py``
lands in Commit 5.

See ``docs/M2_MCP_DESIGN.md`` Decisions 1 (transport), 5 (subprocess
isolation), and 6 (errors).
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from dialekt.mcp.auth import Credentials, EnvVarsAuth
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


@asynccontextmanager
async def open_stdio_session(
    transport: StdioTransportSpec,
    credentials: Credentials,
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

    Error surfacing is intentionally thin in this commit — SDK
    exceptions (ExecutableNotFound, transport cancellations,
    initialize timeouts) bubble unwrapped. Commit 7 adds the
    ``PluginContext`` wrapper that classifies them into the
    ``MCPServerUnavailableError`` / ``MCPTimeoutError`` /
    ``MCPProtocolError`` taxonomy with audit emission.
    """
    params = StdioServerParameters(
        command=transport.command[0],
        args=list(transport.command[1:]),
        env=_build_subprocess_env(transport.env, credentials),
        cwd=transport.cwd,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session
