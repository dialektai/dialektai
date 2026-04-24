"""Agent tools for the MCP server.

Two read-only tools: ``dialekt_list_agents`` and ``dialekt_get_agent``.
Both proxy to the existing ``GET /agents`` / ``GET /agents/{id}``
endpoints on dialekt's backend.

``dialekt_invoke_agent`` is DELIBERATELY NOT REGISTERED in v0.20.0
per the Decision 3 review ruling (docs/M2_MCP_SERVER_DESIGN.md) —
shipping a stub that raises "not implemented" would violate MCP's
working-tools contract. The tool name is reserved; M3 ships it as
a real end-to-end implementation with session + consent propagation.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from dialekt.mcp.server.tools._wrap import call_tool_wrapped

if TYPE_CHECKING:
    from dialekt.llm._plugin_context import PluginContext
    from dialekt.mcp.server.server import MCPServer


def register_agent_tools(
    server: "MCPServer",
    ctx: "PluginContext",
) -> list[str]:
    """Attach the 2 agent tools. Returns the registered tool names."""
    registered: list[str] = []

    @server.fastmcp.tool(
        description=(
            "List the pilot's configured dialekt agents. Returns name, "
            "description, capability groups, autonomy level, and status "
            "for each agent — same data the dialekt desktop Agents "
            "panel shows."
        )
    )
    def dialekt_list_agents() -> list[dict]:
        def _handler() -> list[dict]:
            response = ctx.get("/agents")
            if response.status_code >= 400:
                raise RuntimeError(
                    f"list_agents failed: HTTP {response.status_code}"
                )
            # Trim to the fields that make sense across the MCP wire —
            # drop manifest_yaml (verbose, fetch via get_agent if needed)
            # and created_at (noisy, use get_agent for detail).
            trimmed: list[dict] = []
            for entry in response.json():
                trimmed.append({
                    "id": entry.get("id"),
                    "name": entry.get("name"),
                    "description": entry.get("description", ""),
                    "version": entry.get("version"),
                    "status": entry.get("status"),
                })
            return trimmed

        return call_tool_wrapped(server, "dialekt_list_agents", _handler)

    registered.append("dialekt_list_agents")

    @server.fastmcp.tool(
        description=(
            "Get one dialekt agent's detail: full manifest YAML, "
            "binding info, system prompt. Use after dialekt_list_agents "
            "when you need the manifest shape or capabilities to decide "
            "whether the agent fits your task."
        )
    )
    def dialekt_get_agent(agent_id: str) -> dict:
        def _handler() -> dict:
            response = ctx.get(f"/agents/{agent_id}")
            if response.status_code == 404:
                return {
                    "error": True,
                    "reason": "not_found",
                    "agent_id": agent_id,
                }
            if response.status_code >= 400:
                raise RuntimeError(
                    f"get_agent failed: HTTP {response.status_code}"
                )
            data = response.json()
            # Add the binding if present — same "one call returns the
            # whole picture" shape the desktop UI uses.
            binding_resp = ctx.get(f"/agents/{agent_id}/binding")
            if binding_resp.status_code < 400:
                data["binding"] = binding_resp.json()
            return data

        return call_tool_wrapped(
            server,
            "dialekt_get_agent",
            _handler,
            extra_audit={"agent_id": agent_id},
        )

    registered.append("dialekt_get_agent")

    return registered
