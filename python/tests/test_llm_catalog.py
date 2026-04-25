"""Tests for the LLM catalog and resolver added in v0.21 onboarding refresh."""
from __future__ import annotations

import json
import pytest

from dialekt.llm.catalog import (
    OLLAMA_MODELS,
    CLOUD_PROVIDERS,
    OllamaModel,
    CloudProvider,
    ProviderModel,
    all_provider_secret_keys,
    get_provider,
    catalog_dict,
)
from dialekt.llm.resolver import (
    resolve_litellm_model,
    has_credentials,
    providers_with_status,
    DEFAULT_OLLAMA_MODEL,
    OLLAMA_LOCAL_BASE,
)


# ── Catalog shape ──────────────────────────────────────────────────────────


def test_catalog_has_minimum_models_and_providers():
    """Pilots expect ~30 Ollama models and ~16 providers — keep these bounds."""
    assert len(OLLAMA_MODELS) >= 30, "Ollama catalog shrunk; pilots expect 30+"
    assert len(CLOUD_PROVIDERS) >= 16, "Cloud catalog shrunk; pilots expect 16+"


def test_every_ollama_model_has_required_fields():
    for m in OLLAMA_MODELS:
        assert isinstance(m, OllamaModel)
        assert m.name and m.tag, f"empty name/tag in {m}"
        assert m.size_gb > 0
        assert m.ram_gb > 0
        assert m.ctx
        assert m.categories, f"{m.name}:{m.tag} has no categories"
        # full() property gives canonical "name:tag"
        assert ":" in m.full


def test_every_provider_has_litellm_prefix_and_models():
    for p in CLOUD_PROVIDERS:
        assert p.id and p.name
        assert p.litellm_prefix.endswith("/"), f"{p.id} prefix must end with /"
        assert p.auth_kind in ("api_key", "bearer_token", "aws_iam", "vertex_sa")
        assert p.auth_fields, f"{p.id} has no auth_fields"
        assert p.models, f"{p.id} has no models"
        for m in p.models:
            assert isinstance(m, ProviderModel)
            assert m.id and m.label
            assert m.ctx


def test_provider_ids_are_unique():
    ids = [p.id for p in CLOUD_PROVIDERS]
    assert len(ids) == len(set(ids)), f"duplicate provider ids: {ids}"


def test_all_provider_secret_keys_pattern():
    """Keys must follow provider_<id>_<field> pattern."""
    keys = all_provider_secret_keys()
    assert keys
    for k in keys:
        assert k.startswith("provider_"), k
        # provider_<id>_<field> — at least 3 underscore-separated parts
        parts = k.split("_")
        assert len(parts) >= 3, k


def test_get_provider_lookup():
    assert get_provider("anthropic") is not None
    assert get_provider("anthropic").name == "Anthropic"
    assert get_provider("nonexistent_xyz") is None


def test_catalog_dict_serialises_cleanly():
    """catalog_dict must produce JSON-serialisable output for the API."""
    d = catalog_dict()
    assert "ollama" in d and "providers" in d
    json.dumps(d)  # raises if not serialisable
    assert len(d["ollama"]) == len(OLLAMA_MODELS)
    assert len(d["providers"]) == len(CLOUD_PROVIDERS)


# ── Resolver ───────────────────────────────────────────────────────────────


def test_resolver_default_falls_back_to_ollama():
    """Empty settings → default Ollama model."""
    r = resolve_litellm_model({})
    assert r["provider"] == "ollama"
    assert r["is_local"] is True
    assert r["model"] == f"ollama_chat/{DEFAULT_OLLAMA_MODEL}"
    assert r["api_base"] == OLLAMA_LOCAL_BASE
    assert r["api_key"] is None


def test_resolver_canonicalises_old_style_ollama_tag(monkeypatch):
    """Legacy 'gemma3-12b' → 'gemma3:12b' when Ollama has neither literal nor
    :latest installed (migration-safety fallback path)."""
    from dialekt.llm import resolver as _r
    monkeypatch.setattr(_r, "_installed_ollama_tags", lambda: frozenset())
    r = resolve_litellm_model({"model": "gemma3-12b"})
    assert r["model"] == "ollama_chat/gemma3:12b"


