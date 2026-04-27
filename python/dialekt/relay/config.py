"""Configuration for the dialekt GPU Relay server.

Reads ``~/.dialekt/relay-server.toml`` (or a custom path) and produces
a validated :class:`RelayConfig`. Mirrors the loader shape used by
``dialekt.mcp.server.config`` so operators familiar with the MCP
server settings find no surprises.

TOML shape::

    [server]
    port = 3050
    ollama_url = "http://127.0.0.1:11434"
    cloud_db_url = "postgres://dias:...@127.0.0.1:5432/dialekt_cloud"
    log_level = "INFO"
    default_rate_limit_per_minute = 120

Env-var overrides (applied after file load):

    DIALEKT_RELAY_PORT          → config.port
    DIALEKT_RELAY_OLLAMA_URL    → config.ollama_url
    DIALEKT_RELAY_DB_URL        → config.cloud_db_url
    DIALEKT_RELAY_LOG_LEVEL     → config.log_level
    DIALEKT_RELAY_CONFIG_PATH   → which file ``load_config`` reads
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


DEFAULT_CONFIG_PATH = Path.home() / ".dialekt" / "relay-server.toml"
DEFAULT_PORT = 3050
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_RATE_LIMIT = 120


class RelayConfig(BaseModel):
    """Parsed + validated contents of ``relay-server.toml``.

    ``cloud_db_url`` is optional: the relay starts without it for local
    smoke tests against a development Ollama. Auth + billing wiring
    (Commits 2 + 3) refuse to start without it — that's where the
    DSN actually gets used.
    """
    model_config = ConfigDict(extra="forbid")

    port: int = Field(default=DEFAULT_PORT, gt=0, lt=65536)
    ollama_url: str = DEFAULT_OLLAMA_URL
    cloud_db_url: Optional[str] = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = DEFAULT_LOG_LEVEL
    default_rate_limit_per_minute: int = Field(default=DEFAULT_RATE_LIMIT, gt=0)


def load_config(
    path: Optional[Path | str] = None,
    *,
    apply_env_overrides: bool = True,
) -> RelayConfig:
    """Read and validate ``relay-server.toml``.

    Missing file → returns defaults. Useful for ``python -m dialekt.relay``
    smoke runs against a local Ollama before any config has been written.
    """
    if path is None:
        env_path = os.environ.get("DIALEKT_RELAY_CONFIG_PATH")
        path = Path(env_path) if env_path else DEFAULT_CONFIG_PATH
    path = Path(path)

    raw: dict = {}
    if path.exists():
        with path.open("rb") as fh:
            raw = tomllib.load(fh)

    server_section = raw.get("server", {})
    config = RelayConfig.model_validate(server_section)

    if apply_env_overrides:
        config = _apply_env_overrides(config)

    return config


def _apply_env_overrides(config: RelayConfig) -> RelayConfig:
    updates: dict = {}
    if v := os.environ.get("DIALEKT_RELAY_PORT"):
        updates["port"] = int(v)
    if v := os.environ.get("DIALEKT_RELAY_OLLAMA_URL"):
        updates["ollama_url"] = v
    if v := os.environ.get("DIALEKT_RELAY_DB_URL"):
        updates["cloud_db_url"] = v
    if v := os.environ.get("DIALEKT_RELAY_LOG_LEVEL"):
        v = v.upper()
        if v in ("DEBUG", "INFO", "WARNING", "ERROR"):
            updates["log_level"] = v
    return config.model_copy(update=updates) if updates else config
