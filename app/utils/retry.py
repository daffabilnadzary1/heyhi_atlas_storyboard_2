"""
app/utils/retry.py — the one retry-with-exponential-backoff loop.

app/utils/retry

Shared retry helpers with exponential backoff.
Used by Veo, Lyria, and image generation.
"""
from __future__ import annotations

import os
import time
from typing import Callable, TypeVar

T = TypeVar("T")

DEFAULT_RETRY_BACKOFF_S = 2.0

# Error message fragments treated as transient failures.
TRANSIENT_MARKERS = ("500", "502", "503", "504", "rate", "timeout", "unavailable")


def looks_transient(err: object) -> bool:
    """True when a provider error message looks like a retryable failure."""
    s = str(err).lower()
    return any(k in s for k in TRANSIENT_MARKERS)


def backoff_from_env(var: str, default: float = DEFAULT_RETRY_BACKOFF_S) -> float:
    """Resolve a retry backoff from the environment, else `default`. Each layer
    keeps its own thin wrapper naming its env var."""
    return float(os.environ.get(var, default))


class RetriesExhausted(RuntimeError):
    """Every attempt failed. Carries the final exception so each caller can
    wrap it in that layer's own error type with its own message."""

    def __init__(self, last: Exception | None, attempts: int):
        self.last = last
        self.attempts = attempts
        super().__init__(str(last))


def retry_call(fn: Callable[[], T], *, attempts: int, exc_type,
               backoff_s: float = DEFAULT_RETRY_BACKOFF_S) -> tuple[T, int]:
    """Call fn() up to `attempts` times, retrying only `exc_type`.

    Returns (result, attempt_number) on success — the attempt number is what
    the cost log records. Raises RetriesExhausted when every attempt failed.
    """
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn(), i + 1
        except exc_type as e:
            last = e
            if i < attempts - 1:
                time.sleep(backoff_s * (2 ** i))
    raise RetriesExhausted(last, attempts)
