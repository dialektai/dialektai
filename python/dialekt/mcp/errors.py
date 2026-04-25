"""Exception taxonomy for dialekt.mcp.

Seven concrete classes implementing the error model from
``docs/M2_MCP_DESIGN.md`` Decision 6. Every failure in the MCP
client + server stack maps to exactly one of these. All inherit
from ``MCPError`` (itself a ``RuntimeError``) so callers can
catch broadly or narrowly.
"""
from __future__ import annotations


class MCPError(RuntimeError):
    """Base for all MCP-related failures.

    Callers that want to treat any MCP failure uniformly catch this
    class. Callers that want to branch — e.g. retry only on
    ``MCPServerUnavailableError`` — catch the specific subclass.
    """


class MCPConfigError(MCPError):
    """Raised before any wire traffic.

    Covers: missing secret referenced by manifest, stdio command not
    found on PATH, spec/minimum-dialekt-version mismatch, unknown
    transport type, malformed auth block. Not agent-visible — surfaces
    in the UI as a "this agent can't start" error.
    """


class MCPServerUnavailableError(MCPError):
    """MCP server is unreachable.

    Subprocess dead, HTTP 5xx/4xx other than tool errors, connect
    refused, DNS failure. Agent-visible: the call that tripped it
    gets this as a tool error. One lazy reconnect is attempted on
    the next call; after that failure mode becomes sticky until the
    user triggers a manual restart.
    """


class MCPToolNotFoundError(MCPError):
    """Agent asked for a tool the server doesn't advertise.

    Deterministic — never retried. The manifest's allow/deny list
    is checked before this class of error gets raised, so this only
    fires when the *server* doesn't have the tool.
    """


class MCPToolError(MCPError):
    """Server returned an MCP-level ``isError=true`` tool result.

    The server ran the tool and reported a domain error
    (e.g. "repository not found"). Full message is preserved in
    ``args[0]`` and passed back to the LLM verbatim. The LLM decides
    whether to retry with different arguments or give up.
    """


class MCPTimeoutError(MCPError):
    """Per-call timeout elapsed before the server responded.

    Timeout is the ``timeout_seconds`` from the manifest's
    ``mcp_servers[].timeout_seconds`` field (default 30s). The
    underlying JSON-RPC request is cancelled; the connection stays
    open for future calls.
    """


class MCPRateLimitError(MCPError):
    """Dialekt's own rate limiter tripped.

    Enforced per agent session against the aggregate of all MCP
    tool calls across all configured servers (default 60/minute).
    Not a server-reported rate limit — those come back as
    ``MCPToolError`` and the LLM handles them.
    """


class MCPProtocolError(MCPError):
    """Wire-level protocol violation.

    Malformed JSON-RPC, unknown method, negotiation mismatch,
    version skew. Logged as a warning (indicates a bug on one side
    or the other) and never retried — the connection is marked
    unhealthy and torn down at the next natural lifecycle boundary.
    """


class MCPConsentDenied(MCPError):
    """User explicitly denied an MCP tool invocation.

    Not a failure — a legitimate agent-control outcome. The LLM
    receives this as a tool error and may propose an alternative,
    ask for clarification, or give up gracefully. Audit log records
    the decision under ``kind='mcp_consent_decision'`` with
    ``result='denied'``; there is NO ``error_kind`` attached to
    such audit rows because denial is the system working as designed.
    """


class MCPToolNotAllowed(MCPError):
    """Tool blocked by per-server allow_tools/deny_tools policy.

    Distinct from :class:`MCPConsentDenied`: that's a per-call user
    decision; this is a manifest-level static policy block declared
    via ``mcp_servers[].allow_tools`` / ``deny_tools``. The user is
    never prompted; the call fast-fails before consent or dispatch.
    Audited under ``kind='mcp_tool_blocked'``.
    """
