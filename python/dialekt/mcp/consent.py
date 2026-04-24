"""Consent gating for destructive MCP tool invocations.

Decision 5 (security) requires write-shaped tools to surface a
consent prompt before dispatching. This module implements:

- :class:`ConsentDecision` — the enum the prompt resolves to.
- :func:`is_destructive_tool` — destructive-ness detection:
  explicit MCP annotations first, name-pattern heuristic as fallback.
- :class:`ConsentProvider` — the protocol for "how to ask the user".
  Three concrete implementations ship:
    - ``AutoApproveProvider`` for ``autonomous`` autonomy
    - ``AutoDenyProvider`` for tests / review-only
    - ``SessionCachingProvider`` wraps an inner provider and caches
      ``APPROVED_SESSION`` decisions per ``(server_name, tool_name)``
      for the life of the session.
- :func:`provider_for_autonomy` — maps the manifest's ``autonomy``
  level into the correct provider chain for a session.

The runtime layer (``dialekt.mcp.runtime``) calls into these before
handing a tool call to ``MCPClientManager.call_tool``. Audit rows
for consent events are emitted at the runtime layer; this module is
pure policy + user-prompt protocol.
"""
from __future__ import annotations

import asyncio
import enum
from typing import Any, Awaitable, Callable, Optional, Protocol


class ConsentDecision(str, enum.Enum):
    """The three possible outcomes of a consent prompt."""

    APPROVED = "approved"
    """Approve this single tool invocation. Next call re-asks."""

    APPROVED_SESSION = "approved_session"
    """Approve this tool for the rest of the chat session.

    Scope is narrow by design: identical ``(server_name, tool_name)``
    pairs only. Same tool on a different server, or a different tool
    on the same server, re-prompts. Session-scoped, never persisted —
    reconnecting the WebSocket resets the cache.
    """

    DENIED = "denied"
    """User rejected the tool call. Runtime raises
    :class:`MCPConsentDenied`; LLM sees it as a tool error and
    decides how to adapt."""


# Name-pattern tokens that imply a write / side-effect. Case-insensitive
# substring match — a tool named ``delete_branch`` hits ``delete``;
# ``list_repos`` does not. False positives (asking consent when the
# tool is actually read-only) are acceptable; false negatives (silently
# dispatching a destructive call) are not.
_DESTRUCTIVE_NAME_TOKENS = (
    "create", "update", "delete", "remove", "modify", "write",
    "send", "post", "edit", "patch", "put", "upload", "move",
    "rename", "drop", "truncate", "execute", "run",
)


def is_destructive_tool(tool: Any) -> tuple[bool, str]:
    """Return ``(is_destructive, source)`` for a tool-metadata object.

    ``source`` is ``"explicit"`` when the MCP server annotated the tool
    via ``annotations.destructive`` / ``annotations.writeable``, and
    ``"heuristic"`` when we fell back to name-pattern matching.

    An explicit annotation ALWAYS wins over heuristic: if a server
    says "this is safe", we trust it. The heuristic only fires when
    the server gave us no signal at all.

    Accepts any object with a ``name`` attribute and an optional
    ``annotations`` attribute whose shape is a dict-like. Tolerant of
    missing fields because MCP servers in the wild don't annotate
    consistently.
    """
    annotations = getattr(tool, "annotations", None)
    if annotations is not None:
        # pydantic model OR plain dict — support both shapes
        destructive_hint = _get_annotation(annotations, "destructive")
        writeable_hint = _get_annotation(annotations, "writeable")
        if destructive_hint is not None:
            return bool(destructive_hint), "explicit"
        if writeable_hint is not None:
            return bool(writeable_hint), "explicit"

    name = str(getattr(tool, "name", "") or "")
    lowered = name.lower()
    for token in _DESTRUCTIVE_NAME_TOKENS:
        if token in lowered:
            return True, "heuristic"
    return False, "heuristic"


def _get_annotation(annotations: Any, key: str) -> Any:
    """Read ``key`` from a pydantic model OR dict. Returns ``None`` if absent."""
    if isinstance(annotations, dict):
        return annotations.get(key)
    return getattr(annotations, key, None)


class ConsentRequest:
    """Payload for a consent prompt — what the UI renders to the user."""

    def __init__(
        self,
        *,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        destructive: bool,
        destructive_source: str,
    ) -> None:
        self.server_name = server_name
        self.tool_name = tool_name
        self.arguments = arguments
        self.destructive = destructive
        self.destructive_source = destructive_source

    def to_dict(self) -> dict[str, Any]:
        return {
            "server_name": self.server_name,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "destructive": self.destructive,
            "destructive_source": self.destructive_source,
        }


