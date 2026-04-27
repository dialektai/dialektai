"""Billing for the dialekt GPU Relay.

Per-request rows in ``relay_usage`` (one row per /generate or /chat
call). Token counts come from Ollama's terminal NDJSON chunk:
``prompt_eval_count`` (input) + ``eval_count`` (output). Latency is
measured from when the relay receives the request to when the upstream
stream closes.

Embeddings are not billed: few-shot memory issues many small embed
calls per chat turn, and tracking each one inflates the audit table
without changing the bill in any meaningful way. If embed volume ever
becomes a problem we add a separate counter.

Errors during recording are logged and swallowed — a billing failure
must not turn into an HTTP error for the client. Operator-side audits
catch missing rows.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

from dialekt.relay.auth import RelayKeyContext

log = logging.getLogger("dialekt.relay.billing")


def count_tokens_from_ollama_final_chunk(chunk: dict) -> tuple[int, int]:
    """Pull (prompt_tokens, completion_tokens) from Ollama's terminal
    chunk.

    Either field can be absent on cache hits or aborted generations;
    missing is treated as 0 — caller decides whether to skip recording.
    """
    return (
        int(chunk.get("prompt_eval_count", 0) or 0),
        int(chunk.get("eval_count", 0) or 0),
    )


def find_terminal_chunk(buffer: bytes) -> Optional[dict]:
    """Scan an NDJSON buffer for the last line with ``done: true``.

    Used by the streaming proxy to capture token counts after the
    response winds down. Returns ``None`` if no terminal chunk is
    present (incomplete stream, error response, client disconnect).

    Scans from the bottom — terminal is always at/near the end, so
    we usually parse one or two lines, not the entire transcript.
    """
    for line in reversed(buffer.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("done"):
            return obj
    return None


async def record_usage(
    pool,
    ctx: RelayKeyContext,
    *,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
) -> None:
    """Insert one ``relay_usage`` row + bump
    ``relay_keys.last_used_at``.

    Both writes share a transaction so we never bump last_used_at
    without recording the usage that proves the key is active.
    Caller must catch exceptions if it wants to keep going on
    billing failure — this function does not.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO relay_usage
                  (tenant_id, relay_key_id, model,
                   prompt_tokens, completion_tokens, latency_ms)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                uuid.UUID(ctx.tenant_id),
                uuid.UUID(ctx.key_id),
                model,
                prompt_tokens,
                completion_tokens,
                latency_ms,
            )
            await conn.execute(
                "UPDATE relay_keys SET last_used_at = NOW() WHERE id = $1",
                uuid.UUID(ctx.key_id),
            )
    log.info(
        "billed key=%s model=%s prompt=%d completion=%d latency_ms=%d",
        ctx.key_id, model, prompt_tokens, completion_tokens, latency_ms,
    )


async def maybe_record(
    pool,
    ctx: RelayKeyContext,
    *,
    request_model: str,
    response_buffer: bytes,
    start_monotonic: float,
    now_monotonic: float,
) -> None:
    """Inspect a captured response stream and record usage if a
    terminal chunk with token counts is present.

    Called from the streaming proxy's ``finally`` block. Best-effort:
    swallows exceptions so a billing failure stays out of the
    request's failure mode.

    ``request_model`` is the model the client asked for; the response's
    own ``model`` field overrides it if Ollama swapped (e.g. tag
    fallback) — we record what was actually run.
    """
    if pool is None:
        return
    try:
        terminal = find_terminal_chunk(response_buffer)
        if terminal is None:
            return
        prompt_tokens, completion_tokens = count_tokens_from_ollama_final_chunk(terminal)
        if prompt_tokens == 0 and completion_tokens == 0:
            # Aborted / cache-hit / error response carries no counts.
            return
        model = terminal.get("model") or request_model
        latency_ms = int((now_monotonic - start_monotonic) * 1000)
        await record_usage(
            pool, ctx,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
        )
    except Exception:
        log.exception(
            "billing record failed for key=%s — skipping", ctx.key_id,
        )
