"""Transport descriptors for dialekt's MCP client.

A ``TransportSpec`` is the declarative configuration of *how* to
reach an MCP server. It does not hold any open connection — see
``connection.MCPConnection`` for that.

Two concrete specs:
    - ``StdioTransportSpec`` — spawn a subprocess, talk JSON-RPC
      over its stdin/stdout (``mcp.client.stdio``).
    - ``HttpTransportSpec`` — connect to a Streamable HTTP endpoint
      (``mcp.client.streamable_http``).

Legacy SSE transport is intentionally not modelled — see
``docs/M2_MCP_DESIGN.md`` Decision 1.

The spec classes are Pydantic models so they round-trip through the
manifest YAML -> validator -> runtime path cleanly (the manifest's
``mcp_servers[]`` entries deserialize directly into these).
"""
from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field


class StdioTransportSpec(BaseModel):
    """Configuration for a locally-spawned MCP server subprocess."""

    kind: Literal["stdio"] = "stdio"
    command: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "argv-style list. Never a shell string; the validator "
            "enforces list-shape to kill shell-interpolation risk "
            "(Decision 5)."
        ),
    )
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    timeout_seconds: float = 30.0


class HttpTransportSpec(BaseModel):
    """Configuration for a remote MCP server reached over Streamable HTTP."""

    kind: Literal["http"] = "http"
    url: str = Field(..., min_length=1)
    timeout_seconds: float = 30.0


TransportSpec = Union[StdioTransportSpec, HttpTransportSpec]
"""Discriminated union on ``kind``. Exported for type hints."""
