"""Credentials for dialekt's MCP client.

Three auth schemes ship in v0.20.0 per ``docs/M2_MCP_DESIGN.md``
Decision 2:

    - ``NoAuth`` — loopback / trusted subprocess servers.
    - ``EnvVarsAuth`` — env vars injected into a stdio subprocess.
      This is how ``@modelcontextprotocol/server-github`` wants
      ``GITHUB_TOKEN``.
    - ``BearerAuth`` — ``Authorization: Bearer <token>`` on HTTP
      requests.

OAuth 2.1 flows are deferred to M3 and intentionally not modelled
here.

Secret resolution: these spec classes carry *references* to secrets,
not plaintext. The ``token`` / ``value`` fields are expected to be
materialised from the keyring or env before a transport is opened.
Actual resolution logic lives in the call sites that receive these
specs (``connection.MCPConnection``), not on the spec itself —
keeping these models simple + serializable.
"""
from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field


class NoAuth(BaseModel):
    """No authentication — e.g. a local filesystem MCP on a temp dir."""

    kind: Literal["none"] = "none"


class EnvVarsAuth(BaseModel):
    """Environment variables passed into a stdio subprocess.

    Only stdio transports use this. HTTP transports should use
    ``BearerAuth`` even when a server also accepts env-style auth.
    """

    kind: Literal["env"] = "env"
    vars: dict[str, str] = Field(default_factory=dict)


class BearerAuth(BaseModel):
    """Static bearer token attached as ``Authorization: Bearer <token>``."""

    kind: Literal["bearer"] = "bearer"
    token: str = Field(..., min_length=1)


Credentials = Union[NoAuth, EnvVarsAuth, BearerAuth]
"""Discriminated union on ``kind``."""
