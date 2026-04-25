"""Tests for dialekt.mcp.server.auth — key validation + rate limiter."""
import pytest

from dialekt.mcp.server.auth import (
    AuthError,
    RateLimitExceeded,
    RateLimiter,
    validate_api_key,
)
from dialekt.mcp.server.config import ApiKey, ServerConfig


# ---------------------------------------------------------------------------
# validate_api_key.
# ---------------------------------------------------------------------------


def _config_with_key(value: str, *, id: str = "test") -> ServerConfig:
    return ServerConfig(api_keys=[ApiKey(id=id, value=value)])


def test_validate_api_key_happy_path():
    config = _config_with_key("sekret-long-enough-to-pass-validation")
    key = validate_api_key(config, "sekret-long-enough-to-pass-validation")
    assert key.id == "test"


def test_validate_api_key_none_supplied():
    config = _config_with_key("sekret-long-enough-to-pass-validation")
    with pytest.raises(AuthError, match="no API key"):
        validate_api_key(config, None)


def test_validate_api_key_empty_string():
    config = _config_with_key("sekret-long-enough-to-pass-validation")
    with pytest.raises(AuthError, match="no API key"):
        validate_api_key(config, "")


def test_validate_api_key_mismatch():
    config = _config_with_key("sekret-long-enough-to-pass-validation")
    with pytest.raises(AuthError, match="not recognised"):
        validate_api_key(config, "this-is-not-the-right-key-at-all")


def test_validate_api_key_empty_config_always_rejects():
    config = ServerConfig(api_keys=[])
    with pytest.raises(AuthError):
        validate_api_key(config, "any-key-even-well-formed-fails-here")


# ---------------------------------------------------------------------------
# RateLimiter.
# ---------------------------------------------------------------------------


def test_rate_limiter_within_window_allowed():
    rl = RateLimiter(3)
    rl.check_and_record()
    rl.check_and_record()
    rl.check_and_record()
    # Only the 4th trips.
    with pytest.raises(RateLimitExceeded):
        rl.check_and_record()


def test_rate_limiter_slides():
    """Entries older than 60s evicted; window resets."""
    now = [0.0]
    rl = RateLimiter(2, clock=lambda: now[0])
    rl.check_and_record()
    now[0] += 30
    rl.check_and_record()
    with pytest.raises(RateLimitExceeded):
        rl.check_and_record()

    # Advance past the first entry's 60-second age; it falls out.
    now[0] += 31  # first entry now 61s old
    rl.check_and_record()  # no raise


def test_rate_limiter_remaining_accounts_for_expired():
    now = [0.0]
    rl = RateLimiter(5, clock=lambda: now[0])
    rl.check_and_record()
    rl.check_and_record()
    assert rl.remaining() == 3
    now[0] += 61
    # Prior entries now stale; window effectively empty.
    assert rl.remaining() == 5


def test_rate_limiter_zero_max_rejected():
    with pytest.raises(ValueError):
        RateLimiter(0)


def test_rate_limiter_negative_max_rejected():
    with pytest.raises(ValueError):
        RateLimiter(-1)


def test_rate_limit_error_message_carries_threshold():
    rl = RateLimiter(1)
    rl.check_and_record()
    with pytest.raises(RateLimitExceeded, match="1/min"):
        rl.check_and_record()
