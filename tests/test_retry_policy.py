from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

from hookrelay.delivery.retry import RetryPolicy, parse_retry_after


def policy() -> RetryPolicy:
    return RetryPolicy(max_attempts=5, base_delay_seconds=2, max_delay_seconds=10)


def test_full_jitter_exponential_backoff() -> None:
    first = policy().decide(
        attempt_number=1,
        response_status=500,
        transport_error=False,
        random_value=0.5,
    )
    third = policy().decide(
        attempt_number=3,
        response_status=None,
        transport_error=True,
        random_value=0.5,
    )

    assert first.should_retry is True
    assert first.delay_seconds == 1
    assert third.delay_seconds == 4


def test_non_retryable_4xx_and_exhausted_attempts_stop() -> None:
    bad_request = policy().decide(
        attempt_number=1,
        response_status=400,
        transport_error=False,
    )
    exhausted = policy().decide(
        attempt_number=5,
        response_status=503,
        transport_error=False,
    )

    assert bad_request.should_retry is False
    assert bad_request.reason == "non_retryable_failure"
    assert exhausted.should_retry is False
    assert exhausted.reason == "attempts_exhausted"


def test_retry_after_is_honored_but_capped() -> None:
    decision = policy().decide(
        attempt_number=1,
        response_status=429,
        transport_error=False,
        retry_after_seconds=30,
        random_value=0,
    )

    assert decision.delay_seconds == 10


def test_parse_retry_after_seconds_and_http_date() -> None:
    now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    later = format_datetime(now + timedelta(seconds=15), usegmt=True)

    assert parse_retry_after("7", now=now) == 7
    assert parse_retry_after(later, now=now) == 15
    assert parse_retry_after("not-a-date", now=now) is None
