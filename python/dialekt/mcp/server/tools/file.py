"""File tools for the MCP server.

Two tools, both gated by ``ServerConfig.allowed_file_roots``:

- ``dialekt_read_file`` — read a UTF-8 text file.
- ``dialekt_list_directory`` — list immediate children of a directory.

The allow-list default is empty (Decision 2 ruling) so these tools
refuse everything until a pilot opts paths in via the config. The
validation resolves symlinks on both the request path and each root
before prefix-checking — this kills directory-traversal attacks AND
symlink attacks where an attacker drops a symlink inside an allowed
root pointing outside of it.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from dialekt.mcp.server.tools._wrap import call_tool_wrapped

if TYPE_CHECKING:
    from dialekt.mcp.server.server import MCPServer


class PathAccessDenied(Exception):
    """Requested path falls outside the allow-list."""


def _resolve_safe(
    request_path: str,
    allowed_roots: list[str],
) -> Path:
    """Return an absolute, symlink-resolved :class:`Path` provably
    inside one of ``allowed_roots``. Raises :class:`PathAccessDenied`
    otherwise.

    Both the request path and each root are resolved with
    ``Path.resolve(strict=False)`` — ``strict=False`` so we can get
    a reasonable error path even when the file doesn't exist yet;
    the containment check still works.
    """
    if not allowed_roots:
        raise PathAccessDenied(
            "file tools disabled — [server] allowed_file_roots is empty "
            "in ~/.dialekt/mcp-server.toml. Add an explicit root to "
            "enable dialekt_read_file / dialekt_list_directory."
        )

    expanded = Path(os.path.expanduser(request_path))
    resolved = expanded.resolve(strict=False)

    for raw_root in allowed_roots:
        root = Path(os.path.expanduser(raw_root)).resolve(strict=False)
        try:
            # is_relative_to accepts Path on 3.9+.
            if resolved.is_relative_to(root):
                return resolved
        except ValueError:
            continue

    raise PathAccessDenied(
        f"path {str(resolved)!r} is outside the configured allow-list. "
        f"Allowed roots: {[str(Path(r).expanduser()) for r in allowed_roots]}"
    )


def register_file_tools(server: "MCPServer") -> list[str]:
    """Attach the two file tools. Returns the registered names."""
    registered: list[str] = []
    allowed_roots = list(server.config.allowed_file_roots)

    @server.fastmcp.tool(
        description=(
            "Read a UTF-8 text file. The path must resolve (including "
            "symlink resolution) to a location inside one of the "
            "server's allowed_file_roots — default empty, i.e. this "
            "tool does nothing until a pilot adds roots to "
            "~/.dialekt/mcp-server.toml."
        )
    )
    def dialekt_read_file(path: str) -> dict:
        def _handler() -> dict:
            safe = _resolve_safe(path, allowed_roots)
            if not safe.exists():
                return {"error": True, "reason": "not_found", "path": str(safe)}
            if not safe.is_file():
                return {"error": True, "reason": "not_a_file", "path": str(safe)}
            try:
                content = safe.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return {
                    "error": True,
                    "reason": "not_utf8",
                    "path": str(safe),
                }
            return {
                "path": str(safe),
                "size_bytes": safe.stat().st_size,
                "content": content,
            }

        return call_tool_wrapped(
            server,
            "dialekt_read_file",
            _handler,
            extra_audit={"requested_path": path},
        )

    registered.append("dialekt_read_file")

    @server.fastmcp.tool(
        description=(
            "List immediate children of a directory. Same allow-list "
            "gate as dialekt_read_file — non-recursive, directories "
            "outside the configured roots are refused."
        )
    )
    def dialekt_list_directory(path: str) -> dict:
        def _handler() -> dict:
            safe = _resolve_safe(path, allowed_roots)
            if not safe.exists():
                return {"error": True, "reason": "not_found", "path": str(safe)}
            if not safe.is_dir():
                return {
                    "error": True,
                    "reason": "not_a_directory",
                    "path": str(safe),
                }
            entries: list[dict] = []
            for child in sorted(safe.iterdir()):
                try:
                    stat = child.stat()
                except OSError:
                    continue
                entries.append({
                    "name": child.name,
                    "type": "dir" if child.is_dir() else (
                        "file" if child.is_file() else "other"
                    ),
                    "size_bytes": stat.st_size,
                })
            return {"path": str(safe), "entries": entries}

        return call_tool_wrapped(
            server,
            "dialekt_list_directory",
            _handler,
            extra_audit={"requested_path": path},
        )

    registered.append("dialekt_list_directory")

    return registered
