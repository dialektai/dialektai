"""File tools for the MCP server.

Five tools, all gated by ``ServerConfig.allowed_file_roots``:

- ``dialekt_read_file`` — read a UTF-8 text file.
- ``dialekt_list_directory`` — list immediate children of a directory.
- ``dialekt_write_file`` — write/overwrite a UTF-8 text file (creates
  parent directories on demand).
- ``dialekt_append_file`` — append UTF-8 text to a file.
- ``dialekt_make_dir`` — create a directory (with parents).

The allow-list default is empty so these tools refuse everything until
a pilot opts paths in via the config — or an agent registers its own
``working_directory`` via :func:`register_working_directory` at load
time. Validation resolves symlinks on both the request path and each
root before prefix-checking, killing both directory-traversal attacks
and symlink-escape attacks where an attacker drops a symlink inside an
allowed root pointing outside of it.

The roots list is read live from ``server.config.allowed_file_roots``
on every call, so dynamic mutations done by
:func:`register_working_directory` take effect immediately.
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


def register_working_directory(
    server: "MCPServer",
    working_directory: str | None,
) -> None:
    """Add an agent's ``working_directory`` to the live allow-list.

    Called by the agent runtime when an agent with a manifest
    ``variables.working_directory`` (or equivalent) is loaded. No-op
    when ``working_directory`` is empty / ``None``.

    The path is expanded + absolutised the same way
    :class:`ServerConfig` normalises roots at config load, and is
    deduplicated so repeated agent loads don't bloat the list.
    """
    if not working_directory:
        return
    expanded = os.path.expanduser(working_directory)
    absolute = os.path.abspath(expanded)
    roots = server.config.allowed_file_roots
    if absolute not in roots:
        roots.append(absolute)


def register_file_tools(server: "MCPServer") -> list[str]:
    """Attach the five file tools. Returns the registered names."""
    registered: list[str] = []

    def _live_roots() -> list[str]:
        # Read fresh on every call so register_working_directory()
        # additions take effect without re-registering tools.
        return list(server.config.allowed_file_roots)

    @server.fastmcp.tool(
        description=(
            "Read a UTF-8 text file. The path must resolve (including "
            "symlink resolution) to a location inside one of the "
            "server's allowed_file_roots — default empty, i.e. this "
            "tool does nothing until a pilot adds roots to "
            "~/.dialekt/mcp-server.toml or an agent registers its "
            "working_directory."
        )
    )
    def dialekt_read_file(path: str) -> dict:
        def _handler() -> dict:
            safe = _resolve_safe(path, _live_roots())
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
            safe = _resolve_safe(path, _live_roots())
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

    @server.fastmcp.tool(
        description=(
            "Write UTF-8 text to a file. Creates parent directories "
            "as needed; existing files are overwritten unless "
            "``mode='create_exclusive'`` is passed (returns a "
            "structured ``exists`` error). Refuses paths outside the "
            "allow-list."
        )
    )
    def dialekt_write_file(
        path: str,
        content: str,
        mode: str = "overwrite",
    ) -> dict:
        def _handler() -> dict:
            if mode not in ("overwrite", "create_exclusive"):
                return {
                    "error": True,
                    "reason": "invalid_mode",
                    "detail": f"mode must be 'overwrite' or 'create_exclusive', got {mode!r}",
                }
            safe = _resolve_safe(path, _live_roots())
            if mode == "create_exclusive" and safe.exists():
                return {
                    "error": True,
                    "reason": "exists",
                    "path": str(safe),
                }
            try:
                safe.parent.mkdir(parents=True, exist_ok=True)
                safe.write_text(content, encoding="utf-8")
            except OSError as e:
                return {
                    "error": True,
                    "reason": "write_failed",
                    "path": str(safe),
                    "detail": str(e),
                }
            return {
                "path": str(safe),
                "size_bytes": safe.stat().st_size,
                "mode": mode,
            }

        return call_tool_wrapped(
            server,
            "dialekt_write_file",
            _handler,
            extra_audit={"requested_path": path, "mode": mode},
        )

    registered.append("dialekt_write_file")

    @server.fastmcp.tool(
        description=(
            "Append UTF-8 text to a file. Creates parent directories "
            "and the file itself if missing. Refuses paths outside "
            "the allow-list."
        )
    )
    def dialekt_append_file(path: str, content: str) -> dict:
        def _handler() -> dict:
            safe = _resolve_safe(path, _live_roots())
            try:
                safe.parent.mkdir(parents=True, exist_ok=True)
                with safe.open("a", encoding="utf-8") as f:
                    f.write(content)
            except OSError as e:
                return {
                    "error": True,
                    "reason": "append_failed",
                    "path": str(safe),
                    "detail": str(e),
                }
            return {
                "path": str(safe),
                "size_bytes": safe.stat().st_size,
            }

        return call_tool_wrapped(
            server,
            "dialekt_append_file",
            _handler,
            extra_audit={"requested_path": path},
        )

    registered.append("dialekt_append_file")

    @server.fastmcp.tool(
        description=(
            "Create a directory (with parents) inside the allow-list. "
            "Idempotent: existing directories return a structured "
            "``already_exists`` payload rather than an error. Refuses "
            "paths that already exist as files."
        )
    )
    def dialekt_make_dir(path: str) -> dict:
        def _handler() -> dict:
            safe = _resolve_safe(path, _live_roots())
            if safe.exists() and not safe.is_dir():
                return {
                    "error": True,
                    "reason": "not_a_directory",
                    "path": str(safe),
                }
            already = safe.exists()
            try:
                safe.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return {
                    "error": True,
                    "reason": "mkdir_failed",
                    "path": str(safe),
                    "detail": str(e),
                }
            return {
                "path": str(safe),
                "created": not already,
                "already_exists": already,
            }

        return call_tool_wrapped(
            server,
            "dialekt_make_dir",
            _handler,
            extra_audit={"requested_path": path},
        )

    registered.append("dialekt_make_dir")

    return registered
