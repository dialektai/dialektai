"""
LLM routing resolver — converts a settings dict into the (model, api_base,
api_key, extra_kwargs) tuple consumed by ``open_interpreter`` (which wraps
litellm under the hood).

This is the single source of truth for "given user's choice, how do we
configure the interpreter?". Both ``make_interpreter`` and the
``POST /settings`` patch handler MUST go through here — otherwise a cloud
selection silently reverts to ``ollama_chat/<model>`` after each save.
"""
from __future__ import annotations

import time
from typing import TypedDict

from dialekt.llm.catalog import get_provider, CLOUD_PROVIDERS
from dialekt.llm._plugin_context import get_context
from dialekt.secrets import get_secret


OLLAMA_LOCAL_BASE = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "gemma3:12b"


def _ollama_target():
    """Current inference target for Ollama-shaped calls.

    Honours GPU Relay mode (Cloud-Assisted tier): when the active
    PluginContext has ``relay_url`` + ``relay_api_key`` set, returns
    the relay endpoint + Bearer header. Otherwise local Ollama.
    """
    return get_context().inference_target()

# Cache of installed Ollama models (5s TTL). Used by _ollama_canonical to
# prefer the user's literal model name over the legacy mangle when the
# literal exists in Ollama.
_OLLAMA_TAGS_CACHE: dict = {"ts": 0.0, "names": frozenset()}
_OLLAMA_TAGS_TTL = 5.0


def _installed_ollama_tags() -> frozenset:
    """Best-effort sync fetch of /api/tags. On any failure returns the
    last-known set (so the legacy canonical mangle still applies — the
    fallback path remains intact for cold start / offline pilots).

    Honours relay mode: when Cloud GPU is enabled the call goes to the
    relay's /api/tags alias with the Bearer header. Either way the
    response shape is identical (Ollama-compatible).
    """
    now = time.monotonic()
    if now - _OLLAMA_TAGS_CACHE["ts"] < _OLLAMA_TAGS_TTL:
        return _OLLAMA_TAGS_CACHE["names"]
    try:
        import httpx
        target = _ollama_target()
        r = httpx.get(target.url("/api/tags"), headers=target.headers, timeout=0.4)
        if r.status_code == 200:
            data = r.json()
            names = {m.get("name", "") for m in data.get("models", [])}
            names |= {n.split(":", 1)[0] for n in names if ":" in n}
            _OLLAMA_TAGS_CACHE["names"] = frozenset(n for n in names if n)
            _OLLAMA_TAGS_CACHE["ts"] = now
            return _OLLAMA_TAGS_CACHE["names"]
    except Exception:
        pass
    return _OLLAMA_TAGS_CACHE["names"]


class ResolvedModel(TypedDict):
    model: str
    api_base: str | None
    api_key: str | None
    extra: dict
    provider: str
    is_local: bool


def _provider_secret(provider_id: str, field: str) -> str | None:
    return get_secret(f"provider_{provider_id}_{field}")


def _ollama_canonical(model: str) -> str:
    """Map old-style ``gemma3-12b`` to ``gemma3:12b`` for litellm.

    Bug-fix v0.26.x: prefer the user's literal model name if Ollama has it
    installed (e.g. ``gemma3-12b:latest`` from a custom pull). Mangling only
    applies when the literal isn't present — preserves migration safety
    while not breaking pilots with non-canonical local installs.
    """
    if ":" in model:
        return model
    installed = _installed_ollama_tags()
    if f"{model}:latest" in installed:
        return f"{model}:latest"
    if model in installed:
        return model
    if "-" in model:
        head, tail = model.rsplit("-", 1)
        if tail and (tail[0].isdigit() or tail in {"latest", "instruct"}):
            return f"{head}:{tail}"
    return model


