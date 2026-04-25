"""
LLM catalog — single source of truth for Ollama model list and cloud providers.

Two registries:

- ``OLLAMA_MODELS`` — curated list of locally-runnable Ollama models with
  metadata used by the onboarding picker (RAM fit, category, blurb).
- ``CLOUD_PROVIDERS`` — cloud LLM providers with auth shape, litellm prefix,
  and recommended model IDs.

Both feed ``GET /llm/catalog`` consumed by the OnboardingScreen and the
SettingsScreen model picker. The litellm prefix is the routing key for
open-interpreter (which wraps litellm) — see ``resolve_litellm_model`` in
``resolver.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal


OllamaCategory = Literal[
    "general", "coding", "vision", "reasoning",
    "embedding", "lightweight", "frontier",
]

ProviderAuthKind = Literal["api_key", "bearer_token", "aws_iam", "vertex_sa"]


@dataclass(frozen=True)
class OllamaModel:
    name: str
    tag: str
    vendor: str
    blurb: str
    size_gb: float
    ram_gb: int
    ctx: str
    categories: tuple[OllamaCategory, ...]

    @property
    def full(self) -> str:
        return f"{self.name}:{self.tag}"


OLLAMA_MODELS: tuple[OllamaModel, ...] = (
    OllamaModel("gpt-oss",     "120b",                "OpenAI · via Ollama",
                "OpenAI's open-weights frontier model. Reasoning + agentic tools.",
                65.0, 96, "128k", ("frontier", "reasoning")),
    OllamaModel("gpt-oss",     "20b",                 "OpenAI · via Ollama",
                "OpenAI's smaller open-weights model. Strong reasoning under 20B.",
                14.0, 24, "128k", ("reasoning", "general")),
    OllamaModel("deepseek-v3", "671b-q4_K_M",         "DeepSeek · via Ollama",
                "Frontier-tier MoE. Exceeds typical desktop memory.",
                404.0, 512, "160k", ("frontier", "reasoning")),
    OllamaModel("deepseek-r1", "70b",                 "DeepSeek · via Ollama",
                "Extended thinking. Slow but strong on planning.",
                40.0, 64, "128k", ("reasoning",)),
    OllamaModel("deepseek-r1", "14b",                 "DeepSeek · via Ollama",
                "R1 reasoning at desktop scale. Math + logic.",
                9.0, 16, "128k", ("reasoning",)),
    OllamaModel("deepseek-r1", "8b",                  "DeepSeek · via Ollama",
                "R1 reasoning, lightweight. Math + chain-of-thought.",
                5.2, 12, "128k", ("reasoning", "lightweight")),
    OllamaModel("qwen3",       "32b",                 "Alibaba · via Ollama",
                "Qwen 3 — strong multilingual reasoning, 256k context.",
                19.0, 32, "256k", ("general", "reasoning")),
    OllamaModel("qwen3",       "14b",                 "Alibaba · via Ollama",
                "Qwen 3 mid-size. Best balance of quality and speed.",
                9.3, 16, "128k", ("general", "reasoning")),
    OllamaModel("qwen3",       "8b",                  "Alibaba · via Ollama",
                "Qwen 3 daily driver. Multilingual, tool-use.",
                5.2, 12, "40k", ("general",)),
    OllamaModel("llama4",      "scout",               "Meta · via Ollama",
                "Llama 4 Scout — efficient MoE, native multimodal.",
                49.0, 64, "1M", ("general", "vision", "frontier")),
    OllamaModel("llama3.3",    "70b",                 "Meta · via Ollama",
                "Llama 3.3 — best 70B all-rounder, full tool-use.",
                42.0, 48, "128k", ("general", "reasoning")),
    OllamaModel("llama3.1",    "8b",                  "Meta · via Ollama",
                "Llama 3.1 8B — proven daily driver.",
                4.9, 8, "128k", ("general",)),
    OllamaModel("glm-4.6",     "9b",                  "Zhipu · via Ollama",
                "GLM-4.6 — agentic, tool-use, long context.",
                6.0, 12, "200k", ("general", "reasoning")),
    OllamaModel("mistral-nemo", "12b-instruct-q6_K",  "Mistral · via Ollama",
                "Balanced quality at moderate RAM. Good daily driver.",
                9.1, 14, "128k", ("general",)),
    OllamaModel("mistral-small", "24b",               "Mistral · via Ollama",
                "Mistral Small 3 — Apache-2, strong instruction following.",
                14.0, 28, "32k", ("general",)),
    OllamaModel("gemma3",      "27b",                 "Google · via Ollama",
                "Gemma 3 — strong open multimodal, vision included.",
                17.0, 32, "128k", ("general", "vision")),
    OllamaModel("gemma3",      "12b",                 "Google · via Ollama",
                "Gemma 3 mid-size. Vision-capable, balanced.",
                8.1, 14, "128k", ("general", "vision")),
    OllamaModel("gemma3",      "4b",                  "Google · via Ollama",
                "Gemma 3 small. Vision-capable on modest hardware.",
                3.3, 6, "128k", ("lightweight", "vision")),
    OllamaModel("phi4",        "14b",                 "Microsoft · via Ollama",
                "Phi-4 — efficient reasoning and logic.",
                9.1, 14, "16k", ("reasoning", "general")),
    OllamaModel("granite3.2",  "8b",                  "IBM · via Ollama",
                "IBM Granite 3.2 — enterprise-friendly, RAG-tuned.",
                4.9, 10, "128k", ("general",)),
    OllamaModel("qwen2.5-coder", "32b-instruct-q5_K_M", "Alibaba · via Ollama",
                "Best open code model. SQL + multi-file refactor.",
                22.8, 28, "128k", ("coding", "frontier")),
    OllamaModel("qwen2.5-coder", "14b",                "Alibaba · via Ollama",
                "Coder 14B — strong patches, fast loops.",
                9.0, 16, "128k", ("coding",)),
    OllamaModel("qwen2.5-coder", "7b-instruct-q4_K_M", "Alibaba · via Ollama",
                "Coder 7B — runs on modest hardware.",
                4.7, 8, "128k", ("coding", "lightweight")),
    OllamaModel("deepseek-coder-v2", "16b",            "DeepSeek · via Ollama",
                "DeepSeek Coder V2 — repo-aware code generation.",
                9.0, 16, "128k", ("coding",)),
    OllamaModel("llama3.2-vision", "11b-q4_K_M",       "Meta · via Ollama",
                "Reads screenshots, PDFs, diagrams. Pair with text model.",
                7.2, 11, "32k", ("vision",)),
    OllamaModel("llama3.2-vision", "90b",              "Meta · via Ollama",
                "Frontier vision. Heavy.",
                55.0, 96, "32k", ("vision", "frontier")),
    OllamaModel("llava",       "13b",                  "LLaVA · via Ollama",
                "LLaVA 1.6 — open vision baseline.",
                7.4, 14, "8k", ("vision",)),
    OllamaModel("nomic-embed-text", "v1.5",            "Nomic · via Ollama",
                "Best-in-class open embeddings. Outperforms text-embedding-3-small.",
                0.27, 2, "2k", ("embedding",)),
    OllamaModel("mxbai-embed-large", "335m",           "Mixedbread · via Ollama",
                "Strong English embeddings. Drop-in for OpenAI ada-002.",
                0.67, 2, "512", ("embedding",)),
    OllamaModel("bge-m3",      "567m",                 "BAAI · via Ollama",
                "Multilingual embeddings, long-context capable.",
                1.2, 3, "8k", ("embedding",)),
    OllamaModel("llama3.2",    "3b",                   "Meta · via Ollama",
                "Llama 3.2 3B — runs anywhere, surprisingly capable.",
                2.0, 4, "128k", ("lightweight", "general")),
    OllamaModel("qwen3",       "0.6b",                 "Alibaba · via Ollama",
                "Tiny model. Runs on low-end laptops, draft-tier.",
                0.52, 2, "40k", ("lightweight",)),
    OllamaModel("gemma2",      "2b-q4_0",              "Google · via Ollama",
                "Tiny Gemma. Fast on any hardware.",
                1.6, 4, "8k", ("lightweight",)),
)


@dataclass(frozen=True)
class ProviderModel:
    id: str
    label: str
    blurb: str
    ctx: str
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class CloudProvider:
    id: str
    name: str
    blurb: str
    auth_kind: ProviderAuthKind
    auth_fields: tuple[str, ...]
    litellm_prefix: str
    base_url: str | None
    docs_url: str
    models: tuple[ProviderModel, ...]
    privacy_note: str
    free_tier: bool = False
    requires_org: bool = False
    notes: str = ""


CLOUD_PROVIDERS: tuple[CloudProvider, ...] = (
    CloudProvider(
        id="anthropic", name="Anthropic", blurb="Claude — frontier reasoning, long context, tool use.",
        auth_kind="api_key", auth_fields=("api_key",),
        litellm_prefix="anthropic/", base_url=None,
        docs_url="https://docs.anthropic.com/en/api/getting-started",
        privacy_note="Prompts and responses are sent to Anthropic. Default 30-day retention; opt-out for paid tier.",
        models=(
            ProviderModel("claude-opus-4-7", "Claude Opus 4.7", "Frontier model. Best reasoning + agentic.", "200k", ("reasoning", "agents")),
            ProviderModel("claude-sonnet-4-6", "Claude Sonnet 4.6", "Workhorse. Fast, strong, cost-effective.", "200k", ("general",)),
            ProviderModel("claude-haiku-4-5-20251001", "Claude Haiku 4.5", "Fastest, cheapest. Good for high-volume tools.", "200k", ("fast",)),
        ),
    ),
    CloudProvider(
        id="openai", name="OpenAI", blurb="GPT-4/o-series — industry default.",
        auth_kind="api_key", auth_fields=("api_key", "organization"),
        litellm_prefix="openai/", base_url=None,
        docs_url="https://platform.openai.com/docs/api-reference",
        privacy_note="Sent to OpenAI. API tier excluded from training by default.",
        models=(
            ProviderModel("gpt-4o", "GPT-4o", "Multimodal, fast, broadly capable.", "128k", ("general", "vision")),
            ProviderModel("gpt-4-turbo", "GPT-4 Turbo", "Long context, JSON mode, tool use.", "128k", ("general",)),
            ProviderModel("o1", "o1", "Reasoning model — slow, strong on hard problems.", "200k", ("reasoning",)),
            ProviderModel("o1-mini", "o1-mini", "Cheaper reasoning model.", "128k", ("reasoning", "fast")),
            ProviderModel("gpt-4o-mini", "GPT-4o mini", "Cheap workhorse, vision capable.", "128k", ("fast", "vision")),
        ),
    ),
    CloudProvider(
        id="gemini", name="Google Gemini", blurb="Gemini 2.5 — multimodal, huge context, free tier.",
        auth_kind="api_key", auth_fields=("api_key",),
        litellm_prefix="gemini/", base_url=None,
        docs_url="https://ai.google.dev/api",
        free_tier=True,
        privacy_note="Sent to Google AI Studio. Free tier may be used for training; paid tier excluded.",
        models=(
            ProviderModel("gemini-2.5-pro", "Gemini 2.5 Pro", "Frontier multimodal. 2M context.", "2M", ("reasoning", "vision")),
            ProviderModel("gemini-2.5-flash", "Gemini 2.5 Flash", "Fast multimodal workhorse.", "1M", ("general", "vision", "fast")),
            ProviderModel("gemini-2.5-flash-lite", "Gemini 2.5 Flash Lite", "Cheapest tier, fast.", "1M", ("fast",)),
            ProviderModel("gemini-2.0-flash", "Gemini 2.0 Flash", "Previous-gen Flash, still strong.", "1M", ("general",)),
        ),
    ),
    CloudProvider(
        id="vertex_ai", name="Google Vertex AI", blurb="Gemini + 3rd-party models with GCP IAM and compliance.",
        auth_kind="vertex_sa", auth_fields=("service_account_json", "project_id", "location"),
        litellm_prefix="vertex_ai/", base_url=None,
        docs_url="https://cloud.google.com/vertex-ai/generative-ai/docs/model-reference/inference",
        requires_org=True,
        privacy_note="Enterprise GCP. Excluded from training. Regional residency available.",
        models=(
            ProviderModel("gemini-2.5-pro", "Gemini 2.5 Pro (Vertex)", "Same as AI Studio, GCP IAM-controlled.", "2M", ("reasoning",)),
            ProviderModel("gemini-2.5-flash", "Gemini 2.5 Flash (Vertex)", "Workhorse via Vertex.", "1M", ("general",)),
            ProviderModel("claude-sonnet-4@20250619", "Claude Sonnet 4 (Vertex)", "Anthropic via Vertex.", "200k", ("general",)),
        ),
    ),
    CloudProvider(
        id="bedrock", name="AWS Bedrock", blurb="100+ models with AWS IAM, compliance, regions.",
        auth_kind="aws_iam",
        auth_fields=("access_key_id", "secret_access_key", "region", "session_token"),
        litellm_prefix="bedrock/", base_url=None,
        docs_url="https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html",
        requires_org=True,
        privacy_note="AWS Bedrock — data stays in your AWS account, region of choice.",
        models=(
            ProviderModel("anthropic.claude-opus-4-7-v1:0", "Claude Opus 4.7", "Anthropic via Bedrock.", "200k", ("reasoning",)),
            ProviderModel("anthropic.claude-sonnet-4-6-v1:0", "Claude Sonnet 4.6", "Workhorse Anthropic via Bedrock.", "200k", ("general",)),
            ProviderModel("amazon.nova-pro-v1:0", "Amazon Nova Pro", "AWS-native multimodal flagship.", "300k", ("general", "vision")),
            ProviderModel("meta.llama3-3-70b-instruct-v1:0", "Llama 3.3 70B", "Meta via Bedrock.", "128k", ("general",)),
            ProviderModel("deepseek.deepseek-v3-v1:0", "DeepSeek V3", "DeepSeek via Bedrock.", "160k", ("reasoning",)),
        ),
    ),
    CloudProvider(
        id="azure", name="Azure OpenAI", blurb="GPT-4/o on Azure with enterprise compliance.",
        auth_kind="api_key",
        auth_fields=("api_key", "endpoint", "api_version", "deployment"),
        litellm_prefix="azure/", base_url=None,
        docs_url="https://learn.microsoft.com/en-us/azure/ai-services/openai/",
        requires_org=True,
        privacy_note="Microsoft Azure — regional residency, enterprise compliance, no training.",
        models=(
            ProviderModel("gpt-4o", "GPT-4o (Azure)", "Use your Azure deployment name.", "128k", ("general",)),
            ProviderModel("gpt-4-turbo", "GPT-4 Turbo (Azure)", "Long context.", "128k", ("general",)),
            ProviderModel("o1", "o1 (Azure)", "Reasoning model.", "200k", ("reasoning",)),
        ),
    ),
    CloudProvider(
        id="nvidia_nim", name="NVIDIA NIM", blurb="build.nvidia.com — open-weights frontier on NVIDIA inference.",
        auth_kind="bearer_token", auth_fields=("api_key",),
        litellm_prefix="nvidia_nim/",
        base_url="https://integrate.api.nvidia.com/v1",
        docs_url="https://build.nvidia.com/explore/discover",
        privacy_note="NVIDIA-hosted inference. Free tier with rate limits; enterprise tier available.",
        free_tier=True,
        models=(
            ProviderModel("meta/llama-3.3-70b-instruct", "Llama 3.3 70B", "Meta via NVIDIA NIM.", "128k", ("general",)),
            ProviderModel("deepseek-ai/deepseek-r1", "DeepSeek R1", "Reasoning, fast NVIDIA inference.", "128k", ("reasoning",)),
            ProviderModel("qwen/qwen2.5-coder-32b-instruct", "Qwen2.5 Coder 32B", "Best open coder.", "32k", ("coding",)),
            ProviderModel("nvidia/nemotron-4-340b-instruct", "Nemotron 4 340B", "NVIDIA-tuned frontier.", "4k", ("frontier",)),
        ),
    ),
    CloudProvider(
        id="mistral", name="Mistral La Plateforme", blurb="Mistral's own hosted API.",
        auth_kind="bearer_token", auth_fields=("api_key",),
        litellm_prefix="mistral/", base_url=None,
        docs_url="https://docs.mistral.ai/api/",
        privacy_note="Sent to Mistral. EU-hosted, GDPR-aligned.",
        models=(
            ProviderModel("mistral-large-latest", "Mistral Large", "Flagship reasoning.", "128k", ("reasoning",)),
            ProviderModel("mistral-small-latest", "Mistral Small 3", "Cheap workhorse.", "32k", ("general",)),
            ProviderModel("codestral-latest", "Codestral", "Coding specialist.", "32k", ("coding",)),
            ProviderModel("magistral-medium-latest", "Magistral Medium", "Reasoning model.", "40k", ("reasoning",)),
        ),
    ),
    CloudProvider(
        id="deepseek", name="DeepSeek", blurb="DeepSeek's own API — frontier reasoning at low cost.",
        auth_kind="bearer_token", auth_fields=("api_key",),
        litellm_prefix="deepseek/",
        base_url="https://api.deepseek.com",
        docs_url="https://api-docs.deepseek.com/",
        privacy_note="Sent to DeepSeek (China). Review compliance if regulated.",
        models=(
            ProviderModel("deepseek-chat", "DeepSeek V3", "Workhorse general model.", "128k", ("general",)),
            ProviderModel("deepseek-reasoner", "DeepSeek R1", "Extended reasoning.", "128k", ("reasoning",)),
        ),
    ),
    CloudProvider(
        id="xai", name="xAI Grok", blurb="Grok — real-time-aware, X integration.",
        auth_kind="bearer_token", auth_fields=("api_key",),
        litellm_prefix="xai/",
        base_url="https://api.x.ai/v1",
        docs_url="https://docs.x.ai/docs",
        privacy_note="Sent to xAI. May be used for training unless opted out.",
        models=(
            ProviderModel("grok-4", "Grok 4", "Frontier Grok.", "256k", ("reasoning",)),
            ProviderModel("grok-3", "Grok 3", "Workhorse Grok.", "128k", ("general",)),
            ProviderModel("grok-3-mini", "Grok 3 mini", "Cheap fast tier.", "128k", ("fast",)),
        ),
    ),
    CloudProvider(
        id="cohere", name="Cohere", blurb="Command R+ for RAG, multilingual, enterprise.",
        auth_kind="bearer_token", auth_fields=("api_key",),
        litellm_prefix="cohere/", base_url=None,
        docs_url="https://docs.cohere.com/reference/about",
        privacy_note="Sent to Cohere. Enterprise data not used for training.",
        models=(
            ProviderModel("command-a-03-2025", "Command A", "Latest flagship, RAG-optimized.", "256k", ("general",)),
            ProviderModel("command-r-plus", "Command R+", "Enterprise RAG.", "128k", ("general",)),
            ProviderModel("c4ai-aya-expanse-32b", "Aya Expanse 32B", "Multilingual specialist.", "128k", ("general",)),
        ),
    ),
    CloudProvider(
        id="groq", name="Groq", blurb="Fastest inference — LPU-accelerated, OpenAI-compatible.",
        auth_kind="bearer_token", auth_fields=("api_key",),
        litellm_prefix="groq/", base_url=None,
        docs_url="https://console.groq.com/docs",
        free_tier=True,
        privacy_note="Sent to Groq. No training on API data.",
        models=(
            ProviderModel("llama-3.3-70b-versatile", "Llama 3.3 70B", "Sub-second responses.", "128k", ("general", "fast")),
            ProviderModel("openai/gpt-oss-120b", "gpt-oss-120b", "OpenAI open-weights at Groq speed.", "128k", ("reasoning", "fast")),
            ProviderModel("openai/gpt-oss-20b", "gpt-oss-20b", "Smaller gpt-oss, very fast.", "128k", ("fast",)),
            ProviderModel("deepseek-r1-distill-llama-70b", "DeepSeek R1 distill 70B", "Reasoning, fast.", "128k", ("reasoning",)),
        ),
    ),
    CloudProvider(
        id="together_ai", name="Together AI", blurb="100+ open-source models on shared GPUs.",
        auth_kind="bearer_token", auth_fields=("api_key",),
        litellm_prefix="together_ai/", base_url=None,
        docs_url="https://docs.together.ai/docs/introduction",
        privacy_note="Sent to Together AI. No training on API data.",
        models=(
            ProviderModel("meta-llama/Llama-3.3-70B-Instruct-Turbo", "Llama 3.3 70B", "Speed-optimised Llama.", "128k", ("general",)),
            ProviderModel("Qwen/Qwen3-235B-A22B-Instruct-2507-tput", "Qwen 3 235B", "Frontier MoE.", "256k", ("reasoning",)),
            ProviderModel("deepseek-ai/DeepSeek-V3", "DeepSeek V3", "Frontier MoE general.", "128k", ("general",)),
            ProviderModel("openai/gpt-oss-120b", "gpt-oss-120b", "OpenAI open-weights.", "128k", ("reasoning",)),
        ),
    ),
    CloudProvider(
        id="fireworks_ai", name="Fireworks AI", blurb="Fast serverless inference, fine-tuning.",
        auth_kind="bearer_token", auth_fields=("api_key",),
        litellm_prefix="fireworks_ai/", base_url=None,
        docs_url="https://docs.fireworks.ai/",
        privacy_note="Sent to Fireworks. No training on API data.",
        models=(
            ProviderModel("accounts/fireworks/models/llama-v3p3-70b-instruct", "Llama 3.3 70B", "Fast serverless Llama.", "128k", ("general",)),
            ProviderModel("accounts/fireworks/models/deepseek-v3", "DeepSeek V3", "Frontier general.", "128k", ("general",)),
            ProviderModel("accounts/fireworks/models/qwen3-235b-a22b", "Qwen 3 235B", "Frontier MoE.", "256k", ("reasoning",)),
        ),
    ),
    CloudProvider(
        id="perplexity", name="Perplexity", blurb="Web-grounded search + chat in one API.",
        auth_kind="bearer_token", auth_fields=("api_key",),
        litellm_prefix="perplexity/",
        base_url="https://api.perplexity.ai",
        docs_url="https://docs.perplexity.ai/",
        privacy_note="Sent to Perplexity. Search results from live web.",
        models=(
            ProviderModel("sonar-pro", "Sonar Pro", "Search-grounded reasoning.", "200k", ("general",)),
            ProviderModel("sonar", "Sonar", "Search-grounded chat.", "128k", ("general",)),
            ProviderModel("sonar-reasoning-pro", "Sonar Reasoning Pro", "Search + reasoning.", "128k", ("reasoning",)),
        ),
    ),
    CloudProvider(
        id="openrouter", name="OpenRouter", blurb="One API key, 300+ models from every provider.",
        auth_kind="bearer_token", auth_fields=("api_key",),
        litellm_prefix="openrouter/",
        base_url="https://openrouter.ai/api/v1",
        docs_url="https://openrouter.ai/docs",
        privacy_note="Routes via OpenRouter to 30+ underlying providers. Privacy varies — check each route.",
        models=(
            ProviderModel("anthropic/claude-opus-4.7", "Claude Opus 4.7", "Anthropic via OpenRouter.", "200k", ("reasoning",)),
            ProviderModel("openai/gpt-4o", "GPT-4o", "OpenAI via OpenRouter.", "128k", ("general",)),
            ProviderModel("google/gemini-2.5-flash", "Gemini 2.5 Flash", "Google via OpenRouter.", "1M", ("general",)),
            ProviderModel("deepseek/deepseek-r1", "DeepSeek R1", "Reasoning via OpenRouter.", "128k", ("reasoning",)),
            ProviderModel("meta-llama/llama-3.3-70b-instruct", "Llama 3.3 70B", "Meta via OpenRouter.", "128k", ("general",)),
        ),
    ),
    CloudProvider(
        id="cerebras", name="Cerebras", blurb="Wafer-scale chip — fastest LPU/GPU-class inference.",
        auth_kind="bearer_token", auth_fields=("api_key",),
        litellm_prefix="cerebras/", base_url=None,
        docs_url="https://inference-docs.cerebras.ai/",
        free_tier=True,
        privacy_note="Sent to Cerebras. No training on API data.",
        models=(
            ProviderModel("llama-3.3-70b", "Llama 3.3 70B", "1000+ tok/s on wafer-scale.", "128k", ("general", "fast")),
            ProviderModel("llama3.1-70b", "Llama 3.1 70B", "Wafer-scale Llama 3.1.", "128k", ("general", "fast")),
        ),
    ),
    CloudProvider(
        id="replicate", name="Replicate", blurb="Open-source models on demand — text, image, video.",
        auth_kind="bearer_token", auth_fields=("api_key",),
        litellm_prefix="replicate/", base_url=None,
        docs_url="https://replicate.com/docs",
        privacy_note="Sent to Replicate. Mostly open-source models. Pay-per-second pricing.",
        models=(
            ProviderModel("meta/meta-llama-3.1-405b-instruct", "Llama 3.1 405B", "Frontier Llama on demand.", "128k", ("frontier",)),
            ProviderModel("meta/meta-llama-3-70b-instruct", "Llama 3 70B", "Workhorse Llama.", "8k", ("general",)),
        ),
    ),
)


def all_provider_secret_keys() -> tuple[str, ...]:
    return tuple(
        f"provider_{p.id}_{f}"
        for p in CLOUD_PROVIDERS
        for f in p.auth_fields
    )


def get_provider(provider_id: str) -> CloudProvider | None:
    for p in CLOUD_PROVIDERS:
        if p.id == provider_id:
            return p
    return None


def catalog_dict() -> dict:
    return {
        "ollama": [asdict(m) for m in OLLAMA_MODELS],
        "providers": [
            {
                "id": p.id,
                "name": p.name,
                "blurb": p.blurb,
                "auth_kind": p.auth_kind,
                "auth_fields": list(p.auth_fields),
                "base_url": p.base_url,
                "docs_url": p.docs_url,
                "privacy_note": p.privacy_note,
                "free_tier": p.free_tier,
                "requires_org": p.requires_org,
                "notes": p.notes,
                "models": [asdict(m) for m in p.models],
            }
            for p in CLOUD_PROVIDERS
        ],
    }
