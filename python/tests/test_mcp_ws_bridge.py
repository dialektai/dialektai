"""Tests for the WS ↔ PromptConsentProvider bridge in ``server.py``.

The bridge is Phase 1.2 commit A of M2 Этап 2.5. Its job is to give
a ``dialekt.mcp.consent.PromptConsentProvider`` a prompt function that
talks JSON over an open WebSocket and resolves when the matching
response arrives. The consumer (agent tool-call path) lands in Phase
1.5 — for this commit the bridge stands alone, verified via unit +
integration-shaped tests below.

Tested surfaces (all module-private in server.py):
    _pending_consents             — module-global future registry
    _build_consent_prompt_fn(...) — returns a PromptFn closure
    _handle_consent_response(...) — called from the WS receive loop

WebSocket is stubbed with FakeWS (captures send_text JSON).
"""
import asyncio
import json

from dialekt.mcp import (
    ConsentDecision,
    ConsentRequest,
    provider_for_autonomy,
)

import server as srv


# ── Fixtures ────────────────────────────────────────────────────────────────


class FakeWS:
    """Minimal drop-in for fastapi.WebSocket that captures sends."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))


def _make_request(
    *, server_name: str = "github",
    tool_name: str = "create_issue",
    arguments: dict | None = None,
    destructive: bool = True,
    source: str = "explicit",
) -> ConsentRequest:
    return ConsentRequest(
        server_name=server_name,
        tool_name=tool_name,
        arguments=arguments or {"title": "test"},
        destructive=destructive,
        destructive_source=source,
    )


def _reset_pending() -> None:
    srv._pending_consents.clear()


# ── Core behaviour ──────────────────────────────────────────────────────────


def test_prompt_fn_emits_consent_request_frame():
    """The prompt fn sends one mcp_consent_request with the right shape."""
    async def run():
        _reset_pending()
        ws = FakeWS()
        prompt = srv._build_consent_prompt_fn(ws, "ws-1", asyncio.get_event_loop())

        async def responder():
            # Wait until the prompt has registered its future.
            for _ in range(100):
                if srv._pending_consents:
                    break
                await asyncio.sleep(0.001)
            key = next(iter(srv._pending_consents))
            _, req_id = key.split(":", 1)
            srv._handle_consent_response("ws-1", {
                "request_id": req_id,
                "decision": "approved",
            })

        task = asyncio.create_task(responder())
        decision = await prompt(_make_request())
        await task

        assert decision == ConsentDecision.APPROVED
        assert len(ws.sent) == 1
        frame = ws.sent[0]
        assert frame["type"] == "mcp_consent_request"
        assert frame["server_name"] == "github"
        assert frame["tool_name"] == "create_issue"
        assert frame["arguments"] == {"title": "test"}
        assert frame["destructive"] is True
        assert frame["destructive_source"] == "explicit"
        assert isinstance(frame["request_id"], str) and len(frame["request_id"]) >= 8

    asyncio.run(run())


def test_deny_decision_returns_denied():
    async def run():
        _reset_pending()
        ws = FakeWS()
        prompt = srv._build_consent_prompt_fn(ws, "ws-2", asyncio.get_event_loop())

        async def responder():
            for _ in range(100):
                if srv._pending_consents:
                    break
                await asyncio.sleep(0.001)
            key = next(iter(srv._pending_consents))
            _, req_id = key.split(":", 1)
            srv._handle_consent_response("ws-2", {
                "request_id": req_id,
                "decision": "denied",
            })

        task = asyncio.create_task(responder())
        decision = await prompt(_make_request())
        await task
        assert decision == ConsentDecision.DENIED

    asyncio.run(run())


# ── Integration-shape: full provider chain through WS bridge ────────────────


def test_provider_chain_session_cache_short_circuits():
    """End-to-end: provider_for_autonomy + WS prompt fn → second call on
    the same (server, tool) after approved_session does NOT fire a new
    WS frame. Proves the chain is real (Base → SessionCaching → Prompt),
    not a mock.
    """
    async def run():
        _reset_pending()
        ws = FakeWS()
        prompt = srv._build_consent_prompt_fn(ws, "ws-3", asyncio.get_event_loop())
        provider = provider_for_autonomy("ask-before-write", prompt)

        async def responder_once():
            # Resolve only the first request as APPROVED_SESSION.
            for _ in range(100):
                if srv._pending_consents:
                    break
                await asyncio.sleep(0.001)
            key = next(iter(srv._pending_consents))
            _, req_id = key.split(":", 1)
            srv._handle_consent_response("ws-3", {
                "request_id": req_id,
                "decision": "approved_session",
            })

        task = asyncio.create_task(responder_once())
        first = await provider.request_consent(_make_request())
        await task
        # Second call on same (server, tool) must short-circuit through
        # the cache without any new WS frame.
        second = await provider.request_consent(_make_request())

        assert first == ConsentDecision.APPROVED_SESSION
        assert second == ConsentDecision.APPROVED   # SessionCaching returns APPROVED on hit
        assert len(ws.sent) == 1                    # no second frame

    asyncio.run(run())


# ── Timeout and cancellation paths ──────────────────────────────────────────


def test_timeout_returns_denied_and_emits_timeout_frame(monkeypatch):
    """When no response arrives inside the timeout, prompt fn returns
    DENIED and emits an mcp_consent_timeout frame for the frontend.
    """
    async def run():
        _reset_pending()
        ws = FakeWS()
        # Patch the wait_for timeout to near-zero via a monkeypatched
        # asyncio.wait_for that always raises TimeoutError immediately.
        real_wait_for = asyncio.wait_for

        async def fast_timeout(awaitable, timeout):
            return await real_wait_for(awaitable, timeout=0.05)

        monkeypatch.setattr(srv.asyncio, "wait_for", fast_timeout)
        prompt = srv._build_consent_prompt_fn(ws, "ws-4", asyncio.get_event_loop())

        decision = await prompt(_make_request())
        assert decision == ConsentDecision.DENIED

        types_sent = [f["type"] for f in ws.sent]
        assert "mcp_consent_request" in types_sent
        assert "mcp_consent_timeout" in types_sent
        # Pending map must be clean post-timeout.
        assert not srv._pending_consents

    asyncio.run(run())


def test_cancelled_future_returns_denied():
    """If the future is cancelled (disconnect cleanup path), the prompt
    fn returns DENIED via the CancelledError branch.
    """
    async def run():
        _reset_pending()
        ws = FakeWS()
        prompt = srv._build_consent_prompt_fn(ws, "ws-5", asyncio.get_event_loop())

        async def canceller():
            for _ in range(100):
                if srv._pending_consents:
                    break
                await asyncio.sleep(0.001)
            # Simulate ws_chat finally-block cleanup.
            for key in list(srv._pending_consents):
                if key.startswith("ws-5:"):
                    fut = srv._pending_consents[key]
                    fut.cancel()

        task = asyncio.create_task(canceller())
        decision = await prompt(_make_request())
        await task
        assert decision == ConsentDecision.DENIED

    asyncio.run(run())


# ── Response-handler safety cases ───────────────────────────────────────────


def test_orphan_response_dropped_silently():
    """Response arriving before any request was sent is a no-op."""
    _reset_pending()
    dispatched = srv._handle_consent_response("ws-6", {
        "request_id": "bogus",
        "decision": "approved",
    })
    assert dispatched is False
    assert not srv._pending_consents


def test_response_after_timeout_dropped_silently():
    """If a response arrives AFTER wait_for timed out (future already
    cancelled/done), the handler must not crash and must not attempt
    to resolve a completed future.
    """
    async def run():
        _reset_pending()
        ws = FakeWS()
        loop = asyncio.get_event_loop()
        # Register a future manually and mark it done to mimic a stale entry.
        fut: asyncio.Future = loop.create_future()
        fut.cancel()
        srv._pending_consents["ws-7:stale-id"] = fut

        dispatched = srv._handle_consent_response("ws-7", {
            "request_id": "stale-id",
            "decision": "approved",
        })
        assert dispatched is False
        # No exception, no state change.
        del ws  # silence unused-var

    asyncio.run(run())


def test_non_string_request_id_rejected():
    """Malformed frames with numeric/dict request_id are dropped, not crashy."""
    _reset_pending()
    for bad in (123, {"x": 1}, None, ""):
        assert srv._handle_consent_response("ws-9", {
            "request_id": bad,
            "decision": "approved",
        }) is False


def test_non_string_decision_coerced_to_denied():
    """A list/dict decision value must coerce to DENIED, not raise TypeError."""
    async def run():
        _reset_pending()
        ws = FakeWS()
        prompt = srv._build_consent_prompt_fn(ws, "ws-10", asyncio.get_event_loop())

        async def responder():
            for _ in range(100):
                if srv._pending_consents:
                    break
                await asyncio.sleep(0.001)
            key = next(iter(srv._pending_consents))
            _, req_id = key.split(":", 1)
            srv._handle_consent_response("ws-10", {
                "request_id": req_id,
                "decision": ["approved"],   # non-string, previously crashy
            })

        task = asyncio.create_task(responder())
        decision = await prompt(_make_request())
        await task
        assert decision == ConsentDecision.DENIED

    asyncio.run(run())


def test_unknown_decision_coerced_to_denied():
    """Defensive default — garbage decision values get treated as denied."""
    async def run():
        _reset_pending()
        ws = FakeWS()
        prompt = srv._build_consent_prompt_fn(ws, "ws-8", asyncio.get_event_loop())

        async def responder():
            for _ in range(100):
                if srv._pending_consents:
                    break
                await asyncio.sleep(0.001)
            key = next(iter(srv._pending_consents))
            _, req_id = key.split(":", 1)
            srv._handle_consent_response("ws-8", {
                "request_id": req_id,
                "decision": "maybe_later",
            })

        task = asyncio.create_task(responder())
        decision = await prompt(_make_request())
        await task
        assert decision == ConsentDecision.DENIED

    asyncio.run(run())


# ── v0.24 approve_all batching ──────────────────────────────────────────────


def test_approved_all_resolves_head_and_all_siblings_for_same_ws():
    """approved_all decision resolves the head request as APPROVED and
    snapshot-resolves every other pending consent for this ws_id as
    APPROVED. Mentor ruling §A: snapshot semantics, atomic at decision-
    resolution time."""
    async def run():
        srv._pending_consents.clear()
        ws = FakeWS()
        loop = asyncio.get_event_loop()
        prompt = srv._build_consent_prompt_fn(ws, "ws-batch", loop)

        # Fire 3 concurrent prompts (simulating an agent burst).
        async def responder():
            # Wait until all 3 futures are pending.
            for _ in range(200):
                if len(srv._pending_consents) >= 3:
                    break
                await asyncio.sleep(0.001)
            # Pick the first request_id as the "head" the user clicks
            # Approve All on; the other two are siblings.
            keys = sorted(srv._pending_consents.keys())
            _, head_req = keys[0].split(":", 1)
            srv._handle_consent_response("ws-batch", {
                "request_id": head_req,
                "decision": "approved_all",
            })

        responder_task = asyncio.create_task(responder())
        results = await asyncio.gather(
            prompt(_make_request(tool_name="t1")),
            prompt(_make_request(tool_name="t2")),
            prompt(_make_request(tool_name="t3")),
        )
        await responder_task

        assert all(d == ConsentDecision.APPROVED for d in results), results
        # Pending map fully drained — every future was resolved.
        assert all(k.startswith("ws-other:") or not k.startswith("ws-batch:")
                   for k in srv._pending_consents.keys())


    asyncio.run(run())


def test_approved_all_does_not_affect_other_ws_id():
    """Sibling resolution is scoped to the current ws_id. Other
    sessions in the same process keep their pending consents intact."""
    async def run():
        srv._pending_consents.clear()
        ws_a = FakeWS()
        ws_b = FakeWS()
        loop = asyncio.get_event_loop()
        prompt_a = srv._build_consent_prompt_fn(ws_a, "ws-A", loop)
        prompt_b = srv._build_consent_prompt_fn(ws_b, "ws-B", loop)

        b_decision_holder = {}

        async def fire_b():
            # ws-B has its own pending consent that must NOT be
            # auto-resolved by ws-A clicking Approve All.
            try:
                d = await asyncio.wait_for(
                    prompt_b(_make_request(tool_name="ws_b_tool")),
                    timeout=2.0,
                )
                b_decision_holder["d"] = d
            except asyncio.TimeoutError:
                b_decision_holder["d"] = "timeout"

        async def responder():
            # Wait until A has 2 pending and B has 1 pending.
            for _ in range(200):
                a_count = sum(1 for k in srv._pending_consents if k.startswith("ws-A:"))
                b_count = sum(1 for k in srv._pending_consents if k.startswith("ws-B:"))
                if a_count >= 2 and b_count >= 1:
                    break
                await asyncio.sleep(0.001)
            keys = [k for k in srv._pending_consents if k.startswith("ws-A:")]
            _, head_req = sorted(keys)[0].split(":", 1)
            srv._handle_consent_response("ws-A", {
                "request_id": head_req,
                "decision": "approved_all",
            })
            # Now resolve ws-B explicitly so the test does not hang.
            await asyncio.sleep(0.05)
            b_keys = [k for k in srv._pending_consents if k.startswith("ws-B:")]
            if b_keys:
                _, bid = b_keys[0].split(":", 1)
                srv._handle_consent_response("ws-B", {
                    "request_id": bid,
                    "decision": "denied",
                })

        b_task = asyncio.create_task(fire_b())
        responder_task = asyncio.create_task(responder())
        a_results = await asyncio.gather(
            prompt_a(_make_request(tool_name="a1")),
            prompt_a(_make_request(tool_name="a2")),
        )
        await b_task
        await responder_task

        # A both APPROVED via batch, B explicitly DENIED (not affected
        # by the batch on A).
        assert all(d == ConsentDecision.APPROVED for d in a_results)
        assert b_decision_holder["d"] == ConsentDecision.DENIED

    asyncio.run(run())


def test_approved_all_falls_through_to_approved_when_no_siblings():
    """Mentor P2 nit: if approved_all arrives with queueLength=1 (no
    siblings to resolve), the head still resolves as APPROVED — same
    as plain `approved`. Defensive: the frontend gates the button on
    queueLength > 1, but a buggy/old client could send approved_all
    with one pending."""
    async def run():
        srv._pending_consents.clear()
        ws = FakeWS()
        prompt = srv._build_consent_prompt_fn(ws, "ws-solo", asyncio.get_event_loop())

        async def responder():
            for _ in range(100):
                if srv._pending_consents:
                    break
                await asyncio.sleep(0.001)
            key = next(iter(srv._pending_consents))
            _, req_id = key.split(":", 1)
            srv._handle_consent_response("ws-solo", {
                "request_id": req_id,
                "decision": "approved_all",
            })

        task = asyncio.create_task(responder())
        decision = await prompt(_make_request())
        await task
        assert decision == ConsentDecision.APPROVED

    asyncio.run(run())

