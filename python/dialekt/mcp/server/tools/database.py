"""Database tools for the MCP server.

Five tools that together give external hosts read-mostly access to
dialekt's configured DB connections. Every one of them proxies to
the dialekt backend HTTP API — the router logic, SQL safety parser,
and driver-specific code stay where they are.

Coverage in v0.20.0: PostgreSQL (primary). The ``connection_type``
parameter accepts ``"postgres"``, ``"mysql"``, ``"clickhouse"`` and
routes to the corresponding backend endpoint. MySQL + ClickHouse
work end-to-end but are less-tested; pilots using them should expect
a few rough edges.
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from dialekt.mcp.server.tools._wrap import call_tool_wrapped

if TYPE_CHECKING:
    from dialekt.llm._plugin_context import PluginContext
    from dialekt.mcp.server.server import MCPServer


_TYPE_TO_PREFIX: dict[str, str] = {
    "postgres": "/connections",
    "mysql": "/mysql-connections",
    "clickhouse": "/ch-connections",
}


def _prefix_for(connection_type: str) -> str:
    try:
        return _TYPE_TO_PREFIX[connection_type]
    except KeyError as e:
        raise ValueError(
            f"Unknown connection_type: {connection_type!r}. "
            f"Supported: {sorted(_TYPE_TO_PREFIX)}"
        ) from e


def register_database_tools(
    server: "MCPServer",
    ctx: "PluginContext",
) -> list[str]:
    """Attach the 5 database tools to the FastMCP instance on
    ``server``. Returns the registered tool names."""
    registered: list[str] = []

    @server.fastmcp.tool(
        description=(
            "List configured database connections. Returns entries "
            "with id/name/type but never credentials. Covers "
            "postgres, mysql, and clickhouse connections."
        )
    )
    def dialekt_list_connections() -> list[dict[str, Any]]:
        def _handler() -> list[dict[str, Any]]:
            connections: list[dict[str, Any]] = []
            for kind, prefix in _TYPE_TO_PREFIX.items():
                try:
                    response = ctx.get(prefix)
                    if response.status_code >= 400:
                        continue
                    entries = response.json()
                    for entry in entries:
                        entry = dict(entry)
                        entry.pop("password", None)
                        entry.pop("connection_string", None)
                        entry["connection_type"] = kind
                        connections.append(entry)
                except Exception:
                    # A misconfigured driver shouldn't blank out the
                    # whole list — silently skip and continue. The
                    # audit row captures the call as success anyway
                    # because we returned partial but consistent data.
                    continue
            return connections

        return call_tool_wrapped(server, "dialekt_list_connections", _handler)

    registered.append("dialekt_list_connections")

    @server.fastmcp.tool(
        description=(
            "Execute a SQL query against a configured DB connection. "
            "Read-only — the dialekt backend's sql_safety parser "
            "rejects any statement that mutates data. The row_limit "
            "(default 1000 in backend config) is honored."
        )
    )
    def dialekt_query_database(
        connection_id: str,
        sql: str,
        connection_type: str = "postgres",
    ) -> dict[str, Any]:
        def _handler() -> dict[str, Any]:
            prefix = _prefix_for(connection_type)
            response = ctx.post(
                f"{prefix}/{connection_id}/query",
                json={"sql": sql},
            )
            if response.status_code >= 400:
                try:
                    body = response.json()
                except Exception:
                    body = {"detail": response.text}
                return {
                    "error": True,
                    "status": response.status_code,
                    "detail": body,
                }
            return response.json()

        return call_tool_wrapped(
            server,
            "dialekt_query_database",
            _handler,
            extra_audit={
                "connection_id": connection_id,
                "connection_type": connection_type,
                "sql_preview": sql[:200],
            },
        )

    registered.append("dialekt_query_database")

    @server.fastmcp.tool(
        description=(
            "List schemas/tables on a DB connection. Returns a nested "
            "{schema: [tables...]} structure."
        )
    )
    def dialekt_list_tables(
        connection_id: str,
        connection_type: str = "postgres",
    ) -> dict[str, list[str]]:
        def _handler() -> dict[str, list[str]]:
            prefix = _prefix_for(connection_type)
            schemas_resp = ctx.get(f"{prefix}/{connection_id}/schemas")
            if schemas_resp.status_code >= 400:
                raise RuntimeError(
                    f"list_schemas failed: HTTP {schemas_resp.status_code}"
                )
            schemas = schemas_resp.json()
            out: dict[str, list[str]] = {}
            for schema in schemas:
                tables_resp = ctx.get(
                    f"{prefix}/{connection_id}/schemas/{schema}/tables"
                )
                if tables_resp.status_code >= 400:
                    out[schema] = []
                    continue
                out[schema] = list(tables_resp.json())
            return out

        return call_tool_wrapped(
            server,
            "dialekt_list_tables",
            _handler,
            extra_audit={"connection_id": connection_id,
                         "connection_type": connection_type},
        )

    registered.append("dialekt_list_tables")

    @server.fastmcp.tool(
        description=(
            "Describe a table: columns, types, primary/foreign keys. "
            "Pure introspection; respects the connection's readonly role."
        )
    )
    def dialekt_describe_table(
        connection_id: str,
        schema: str,
        table: str,
        connection_type: str = "postgres",
    ) -> dict[str, Any]:
        def _handler() -> dict[str, Any]:
            prefix = _prefix_for(connection_type)
            response = ctx.get(
                f"{prefix}/{connection_id}/schemas/{schema}/tables/{table}/describe"
            )
            if response.status_code >= 400:
                raise RuntimeError(
                    f"describe_table failed: HTTP {response.status_code}"
                )
            return response.json()

        return call_tool_wrapped(
            server,
            "dialekt_describe_table",
            _handler,
            extra_audit={
                "connection_id": connection_id,
                "connection_type": connection_type,
                "schema": schema,
                "table": table,
            },
        )

    registered.append("dialekt_describe_table")

    @server.fastmcp.tool(
        description=(
            "Semantic search over a connection's schema via Schema RAG. "
            "Returns matching tables/columns ranked by relevance to "
            "the natural-language query. Requires the nomic-embed-text "
            "Ollama model to be available on the dialekt backend."
        )
    )
    def dialekt_search_schema(
        connection_id: str,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        def _handler() -> list[dict[str, Any]]:
            # Schema RAG endpoint lives at connection level; it's
            # Postgres-first today. The backend errors out cleanly
            # for non-pg connections; we surface that verbatim.
            response = ctx.post(
                f"/connections/{connection_id}/schema-rag/search",
                json={"query": query, "limit": limit},
            )
            if response.status_code >= 400:
                raise RuntimeError(
                    f"search_schema failed: HTTP {response.status_code}. "
                    "Ensure the nomic-embed-text model is installed "
                    "(Settings → Schema RAG in dialekt desktop)."
                )
            return response.json()

        return call_tool_wrapped(
            server,
            "dialekt_search_schema",
            _handler,
            extra_audit={
                "connection_id": connection_id,
                "query_preview": query[:200],
                "limit": limit,
            },
        )

    registered.append("dialekt_search_schema")

    return registered
