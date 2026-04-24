"""Secret-reference resolution for MCP credentials.

At manifest-load time, an agent's ``mcp_servers[]`` block can refer
to stored secrets via ``${secrets.NAME}`` placeholders — for
example::

    mcp_servers:
      - name: github
        transport: stdio
        command: ["npx", "-y", "@modelcontextprotocol/server-github"]
        env:
          GITHUB_TOKEN: "${secrets.github_token}"

This module turns those strings into concrete values by looking them
up via ``dialekt.secrets`` (the same OS-keyring path used for
license keys + cloud tokens).

Keyring namespace
-----------------

Secrets are stored under ``dialekt.secrets``'s single service name
``"dialekt"`` with the *account* portion of the entry namespaced
as ``mcp.<server_name>.<ref_name>``. That keeps MCP secrets visible
alongside dialekt's other secrets in a keyring inspector, without
colliding on account strings. See ``docs/M2_MCP_DESIGN.md``
Decision 2.

The public API of this module is:

    resolve_secret_refs(value, *, server_name) -> str
    resolve_env(env, *, server_name) -> dict[str, str]
    keyring_key(server_name, ref_name) -> str   # for UI / tests
"""
from __future__ import annotations

import re

from dialekt.mcp.errors import MCPConfigError
from dialekt.secrets import get_secret


_REF_PATTERN = re.compile(r"\$\{secrets\.([a-zA-Z0-9_.-]+)\}")

_KEYRING_PREFIX = "mcp"


def keyring_key(server_name: str, ref_name: str) -> str:
    """Compose the keyring account string for an MCP secret.

    The full keyring entry is ``(service="dialekt", account=<this>)``.
    Exposed so UI + tests + migration scripts don't hand-roll the
    namespace format.
    """
    return f"{_KEYRING_PREFIX}.{server_name}.{ref_name}"


def resolve_secret_refs(value: str, *, server_name: str) -> str:
    """Replace every ``${secrets.NAME}`` in ``value`` with its stored secret.

    Lookups go to ``dialekt.secrets.get_secret(keyring_key(server_name, NAME))``.
    An unresolved reference raises :class:`MCPConfigError` with a
    message that points the user at the exact keyring key they need
    to set.
    """
    def _substitute(match: re.Match[str]) -> str:
        ref_name = match.group(1)
        key = keyring_key(server_name, ref_name)
        resolved = get_secret(key)
        if resolved is None:
            raise MCPConfigError(
                f"MCP server {server_name!r}: secret reference "
                f"${{secrets.{ref_name}}} is unresolved — "
                f"set it via dialekt.secrets.set_secret({key!r}, ...) "
                f"or through the dialekt credentials UI."
            )
        return resolved

    return _REF_PATTERN.sub(_substitute, value)


def resolve_env(
    env: dict[str, str],
    *,
    server_name: str,
) -> dict[str, str]:
    """Resolve secret refs across every value of an env dict.

    Keys are left alone (they are literal env var names); values go
    through :func:`resolve_secret_refs`.
    """
    return {
        name: resolve_secret_refs(raw, server_name=server_name)
        for name, raw in env.items()
    }


def has_unresolved_refs(value: str) -> bool:
    """True if the string still contains a ``${secrets.*}`` placeholder.

    Useful as a defence-in-depth check at call sites that expect all
    refs to have been resolved — if a bug leaves one behind, this
    catches the leak before it is written to a log or passed into a
    subprocess env.
    """
    return bool(_REF_PATTERN.search(value))
