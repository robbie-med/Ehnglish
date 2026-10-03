"""HTTP with retries for engine calls. This PC's DNS resolver drops out for a few seconds now and
then; a transport error is retried with backoff, an HTTP error status is returned as-is (the
caller decides), and 429/5xx are retried too."""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

RETRY_STATUS = {429, 500, 502, 503, 504}


def request_with_retry(
    make: Callable[[], httpx.Response], *, attempts: int = 4, base_delay: float = 2.0
) -> httpx.Response:
    last: Exception | None = None
    for i in range(attempts):
        try:
            r = make()
        except httpx.TransportError as e:  # DNS, connect, read timeouts
            last = e
        else:
            if r.status_code not in RETRY_STATUS or i == attempts - 1:
                return r
            last = RuntimeError(f"HTTP {r.status_code}")
        time.sleep(base_delay * (2**i))
    assert last is not None
    raise last
