"""``python -m dialekt.relay`` entry point.

Reads ``~/.dialekt/relay-server.toml`` (or ``DIALEKT_RELAY_CONFIG_PATH``),
constructs the FastAPI app, and serves it via uvicorn on the
configured port. Bound to 127.0.0.1 — the relay is reached from the
public internet through the nginx + Cloudflare-tunnel layer in front
of it, never directly.
"""
from __future__ import annotations

import argparse
import logging

import uvicorn

from dialekt.relay.config import load_config
from dialekt.relay.server import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dialekt-relay",
        description="dialekt GPU Relay — proxy Ollama inference for tenants.",
    )
    parser.add_argument(
        "--port", type=int, help="Override the port from config / defaults.",
    )
    parser.add_argument(
        "--config", help="Path to relay-server.toml (overrides env + default).",
    )
    args = parser.parse_args(argv)

    config = load_config(args.config) if args.config else load_config()
    if args.port:
        config = config.model_copy(update={"port": args.port})

    logging.basicConfig(
        level=getattr(logging, config.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    app = create_app(config)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=config.port,
        log_level=config.log_level.lower(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
