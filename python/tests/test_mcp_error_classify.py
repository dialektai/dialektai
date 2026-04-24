"""Tests for dialekt.mcp.error_classify.classify_sdk_error."""
import pytest

from dialekt.mcp.error_classify import classify_sdk_error
from dialekt.mcp.errors import (
    MCPError,
    MCPProtocolError,
    MCPServerUnavailableError,
    MCPTimeoutError,
    MCPToolNotFoundError,
)


def test_already_classified_passes_through():
    err = MCPTimeoutError("orig")
    out = classify_sdk_error(err)
    assert out is err


def test_timeout_names_map_to_mcp_timeout():
    for exc_cls_name in ("TimeoutError", "CancelledError"):
        exc = type(exc_cls_name, (Exception,), {})("boom")
        result = classify_sdk_error(exc)
        assert isinstance(result, MCPTimeoutError), (
            f"{exc_cls_name} should map to MCPTimeoutError, got {type(result).__name__}"
        )


def test_connection_shapes_map_to_unavailable():
    # Names matter, not inheritance — the classifier is name-based.
    for exc_cls_name in (
        "ConnectionRefusedError",
        "ConnectionError",
        "FileNotFoundError",
        "ProcessLookupError",
        "ClosedResourceError",
        "EndOfStream",
        "BrokenResourceError",
        "RemoteProtocolError",
    ):
        exc = type(exc_cls_name, (Exception,), {})("boom")
        out = classify_sdk_error(exc)
        assert isinstance(out, MCPServerUnavailableError), (
            f"{exc_cls_name} should map to Unavailable, got {type(out).__name__}"
        )


def test_mcp_protocol_names():
    exc = type("McpError", (Exception,), {})("proto")
    assert isinstance(classify_sdk_error(exc), MCPProtocolError)

    exc = type("JSONRPCError", (Exception,), {})("jsonrpc")
    assert isinstance(classify_sdk_error(exc), MCPProtocolError)

    exc = type("InvalidRequestError", (Exception,), {})("bad req")
    assert isinstance(classify_sdk_error(exc), MCPProtocolError)


def test_tool_not_found_heuristic():
    exc = RuntimeError("Tool 'xyz' not found on server")
    assert isinstance(classify_sdk_error(exc), MCPToolNotFoundError)

    exc = RuntimeError("unknown tool: bar")
    assert isinstance(classify_sdk_error(exc), MCPToolNotFoundError)


def test_unknown_exception_falls_back_to_server_unavailable():
    exc = RuntimeError("something weird happened")
    out = classify_sdk_error(exc)
    assert isinstance(out, MCPServerUnavailableError)
    assert "unclassified MCP failure" in str(out)


def test_classifier_returns_mcperror_base_for_all_inputs():
    """Every branch produces an MCPError subclass — no raw Exception escapes."""
    for exc in [
        TimeoutError("t"),
        ConnectionRefusedError("c"),
        FileNotFoundError("f"),
        RuntimeError("r"),
        ValueError("v"),
    ]:
        assert isinstance(classify_sdk_error(exc), MCPError)


def test_builtin_exception_group_is_unwrapped():
    """BaseExceptionGroup wrapping one inner exception should classify
    on the inner — anyio task groups surface failures this way."""
    try:
        BaseExceptionGroup  # type: ignore[used-before-assign]
    except NameError:
        pytest.skip("BaseExceptionGroup not available on this Python")

    inner = type("ConnectionRefusedError", (Exception,), {})("conn refused")
    group = BaseExceptionGroup("wrap", [inner])  # type: ignore[name-defined]
    out = classify_sdk_error(group)
    assert isinstance(out, MCPServerUnavailableError)
