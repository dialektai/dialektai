"""dialekt GPU Relay — proxy Ollama inference for tenants without a GPU.

The relay runs on the dialekt server (RTX 3060, Almaty KZ), forwards
inference requests from authenticated tenants to a local Ollama
instance, and records token usage for billing. Stateless — no prompts
or responses are persisted, only counts and timestamps.

See docs/GPU_RELAY.md for architecture and the operator runbook.
"""

__version__ = "0.1.0"
