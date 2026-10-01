import random
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime


@dataclass(frozen=True)
class RetryDecision:
    should_retry: bool
    delay_seconds: float | None
    reason: str


class RetryPolicy:
    def __init__(
        self,
        *,
        max_attempts: int,
        base_delay_seconds: float,
        max_delay_seconds: float,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if base_delay_seconds <= 0 or max_delay_seconds <= 0:
            raise ValueError("retry delays must be positive")
        self.max_attempts = max_attempts
        self.base_delay_seconds = base_delay_seconds
        self.max_delay_seconds = max_delay_seconds

    def decide(
        self,
        *,
        attempt_number: int,
        response_status: int | None,
        transport_error: bool,
        retry_after_seconds: float | None = None,
        random_value: float | None = None,
    ) -> RetryDecision:
        retryable = (
            transport_error
            or response_status in {408, 425, 429}
            or (response_status is not None and 500 <= response_status <= 599)
        )
        if not retryable:
            return RetryDecision(False, None, "non_retryable_failure")
        if attempt_number >= self.max_attempts:
            return RetryDecision(False, None, "attempts_exhausted")

        exponential_cap = min(
            self.max_delay_seconds,
            self.base_delay_seconds * (2 ** (attempt_number - 1)),
        )
        jitter_factor = random.random() if random_value is None else random_value
        if not 0 <= jitter_factor <= 1:
            raise ValueError("random_value must be between 0 and 1")
        delay = exponential_cap * jitter_factor
        if retry_after_seconds is not None:
            delay = max(delay, min(retry_after_seconds, self.max_delay_seconds))
        return RetryDecision(True, delay, "retryable_failure")


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    if value is None:
        return None
    stripped = value.strip()
    if stripped.isdigit():
        return float(stripped)
    try:
        parsed = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    current = now or datetime.now(UTC)
    return max(0.0, (parsed - current).total_seconds())
