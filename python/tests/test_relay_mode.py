"""Tests for PluginContext relay mode + resolver/few-shot consumption
(Commit 5).

Covers:
  - PluginContext.inference_target() shape (local vs relay)
  - resolver.resolve_litellm_model() honours relay mode for ollama
  - few_shot_memory._embed() routes through the relay
  - python/server.py _build_plugin_context() reads relay.toml correctly
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from dialekt.llm._plugin_context import (
    InferenceTarget,
    PluginContext,
    set_context,
    _reset_context_for_testing,
)


@pytest.fixture(autouse=True)
def _reset_ctx():
    """Reset the module singleton between tests so set_context calls
    don't leak across cases."""
    _reset_context_for_testing()
    yield
    _reset_context_for_testing()


# ── PluginContext.inference_target ────────────────────────────────────────


def test_default_context_targets_local_ollama():
    ctx = PluginContext()
    target = ctx.inference_target()
    assert target.is_relay is False
    assert target.base_url == "http://localhost:11434"
    assert target.headers == {}
    assert target.api_key is None


def test_relay_context_targets_relay_with_bearer():
    ctx = PluginContext(
        relay_url="https://gpu-relay.dias.now",
        relay_api_key="dlk_relay_xyz",
    )
    target = ctx.inference_target()
    assert target.is_relay is True
    assert target.base_url == "https://gpu-relay.dias.now"
    assert target.headers == {"Authorization": "Bearer dlk_relay_xyz"}
    assert target.api_key == "dlk_relay_xyz"


def test_relay_disabled_when_only_url_set():
    """A URL without a key is half-configured — fall back to local
    rather than send unauthenticated traffic to a remote host."""
    ctx = PluginContext(relay_url="https://gpu-relay.dias.now")
    assert ctx.inference_target().is_relay is False


def test_relay_disabled_when_only_key_set():
    ctx = PluginContext(relay_api_key="dlk_relay_xyz")
    assert ctx.inference_target().is_relay is False


def test_inference_target_url_composes_path():
    target = InferenceTarget(base_url="https://gpu-relay.dias.now")
    assert target.url("/api/tags") == "https://gpu-relay.dias.now/api/tags"
    assert target.url("api/chat") == "https://gpu-relay.dias.now/api/chat"


def test_describe_surfaces_relay_flag():
    ctx = PluginContext(
        relay_url="https://gpu-relay.dias.now",
        relay_api_key="dlk_relay_xyz",
    )
    info = ctx.describe()
    assert info["relay_enabled"] is True


# ── resolver consumes inference_target ────────────────────────────────────


def test_resolver_routes_to_relay_when_enabled():
    """When the active PluginContext has a relay configured, the
    resolved litellm config points at the relay URL with the Bearer
    as api_key — litellm sends that as the Authorization header on
    its outbound /api/chat call."""
    set_context(PluginContext(
        relay_url="https://gpu-relay.dias.now",
        relay_api_key="dlk_relay_secret",
    ))
    from dialekt.llm.resolver import resolve_litellm_model
    resolved = resolve_litellm_model({"model_provider": "ollama", "model": "llama3"})
    assert resolved["api_base"] == "https://gpu-relay.dias.now"
    assert resolved["api_key"] == "dlk_relay_secret"
    assert resolved["is_local"] is False


def test_resolver_local_when_no_relay():
    set_context(PluginContext())
    from dialekt.llm.resolver import resolve_litellm_model
    resolved = resolve_litellm_model({"model_provider": "ollama", "model": "llama3"})
    assert resolved["api_base"] == "http://localhost:11434"
    assert resolved["api_key"] is None
    assert resolved["is_local"] is True


# ── _installed_ollama_tags routes through inference_target ────────────────


def test_installed_tags_uses_relay_url(monkeypatch):
    """Verifies the canonical-mangle helper routes through the relay
    when Cloud GPU is on."""
    set_context(PluginContext(
        relay_url="https://gpu-relay.dias.now",
        relay_api_key="dlk_relay_secret",
    ))
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return httpx.Response(200, json={"models": []})

    monkeypatch.setattr(httpx, "get", fake_get)
    # Reset the resolver's tag cache to force a fresh fetch.
    from dialekt.llm import resolver as resolver_mod
    resolver_mod._OLLAMA_TAGS_CACHE.update({"ts": 0.0, "names": frozenset()})

    resolver_mod._installed_ollama_tags()

    assert captured["url"] == "https://gpu-relay.dias.now/api/tags"
    assert captured["headers"]["Authorization"] == "Bearer dlk_relay_secret"


# ── few_shot_memory._embed routes through inference_target ────────────────


@pytest.mark.asyncio
async def test_few_shot_embed_routes_through_relay(monkeypatch):
    set_context(PluginContext(
        relay_url="https://gpu-relay.dias.now",
        relay_api_key="dlk_relay_secret",
    ))
    captured = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"embeddings": [[0.1, 0.2, 0.3]]}

    class FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    from dialekt.llm.few_shot_memory import _embed
    result = await _embed("hello world")

    assert result == [0.1, 0.2, 0.3]
    assert captured["url"] == "https://gpu-relay.dias.now/api/embed"
    assert captured["headers"]["Authorization"] == "Bearer dlk_relay_secret"


# ── server.py _build_plugin_context ────────────────────────────────────────


def test_build_plugin_context_picks_up_relay_toml(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    import server as srv
    monkeypatch.setattr(srv, "DIALEKT_DIR", tmp_path / ".dialekt")
    monkeypatch.setattr(
        srv, "RELAY_CONFIG_FILE", tmp_path / ".dialekt" / "relay.toml",
    )
    (tmp_path / ".dialekt").mkdir(parents=True, exist_ok=True)

    # No file → local mode
    pc_local = srv._build_plugin_context(srv.app)
    assert pc_local.inference_target().is_relay is False

    # Save toml → relay mode
    srv.save_relay_config({
        "url": "https://gpu-relay.dias.now",
        "api_key": "dlk_relay_xyz",
        "enabled": True,
    })
    pc_relay = srv._build_plugin_context(srv.app)
    assert pc_relay.inference_target().is_relay is True
    assert pc_relay.relay_url == "https://gpu-relay.dias.now"


def test_build_plugin_context_skips_when_disabled_flag(tmp_path, monkeypatch):
    """`enabled = false` means use local even if URL+key are present —
    matches the UI's mental model where the toggle is the source of truth."""
    monkeypatch.setenv("HOME", str(tmp_path))
    import server as srv
    monkeypatch.setattr(srv, "DIALEKT_DIR", tmp_path / ".dialekt")
    monkeypatch.setattr(
        srv, "RELAY_CONFIG_FILE", tmp_path / ".dialekt" / "relay.toml",
    )
    (tmp_path / ".dialekt").mkdir(parents=True, exist_ok=True)

    srv.save_relay_config({
        "url": "https://gpu-relay.dias.now",
        "api_key": "dlk_relay_xyz",
        "enabled": False,
    })
    pc = srv._build_plugin_context(srv.app)
    assert pc.inference_target().is_relay is False