class ConsentProvider(Protocol):
    """How the runtime learns what the user wants to do with a tool call.

    Implementations may prompt via WebSocket (production), auto-resolve
    (``AutoApprove`` / ``AutoDeny``), or delegate through caches
    (``SessionCachingProvider``). Ask one at a time — ``request_consent``
    may be called concurrently if the agent fires multiple tools in
    parallel; implementations are responsible for serializing prompts
    to the user if they care about order.
    """

    async def request_consent(
        self, request: ConsentRequest
    ) -> ConsentDecision: ...


class AutoApproveProvider:
    """Always returns :attr:`ConsentDecision.APPROVED`.

    For ``autonomy: autonomous`` sessions. Records no state.
    """

    async def request_consent(
        self, request: ConsentRequest
    ) -> ConsentDecision:
        return ConsentDecision.APPROVED


class AutoDenyProvider:
    """Always returns :attr:`ConsentDecision.DENIED`.

    For ``autonomy: review-only`` sessions and for tests of the denial
    path. Records no state.
    """

    async def request_consent(
        self, request: ConsentRequest
    ) -> ConsentDecision:
        return ConsentDecision.DENIED


PromptFn = Callable[[ConsentRequest], Awaitable[ConsentDecision]]


class PromptConsentProvider:
    """Delegates to a user-supplied async prompt function.

    The ws_chat session handler passes a prompt function that:
      - sends a ``mcp_consent_request`` WebSocket message to the frontend
      - waits for a ``mcp_consent_response`` message back
      - resolves to one of the three ``ConsentDecision`` values

    Decoupling the prompt from this module means the consent logic
    tests against simple callables, not against a WebSocket mock.
    """

    def __init__(self, prompt_fn: PromptFn) -> None:
        self._prompt_fn = prompt_fn

    async def request_consent(
        self, request: ConsentRequest
    ) -> ConsentDecision:
        return await self._prompt_fn(request)


class SessionCachingProvider:
    """Wraps an inner provider. Caches ``APPROVED_SESSION`` decisions
    keyed by ``(server_name, tool_name)``.

    First call on a given pair goes to the inner provider. If the
    user returns ``APPROVED_SESSION``, every subsequent call on the
    same pair short-circuits to ``APPROVED`` for the life of this
    instance. ``APPROVED`` (single-shot) and ``DENIED`` decisions are
    NOT cached — each call asks again.
    """

    def __init__(self, inner: ConsentProvider) -> None:
        self._inner = inner
        self._session_approvals: set[tuple[str, str]] = set()
        self._lock = asyncio.Lock()

    async def request_consent(
        self, request: ConsentRequest
    ) -> ConsentDecision:
        key = (request.server_name, request.tool_name)
        # Fast path without the lock.
        if key in self._session_approvals:
            return ConsentDecision.APPROVED
        # Slow path — hold the lock so concurrent prompts for the
        # same pair don't double-ask the user.
        async with self._lock:
            if key in self._session_approvals:
                return ConsentDecision.APPROVED
            decision = await self._inner.request_consent(request)
            if decision is ConsentDecision.APPROVED_SESSION:
                self._session_approvals.add(key)
            return decision


def provider_for_autonomy(
    autonomy_level: str,
    user_prompt_fn: Optional[PromptFn] = None,
) -> ConsentProvider:
    """Return the provider chain appropriate for a manifest's autonomy.

    Mapping (docs/M2_MCP_DESIGN.md Decision 5):
        ``autonomous``       -> AutoApproveProvider
        ``review-only``      -> AutoDenyProvider  (all destructive tools blocked)
        ``ask-before-write`` -> SessionCaching(Prompt)  — asks on destructive
        ``manual``           -> SessionCaching(Prompt)  — asks on EVERY call;
                                                         runtime skips the
                                                         destructiveness check
        ``sandbox-only``     -> SessionCaching(Prompt)  (treated like
                                                         ask-before-write for
                                                         v0.20.0; true sandbox
                                                         is out of scope)

    ``user_prompt_fn`` is required when the autonomy level needs to
    prompt; omit it only for ``autonomous`` / ``review-only``.
    """
    if autonomy_level == "autonomous":
        return AutoApproveProvider()
    if autonomy_level == "review-only":
        return AutoDenyProvider()
    if user_prompt_fn is None:
        raise ValueError(
            f"autonomy={autonomy_level!r} needs a user_prompt_fn — "
            "only 'autonomous' and 'review-only' can run unattended"
        )
    return SessionCachingProvider(PromptConsentProvider(user_prompt_fn))
