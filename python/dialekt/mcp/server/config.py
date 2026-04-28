"""Configuration for the dialekt MCP server.

Reads ``~/.dialekt/mcp-server.toml`` (or a custom path) and produces
a validated :class:`ServerConfig`. The file shape is documented in
``docs/M2_MCP_SERVER_DESIGN.md`` Decision 4; the defaults here match
what the design calls for.

Env-var overrides apply after file load:

    DIALEKT_BACKEND_URL        → config.backend_url
    DIALEKT_MCP_API_KEY        → appended to api_keys as ad-hoc entry
    DIALEKT_MCP_LOG_LEVEL      → config.log_level

``DIALEKT_MCP_CONFIG_PATH`` is consumed by ``load_config()`` itself
to choose which file to read.
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


DEFAULT_CONFIG_PATH = Path.home() / ".dialekt" / "mcp-server.toml"
DEFAULT_BACKEND_URL = "http://127.0.0.1:8765"
DEFAULT_RATE_LIMIT = 120
DEFAULT_LOG_LEVEL = "INFO"

TOOL_CATEGORIES = (
    "database",
    "file",
    "agent",
    "http",
    "rss",
    "bitrix",
    "instagram",
    "visual",
    "web_crawl",
)


class ApiKey(BaseModel):
    """One row in ``[server.api_keys]``.

    ``id`` is a short human-readable label used in audit rows
    (``target`` column) — "claude-desktop", "cursor", etc. It is
    NOT a secret and appears in logs.

    ``value`` is the opaque shared secret the client presents on
    each connection. Treat as a secret; we never log it verbatim.

    ``enabled_tools`` is an optional per-key allow-list. Missing or
    empty means "all tools in the server-wide enabled_categories".
    """
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    value: str = Field(min_length=16)
    enabled_tools: Optional[list[str]] = None


class StdioTransportConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True


class HttpTransportConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    port: int = Field(default=8766, gt=0, lt=65536)


class TransportConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stdio: StdioTransportConfig = Field(default_factory=StdioTransportConfig)
    http: HttpTransportConfig = Field(default_factory=HttpTransportConfig)


class ServerConfig(BaseModel):
    """Parsed + validated contents of ``mcp-server.toml``.

    Field defaults apply when the file is absent or partial — a
    first-run pilot gets a sensible config without touching anything.
    """
    model_config = ConfigDict(extra="forbid")

    api_keys: list[ApiKey] = Field(default_factory=list)
    enabled_categories: list[str] = Field(
        default_factory=lambda: list(TOOL_CATEGORIES)
    )
    rate_limit_per_minute: int = Field(default=DEFAULT_RATE_LIMIT, gt=0)
    allowed_file_roots: list[str] = Field(default_factory=list)
    transport: TransportConfig = Field(default_factory=TransportConfig)

    # Runtime knobs (populated from env / CLI, not normally in the toml)
    backend_url: str = DEFAULT_BACKEND_URL
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = DEFAULT_LOG_LEVEL

    @field_validator("enabled_categories")
    @classmethod
    def _validate_categories(cls, v: list[str]) -> list[str]:
        unknown = set(v) - set(TOOL_CATEGORIES)
        if unknown:
            raise ValueError(
                f"Unknown tool categories: {sorted(unknown)}. "
                f"Valid: {sorted(TOOL_CATEGORIES)}"
            )
        return v

    @field_validator("allowed_file_roots")
    @classmethod
    def _resolve_file_roots(cls, v: list[str]) -> list[str]:
        """Expand ``~`` and normalise. The file-tool call site still
        re-resolves each access path defensively, but normalising here
        helps the Settings UI show what actually applies."""
        resolved: list[str] = []
        for raw in v:
            expanded = os.path.expanduser(raw)
            absolute = os.path.abspath(expanded)
            resolved.append(absolute)
        return resolved

    def has_api_key(self, value: str) -> Optional[ApiKey]:
        """Return the matching ApiKey (by value) or ``None``.

        Linear scan — fine for the dozen-or-so keys a pilot config
        carries. Constant-time comparison via ``secrets.compare_digest``
        to keep timing-attack surface minimal.
        """
        import secrets

        for key in self.api_keys:
            if secrets.compare_digest(key.value, value):
                return key
        return None


def load_config(
    path: Optional[Path | str] = None,
    *,
    apply_env_overrides: bool = True,
) -> ServerConfig:
    """Read and validate ``mcp-server.toml``.

    Missing file → returns a default config (fields all at their
    defaults, ``api_keys=[]``). This keeps ``dialekt-mcp --dev``
    usable before the pilot has configured anything; production
    paths refuse to start with empty ``api_keys``.

    ``apply_env_overrides=True`` applies the env-var overrides
    documented in this module's header. Tests can pass ``False``
    to get deterministic file-only behaviour.
    """
    # Path precedence: explicit arg > env var > default.
    if path is None:
        env_path = os.environ.get("DIALEKT_MCP_CONFIG_PATH")
        if env_path:
            path = Path(env_path)
        else:
            path = DEFAULT_CONFIG_PATH
    path = Path(path)

    raw: dict = {}
    if path.exists():
        with path.open("rb") as fh:
            raw = tomllib.load(fh)

    # The TOML shape is ``[server]`` at top level; everything under.
    server_section = raw.get("server", {})
    config = ServerConfig.model_validate(server_section)

    if apply_env_overrides:
        config = _apply_env_overrides(config)

    return config


def _apply_env_overrides(config: ServerConfig) -> ServerConfig:
    """Return a copy with environment-variable overrides applied."""
    backend = os.environ.get("DIALEKT_BACKEND_URL")
    if backend:
        config = config.model_copy(update={"backend_url": backend})

    log_level = os.environ.get("DIALEKT_MCP_LOG_LEVEL")
    if log_level:
        log_level = log_level.upper()
        if log_level in ("DEBUG", "INFO", "WARNING", "ERROR"):
            config = config.model_copy(update={"log_level": log_level})

    env_key = os.environ.get("DIALEKT_MCP_API_KEY")
    if env_key:
        # Environment-injected keys get a synthetic id so audit rows
        # can tell them apart from TOML-declared ones.
        adhoc = ApiKey(id="env", value=env_key)
        config = config.model_copy(
            update={"api_keys": list(config.api_keys) + [adhoc]}
        )

    return config