def test_resolver_prefers_literal_when_ollama_has_it(monkeypatch):
    """v0.26.x bug fix: if Ollama has 'gemma3-12b:latest' installed (custom
    pull, non-canonical), the resolver must use that literal name and NOT
    silently mangle to the canonical 'gemma3:12b' which would 404."""
    from dialekt.llm import resolver as _r
    monkeypatch.setattr(_r, "_installed_ollama_tags",
                        lambda: frozenset({"gemma3-12b", "gemma3-12b:latest"}))
    r = resolve_litellm_model({"model": "gemma3-12b"})
    assert r["model"] == "ollama_chat/gemma3-12b:latest"


def test_resolver_preserves_modern_ollama_tag():
    r = resolve_litellm_model({"model": "qwen3:14b"})
    assert r["model"] == "ollama_chat/qwen3:14b"


def test_resolver_anthropic_uses_anthropic_prefix():
    """The P0 bug: model_provider must NOT be silently overwritten with ollama."""
    r = resolve_litellm_model({
        "model_provider": "anthropic",
        "model": "claude-opus-4-7",
    })
    assert r["provider"] == "anthropic"
    assert r["is_local"] is False
    assert r["model"] == "anthropic/claude-opus-4-7"
    assert "ollama" not in r["model"]


def test_resolver_unknown_provider_degrades_to_ollama():
    """Unknown provider id is recoverable — degrade, not crash."""
    r = resolve_litellm_model({
        "model_provider": "made_up_provider",
        "model": "fake-model",
    })
    assert r["provider"] == "ollama"
    assert r["is_local"] is True


def test_resolver_bedrock_returns_aws_extras():
    r = resolve_litellm_model({
        "model_provider": "bedrock",
        "model": "anthropic.claude-opus-4-7-v1:0",
    })
    assert r["model"] == "bedrock/anthropic.claude-opus-4-7-v1:0"
    # Bedrock always provides a region default even without creds saved
    assert "aws_region_name" in r["extra"]


def test_resolver_vertex_returns_vertex_extras():
    r = resolve_litellm_model({
        "model_provider": "vertex_ai",
        "model": "gemini-2.5-pro",
    })
    assert r["model"] == "vertex_ai/gemini-2.5-pro"
    # Vertex always sets a default location even without creds saved
    assert r["extra"].get("vertex_location") == "us-central1"


def test_resolver_azure_uses_deployment_when_set(monkeypatch):
    """Azure substitutes deployment name in the model field if set."""
    from dialekt.llm import resolver as res

    def fake_secret(name):
        return {
            "provider_azure_endpoint": "https://test.openai.azure.com",
            "provider_azure_deployment": "my-gpt4o-deployment",
            "provider_azure_api_version": "2024-10-21",
        }.get(name)

    monkeypatch.setattr(res, "get_secret", fake_secret)

    r = resolve_litellm_model({
        "model_provider": "azure",
        "model": "gpt-4o",
    })
    assert r["model"] == "azure/my-gpt4o-deployment"
    assert r["api_base"] == "https://test.openai.azure.com"
    assert r["extra"].get("api_version") == "2024-10-21"


# ── Credential status ──────────────────────────────────────────────────────


def test_has_credentials_false_when_unset(monkeypatch):
    from dialekt.llm import resolver as res
    monkeypatch.setattr(res, "get_secret", lambda name: None)
    assert has_credentials("anthropic") is False
    assert has_credentials("bedrock") is False


def test_has_credentials_true_for_anthropic_with_api_key(monkeypatch):
    from dialekt.llm import resolver as res
    monkeypatch.setattr(res, "get_secret",
                        lambda name: "sk-test" if name == "provider_anthropic_api_key" else None)
    assert has_credentials("anthropic") is True
    assert has_credentials("openai") is False  # different provider


def test_has_credentials_unknown_provider_false():
    assert has_credentials("nope_xyz") is False


def test_providers_with_status_lists_all(monkeypatch):
    from dialekt.llm import resolver as res
    monkeypatch.setattr(res, "get_secret", lambda name: None)
    out = providers_with_status()
    assert len(out) == len(CLOUD_PROVIDERS)
    for entry in out:
        assert {"id", "name", "blurb", "auth_kind", "configured"}.issubset(entry.keys())
        assert entry["configured"] is False
