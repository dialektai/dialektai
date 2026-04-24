"""Tool implementations for the dialekt MCP server.

One module per category from docs/M2_MCP_SERVER_DESIGN.md Decision 1:

- ``database`` — 5 tools over dialekt's configured DB connections
- ``file`` — 2 tools under ``allowed_file_roots``
- ``agent`` — 2 tools (list + get; invoke deferred to M3)

Each module exposes a ``register_*`` function that takes the
:class:`MCPServer` and a ``PluginContext`` (the HTTP client pointing at
dialekt's local backend) and attaches ``@srv.fastmcp.tool()``-decorated
callables. The server's ``register_tools`` dispatches to these.

The common wrapping (rate limit + audit + error classification) lives
in :mod:`dialekt.mcp.server.tools._wrap` so every tool body stays
focused on its one backend call.
"""
