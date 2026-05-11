"""Tests for authentication and rate limiting."""

from __future__ import annotations

import time

from ai_data_agent.api.auth import APIKeyAuth
from ai_data_agent.api.rate_limit import RateLimiter


def test_rate_limiter_allows_within_limit():
    limiter = RateLimiter(requests_per_minute=60, burst=10)
    for _ in range(10):
        assert limiter.check("user1") is True


def test_rate_limiter_rejects_over_limit():
    limiter = RateLimiter(requests_per_minute=60, burst=2)
    assert limiter.check("user1") is True
    assert limiter.check("user1") is True
    assert limiter.check("user1") is False


def test_rate_limiter_separate_keys():
    limiter = RateLimiter(requests_per_minute=60, burst=1)
    assert limiter.check("user1") is True
    assert limiter.check("user2") is True
    # user1's second request should fail
    assert limiter.check("user1") is False
    # user2's second request should also fail
    assert limiter.check("user2") is False


def test_rate_limiter_refills():
    limiter = RateLimiter(requests_per_minute=6000, burst=1)
    assert limiter.check("user1") is True
    assert limiter.check("user1") is False
    # Wait briefly for refill
    time.sleep(0.15)
    assert limiter.check("user1") is True