def resolve_litellm_model(settings: dict) -> ResolvedModel:
    provider_id: str = settings.get("model_provider") or "ollama"
    model: str = settings.get("model") or DEFAULT_OLLAMA_MODEL

    if provider_id == "ollama":
        # Cloud GPU mode swaps api_base to the relay and supplies the
        # Bearer key as ``api_key`` — litellm sends that as the
        # Authorization header on its outbound /api/chat call. The
        # rest of OI's ollama_chat machinery is unchanged.
        target = _ollama_target()
        return {
            "model": f"ollama_chat/{_ollama_canonical(model)}",
            "api_base": target.base_url,
            "api_key": target.api_key,
            "extra": {},
            "provider": "ollama",
            "is_local": not target.is_relay,
        }

    provider = get_provider(provider_id)
    if provider is None:
        target = _ollama_target()
        return {
            "model": f"ollama_chat/{_ollama_canonical(DEFAULT_OLLAMA_MODEL)}",
            "api_base": target.base_url,
            "api_key": target.api_key,
            "extra": {},
            "provider": "ollama",
            "is_local": not target.is_relay,
        }

    model_str = f"{provider.litellm_prefix}{model}"
    api_key = _provider_secret(provider.id, "api_key")
    api_base = provider.base_url
    extra: dict = {}

    if provider.id == "azure":
        api_base = _provider_secret("azure", "endpoint") or api_base
        api_version = _provider_secret("azure", "api_version") or "2024-10-21"
        deployment = _provider_secret("azure", "deployment")
        if deployment:
            model_str = f"azure/{deployment}"
        extra["api_version"] = api_version

    elif provider.id == "bedrock":
        access_key = _provider_secret("bedrock", "access_key_id")
        secret_key = _provider_secret("bedrock", "secret_access_key")
        region = _provider_secret("bedrock", "region") or "us-east-1"
        session_token = _provider_secret("bedrock", "session_token")
        if access_key:
            extra["aws_access_key_id"] = access_key
        if secret_key:
            extra["aws_secret_access_key"] = secret_key
        if region:
            extra["aws_region_name"] = region
        if session_token:
            extra["aws_session_token"] = session_token
        api_key = None

    elif provider.id == "vertex_ai":
        sa_json = _provider_secret("vertex_ai", "service_account_json")
        project_id = _provider_secret("vertex_ai", "project_id")
        location = _provider_secret("vertex_ai", "location") or "us-central1"
        if sa_json:
            extra["vertex_credentials"] = sa_json
        if project_id:
            extra["vertex_project"] = project_id
        if location:
            extra["vertex_location"] = location
        api_key = None

    elif provider.id == "openai":
        org = _provider_secret("openai", "organization")
        if org:
            extra["organization"] = org

    return {
        "model": model_str,
        "api_base": api_base,
        "api_key": api_key,
        "extra": extra,
        "provider": provider.id,
        "is_local": False,
    }


def apply_to_interpreter(interpreter, resolved: ResolvedModel) -> None:
    interpreter.llm.model = resolved["model"]
    interpreter.llm.api_base = resolved["api_base"]
    interpreter.llm.api_key = resolved["api_key"] or None
    if resolved["extra"]:
        try:
            interpreter.llm.completion_params = dict(resolved["extra"])
        except Exception:
            pass


def has_credentials(provider_id: str) -> bool:
    provider = get_provider(provider_id)
    if provider is None:
        return False

    if provider.auth_kind in ("api_key", "bearer_token"):
        if provider.id == "azure":
            return all(
                _provider_secret("azure", f) for f in ("api_key", "endpoint", "deployment")
            )
        return bool(_provider_secret(provider.id, "api_key"))

    if provider.auth_kind == "aws_iam":
        return all(
            _provider_secret(provider.id, f)
            for f in ("access_key_id", "secret_access_key")
        )

    if provider.auth_kind == "vertex_sa":
        return all(
            _provider_secret(provider.id, f)
            for f in ("service_account_json", "project_id")
        )

    return False


def providers_with_status() -> list[dict]:
    return [
        {
            "id": p.id,
            "name": p.name,
            "blurb": p.blurb,
            "auth_kind": p.auth_kind,
            "auth_fields": list(p.auth_fields),
            "configured": has_credentials(p.id),
            "free_tier": p.free_tier,
            "requires_org": p.requires_org,
        }
        for p in CLOUD_PROVIDERS
    ]
