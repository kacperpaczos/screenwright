"""HTTP client dla domen (shared kernel)."""

import os
from collections.abc import Iterator
from contextlib import contextmanager

import httpx

DEFAULT_USER_AGENT = "screenwright/0.2 (+https://github.com/screenwright/screenwright)"
SNAP_DEVICE_SERIES = "16"

RETRYABLE_EXC = (httpx.ConnectTimeout, httpx.ConnectError, httpx.ReadTimeout)


class HttpClient:
    """Synchronous HTTP client z retry i konfigurowalnym nagłówkiem Snap."""

    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_connect: float = 10.0,
        timeout_read: float = 30.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
    ) -> None:
        self._user_agent = user_agent
        self._timeout = httpx.Timeout(timeout_read, connect=timeout_connect)
        self._max_retries = max_retries
        self._backoff_base = backoff_base

    def get(self, url: str, *, snap: bool = False) -> httpx.Response:
        headers = self._base_headers(snap)
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                response = httpx.get(
                    url, headers=headers, timeout=self._timeout, follow_redirects=True
                )
                if response.status_code == 429 or response.status_code >= 500:
                    last_exc = httpx.HTTPStatusError(
                        f"{response.status_code}",
                        request=response.request,
                        response=response,
                    )
                    self._sleep_backoff(attempt)
                    continue
                response.raise_for_status()
                return response
            except RETRYABLE_EXC as exc:
                last_exc = exc
                self._sleep_backoff(attempt)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"unreachable: {url}")

    def _base_headers(self, snap: bool) -> dict[str, str]:
        headers: dict[str, str] = {"User-Agent": self._user_agent}
        if snap:
            headers["Snap-Device-Series"] = SNAP_DEVICE_SERIES
        return headers

    def _sleep_backoff(self, attempt: int) -> None:
        delay = self._backoff_base * (2**attempt)
        if os.environ.get("SCREENWRIGHT_TESTS_FAST") == "1":
            return
        import time

        time.sleep(delay)


@contextmanager
def http_session(client: HttpClient | None = None) -> Iterator[HttpClient]:
    yield client or HttpClient()


__all__ = [
    "DEFAULT_USER_AGENT",
    "RETRYABLE_EXC",
    "SNAP_DEVICE_SERIES",
    "HttpClient",
    "http_session",
]
