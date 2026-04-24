"""Tests for consent policy (destructive detection + providers).

These are pure unit tests — no subprocess, no MCP connection. They
exercise the decision rules the runtime layer depends on.
"""
import asyncio
from types import SimpleNamespace

import pytest

from dialekt.mcp import (
    AutoApproveProvider,
    AutoDenyProvider,
    ConsentDecision,
    ConsentRequest,
    PromptConsentProvider,
    SessionCachingProvider,
    is_destructive_tool,
    provider_for_autonomy,
)


# ---------------------------------------------------------------------------
# Destructive detection.
# ---------------------------------------------------------------------------


def _tool(name, annotations=None):
    return SimpleNamespace(name=name, annotations=annotations)


def test_explicit_destructive_annotation_wins():
    tool = _tool("list_repos", {"destructive": True})
    destructive, source = is_destructive_tool(tool)
    assert destructive is True
    assert source == "explicit"


def test_explicit_non_destructive_annotation_wins():
    """Even a 'write'-looking name gets marked safe if the server says so."""
    tool = _tool("write_status", {"destructive": False})
    destructive, source = is_destructive_tool(tool)
    assert destructive is False
    assert source == "explicit"


def test_writeable_annotation_treated_as_destructive_hint():
    tool = _tool("update_thing", {"writeable": True})
    destructive, source = is_destructive_tool(tool)
    assert destructive is True
    assert source == "explicit"


def test_heuristic_catches_common_write_verbs():
    for name in ("create_issue", "delete_branch", "update_file",
                 "write_log", "send_email", "post_message",
                 "remove_label", "modify_config", "edit_post"):
        destructive, source = is_destructive_tool(_tool(name))
        assert destructive is True, f"{name!r} should be flagged destructive"
        assert source == "heuristic"


def test_heuristic_lets_read_verbs_through():
    for name in ("list_repos", "get_issue", "search_code", "read_file"):
        destructive, source = is_destructive_tool(_tool(name))
        assert destructive is False, f"{name!r} should NOT be destructive"


def test_missing_annotations_falls_back_to_heuristic():
    tool = _tool("create_issue", annotations=None)
    destructive, source = is_destructive_tool(tool)
    assert destructive is True
    assert source == "heuristic"


def test_annotations_as_dict_supported():
    """The MCP SDK's Tool model carries annotations as a nested
    Pydantic object; tests pass plain dicts for simplicity — the
    reader accepts both."""
    tool = _tool("anything", annotations={"destructive": True})
    destructive, _ = is_destructive_tool(tool)
    assert destructive is True


# ---------------------------------------------------------------------------
# Concrete providers.
# ---------------------------------------------------------------------------


def _req() -> ConsentRequest:
    return ConsentRequest(
        server_name="github",
        tool_name="create_issue",
        arguments={"repo": "a/b"},
        destructive=True,
        destructive_source="heuristic",
    )


def test_auto_approve_returns_approved():
    async def run():
        return await AutoApproveProvider().request_consent(_req())
    assert asyncio.run(run()) is ConsentDecision.APPROVED


def test_auto_deny_returns_denied():
    async def run():
        return await AutoDenyProvider().request_consent(_req())
    assert asyncio.run(run()) is ConsentDecision.DENIED


def test_prompt_provider_delegates_to_callable():
    seen: list[ConsentRequest] = []

    async def fake_prompt(req):
        seen.append(req)
        return ConsentDecision.APPROVED_SESSION

    provider = PromptConsentProvider(fake_prompt)

    async def run():
        return await provider.request_consent(_req())

    assert asyncio.run(run()) is ConsentDecision.APPROVED_SESSION
    assert len(seen) == 1
    assert seen[0].tool_name == "create_issue"


def test_session_caching_skips_after_approved_session():
    call_count = [0]

    async def one_shot_prompt(req):
        call_count[0] += 1
        return ConsentDecision.APPROVED_SESSION

    provider = SessionCachingProvider(PromptConsentProvider(one_shot_prompt))

    async def run():
        d1 = await provider.request_consent(_req())
        d2 = await provider.request_consent(_req())
        d3 = await provider.request_consent(_req())
        return d1, d2, d3

    d1, d2, d3 = asyncio.run(run())
    assert d1 is ConsentDecision.APPROVED_SESSION
    # Subsequent calls short-circuit to APPROVED (single-shot, cached).
    assert d2 is ConsentDecision.APPROVED
    assert d3 is ConsentDecision.APPROVED
    assert call_count[0] == 1  # user asked exactly once


def test_session_caching_does_not_cache_single_approved():
    """APPROVED (without _SESSION) must NOT be cached — user only
    approved the one invocation."""
    call_count = [0]

    async def always_approve_one_shot(req):
        call_count[0] += 1
        return ConsentDecision.APPROVED

    provider = SessionCachingProvider(
        PromptConsentProvider(always_approve_one_shot)
    )

    async def run():
        await provider.request_consent(_req())
        await provider.request_consent(_req())

    asyncio.run(run())
    assert call_count[0] == 2, "APPROVED must re-ask the user"


def test_session_caching_does_not_cache_denied():
    call_count = [0]

    async def prompt(req):
        call_count[0] += 1
        return ConsentDecision.DENIED

    provider = SessionCachingProvider(PromptConsentProvider(prompt))

    async def run():
        await provider.request_consent(_req())
        await provider.request_consent(_req())

    asyncio.run(run())
    assert call_count[0] == 2


def test_session_caching_per_tool_pair():
    """APPROVED_SESSION for github.create_issue must NOT approve
    slack.send_message. Each (server, tool) pair is tracked separately."""
    async def prompt(req):
        return ConsentDecision.APPROVED_SESSION

    provider = SessionCachingProvider(PromptConsentProvider(prompt))

    req_github = ConsentRequest(
        server_name="github",
        tool_name="create_issue",
        arguments={},
        destructive=True,
        destructive_source="heuristic",
    )
    req_slack = ConsentRequest(
        server_name="slack",
        tool_name="send_message",
        arguments={},
        destructive=True,
        destructive_source="heuristic",
    )

    called = [0]

    async def counting_prompt(req):
        called[0] += 1
        return ConsentDecision.APPROVED_SESSION

    provider = SessionCachingProvider(PromptConsentProvider(counting_prompt))

    async def run():
        await provider.request_consent(req_github)  # asks
        await provider.request_consent(req_github)  # cached
        await provider.request_consent(req_slack)  # different pair, asks
        await provider.request_consent(req_slack)  # cached
        await provider.request_consent(req_github)  # still cached

    asyncio.run(run())
    assert called[0] == 2, "Each (server, tool) pair asks once"


# ---------------------------------------------------------------------------
# Autonomy-to-provider mapping.
# ---------------------------------------------------------------------------


def test_provider_for_autonomy_autonomous_is_auto_approve():
    provider = provider_for_autonomy("autonomous")
    assert isinstance(provider, AutoApproveProvider)


def test_provider_for_autonomy_review_only_is_auto_deny():
    provider = provider_for_autonomy("review-only")
    assert isinstance(provider, AutoDenyProvider)


def test_provider_for_autonomy_ask_before_write_wraps_prompt():
    async def prompt(req):
        return ConsentDecision.APPROVED

    provider = provider_for_autonomy("ask-before-write", prompt)
    # Should be a SessionCachingProvider wrapping a PromptConsentProvider.
    assert isinstance(provider, SessionCachingProvider)


def test_provider_for_autonomy_prompting_level_without_fn_errors():
    with pytest.raises(ValueError, match="user_prompt_fn"):
        provider_for_autonomy("ask-before-write")
