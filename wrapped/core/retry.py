from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable

log = logging.getLogger(__name__)


def retry_call[T](
    fn: Callable[[], T],
    *,
    retry_on: type[Exception] | tuple[type[Exception], ...],
    max_attempts: int,
    sleep: Callable[[float], None] = time.sleep,
    rng: Callable[[], float] = random.random,
    base: float = 0.5,
    cap: float = 30.0,
) -> T:

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    attempt = 1
    while True:
        try:
            return fn()
        except retry_on as exc:
            if attempt >= max_attempts:
                raise
            log.warning(
                "Retrying a temporary failure",
                extra={
                    "event": "retry.scheduled",
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "exception_type": type(exc).__name__,
                },
            )
            sleep(rng() * min(cap, base * 2 ** (attempt - 1)))
            attempt += 1
