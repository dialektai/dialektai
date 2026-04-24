"""Passive stdio reader — accepts data but never writes.

Used by the connect-timeout test to simulate an MCP server that
completes the subprocess spawn phase but never answers the
``initialize`` JSON-RPC request. Without a handshake timeout this
would wedge the client forever.
"""
from __future__ import annotations

import sys


def main() -> None:
    try:
        while True:
            chunk = sys.stdin.readline()
            if not chunk:
                break
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
