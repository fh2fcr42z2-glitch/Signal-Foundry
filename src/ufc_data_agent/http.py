from __future__ import annotations

import logging
import random
import time
from urllib.parse import urlparse

import httpx

LOGGER = logging.getLogger(__name__)


class RespectfulClient:
    """HTTP client with a global delay, retries, and an identifiable user agent."""

    def __init__(
        self, *, user_agent: str, interval: float = 1.0, timeout: float = 30, retries: int = 4
    ) -> None:
        self.interval = interval
        self.retries = retries
        self._last_request_at = 0.0
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"},
            timeout=timeout,
            follow_redirects=True,
        )

    def get_text(self, url: str) -> str:
        if urlparse(url).scheme not in {"http", "https"}:
            raise ValueError(f"Unsupported URL: {url}")
        for attempt in range(self.retries + 1):
            wait = self.interval - (time.monotonic() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            try:
                response = self._client.get(url)
                self._last_request_at = time.monotonic()
                response.raise_for_status()
                return response.text
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in {
                    429,
                    500,
                    502,
                    503,
                    504,
                }
                if attempt >= self.retries or not retryable:
                    raise
                delay = (2**attempt) + random.uniform(0, 0.5)  # noqa: S311
                LOGGER.warning("Request failed (%s); retrying in %.1fs", exc, delay)
                time.sleep(delay)
        raise RuntimeError("unreachable")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> RespectfulClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
