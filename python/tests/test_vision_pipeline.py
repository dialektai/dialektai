"""Functional tests for the vision pipeline (describe_image_vision).

Three paths exercised without a live Ollama instance:

1. No vision model installed  → graceful fallback string (no exception).
2. Vision model available     → calls /api/generate → annotated description.
3. Ollama unreachable         → ConnectError caught → fallback string.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from server import describe_image_vision  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def _make_async_client(
    get_return: dict | None = None,
    post_return: dict | None = None,
    raise_on_get: Exception | None = None,
):
    """Return a mock usable as ``async with httpx.AsyncClient(...) as c``."""
    get_resp = MagicMock()
    get_resp.json.return_value = get_return or {}

    post_resp = MagicMock()
    post_resp.json.return_value = post_return or {}

    client = AsyncMock()
    if raise_on_get is not None:
        client.get = AsyncMock(side_effect=raise_on_get)
    else:
        client.get = AsyncMock(return_value=get_resp)
    client.post = AsyncMock(return_value=post_resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


# ---------------------------------------------------------------------------
# Test 1 — no vision model available
# ---------------------------------------------------------------------------

def test_no_vision_model_returns_graceful_fallback(tmp_path):
    """When Ollama reports zero installed models the function returns a
    human-readable fallback and does not raise."""
    img = tmp_path / "screenshot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    client = _make_async_client(get_return={"models": []})
    with patch("httpx.AsyncClient", return_value=client):
        result = run(describe_image_vision(str(img)))

    assert "no vision model available" in result
    assert str(img) in result
    # Must not crash — result is a string, not an exception
    assert isinstance(result, str)


def test_no_vision_model_only_one_ollama_call(tmp_path):
    """Early-exit path must not call /api/generate when there is no model."""
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    client = _make_async_client(get_return={"models": []})
    with patch("httpx.AsyncClient", return_value=client) as MockClient:
        run(describe_image_vision(str(img)))

    # AsyncClient() should be called exactly once (tags lookup only)
    assert MockClient.call_count == 1
    client.post.assert_not_called()


# ---------------------------------------------------------------------------
# Test 2 — vision model found → full describe path
# ---------------------------------------------------------------------------

def test_vision_model_found_returns_annotated_description(tmp_path):
    """When llava is installed /api/generate is called and the response is
    returned with a model-prefixed header."""
    img = tmp_path / "code.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)

    tags_client = _make_async_client(
        get_return={"models": [{"name": "llava:latest"}]}
    )
    gen_client = _make_async_client(
        post_return={"response": "A Python file open in VS Code."}
    )

    with patch("httpx.AsyncClient", side_effect=[tags_client, gen_client]):
        result = run(describe_image_vision(str(img)))

    assert result.startswith("[Screenshot described by llava:latest]")
    assert "A Python file open in VS Code." in result


def test_vision_model_selection_prefers_llava(tmp_path):
    """Among mixed models the first vision-capable one is selected."""
    img = tmp_path / "b.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)

    tags_client = _make_async_client(
        get_return={
            "models": [
                {"name": "qwen2.5-coder:7b"},   # not vision
                {"name": "moondream:latest"},    # vision — should be picked
                {"name": "llava:7b"},
            ]
        }
    )
    gen_client = _make_async_client(post_return={"response": "A dashboard."})

    with patch("httpx.AsyncClient", side_effect=[tags_client, gen_client]) as MockCls:
        result = run(describe_image_vision(str(img)))

    assert "moondream:latest" in result
    # generate call must have included the model name
    call_json = gen_client.post.call_args.kwargs.get("json", {})
    assert call_json.get("model") == "moondream:latest"


# ---------------------------------------------------------------------------
# Test 3 — Ollama unreachable
# ---------------------------------------------------------------------------

def test_ollama_unreachable_returns_fallback(tmp_path):
    """If Ollama is not running the function must swallow the error and
    return the bare path-based fallback — never propagate the exception."""
    img = tmp_path / "err.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    client = _make_async_client(raise_on_get=httpx.ConnectError("connection refused"))
    with patch("httpx.AsyncClient", return_value=client):
        result = run(describe_image_vision(str(img)))

    assert isinstance(result, str)
    assert str(img) in result
    # fallback must NOT embed a Python traceback
    assert "Traceback" not in result
    assert "ConnectError" not in result
