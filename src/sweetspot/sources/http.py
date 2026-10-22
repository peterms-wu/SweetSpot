"""Polite HTTP client: throttling, bounded retries, Retry-After, auth stop, secret redaction (FR-023, FR-028)."""

import logging
import re
import time
from collections import Counter, deque
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from sweetspot import __version__
from sweetspot.sources.errors import RateLimited, ResponseTooLarge, SourceDisabled, SourceError

__all__ = ["RateLimitedClient", "RateLimited", "ResponseTooLarge", "SourceDisabled", "SourceError"]

log = logging.getLogger("sweetspot.http")

USER_AGENT = f"SweetSpot/{__version__} (personal, non-commercial)"
_KEY_PARAM = re.compile(r"(?i)\b(key=)[^&\s]+")


class RateLimitedClient:
    def __init__(
        self,
        name: str,
        *,
        min_interval: float,
        window_limit: int | None = None,
        window_seconds: float = 300.0,
        max_retries: int = 3,
        max_retry_wait: float = 120.0,
        max_bytes: int = 8 * 1024 * 1024,
        timeout: httpx.Timeout = httpx.Timeout(30.0, connect=10.0),
        headers: dict[str, str] | None = None,
        secrets: Iterable[str] = (),
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.name = name
        self.min_interval = min_interval
        self.window_limit = window_limit
        self.window_seconds = window_seconds
        self.max_retries = max_retries
        self.max_retry_wait = max_retry_wait
        self.max_bytes = max_bytes
        self.disabled = False
        self.requests_sent = 0          # usage statistics for run summaries
        self.throttle_wait = 0.0        # seconds spent waiting for our own spacing / window limits
        self.requests_by_path: Counter = Counter()
        self._blocked_until: float | None = None   # set when the source asked for a longer pause than we wait
        self._secrets = [s for s in secrets if s]
        self._sleep = sleep
        self._clock = clock
        self._last_start: float | None = None
        self._window: deque[float] = deque()
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, **(headers or {})},
            transport=transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    # --- helpers -----------------------------------------------------------------------------

    def redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, "***")
        return _KEY_PARAM.sub(r"\1***", text)

    def _throttle(self) -> None:
        now = self._clock()
        if self._last_start is not None:
            wait = self._last_start + self.min_interval - now
            if wait > 0:
                self._sleep(wait)
                self.throttle_wait += wait
                now = self._clock()
        if self.window_limit:
            while self._window and self._window[0] <= now - self.window_seconds:
                self._window.popleft()
            if len(self._window) >= self.window_limit:
                wait = self._window[0] + self.window_seconds - now
                self._sleep(wait)
                self.throttle_wait += wait
                now = self._clock()
                self._window.popleft()
            self._window.append(now)
        self._last_start = now

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if not value:
            return None
        if value.strip().isdigit():
            return float(value)
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        seconds = (when - datetime.now(UTC)).total_seconds()
        return seconds if seconds > 0 else None

    def _read(self, response: httpx.Response) -> httpx.Response:
        chunks, size = [], 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > self.max_bytes:
                response.close()
                raise ResponseTooLarge(f"{self.name}: response larger than {self.max_bytes} bytes")
            chunks.append(chunk)
        response.close()
        # Rebuild without content-encoding: iter_bytes() already decompressed the body.
        headers = {k: v for k, v in response.headers.items() if k.lower() not in ("content-encoding",
                                                                                   "content-length")}
        return httpx.Response(response.status_code, headers=headers, content=b"".join(chunks),
                              request=response.request)

    # --- public API ----------------------------------------------------------------------------

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Send a request. Returns the response for 2xx/3xx and non-retryable 4xx (e.g. 404)."""
        if self.disabled:
            raise SourceDisabled(f"{self.name}: disabled after an authorization failure")
        safe_url = self.redact(url)
        if self._blocked_until is not None:
            remaining = self._blocked_until - self._clock()
            if remaining > self.max_retry_wait:
                raise RateLimited(f"{self.name}: still rate limited for {remaining:.0f}s; not sending {safe_url}")
            if remaining > 0:
                self._sleep(remaining)
            self._blocked_until = None
        last_problem = ""
        for attempt in range(self.max_retries + 1):
            if attempt:
                log.info("%s retry %d for %s: %s", self.name, attempt, safe_url, last_problem)
            self._throttle()
            self.requests_sent += 1
            self.requests_by_path[httpx.URL(url).path] += 1
            try:
                request = self._client.build_request(method, url, **kwargs)
                response = self._read(self._client.send(request, stream=True))
            except httpx.TransportError as exc:
                last_problem = self.redact(f"{type(exc).__name__}: {exc}")
                if attempt < self.max_retries:
                    self._sleep(2 ** attempt)
                    continue
                raise SourceError(f"{self.name}: network error for {safe_url}: {last_problem}") from None

            status = response.status_code
            if status in (401, 403):
                self.disabled = True
                raise SourceDisabled(f"{self.name}: HTTP {status} for {safe_url}; source disabled for this run")
            if status == 429 or status >= 500:
                retry_after = self._retry_after(response)
                if retry_after is not None and retry_after > self.max_retry_wait:
                    self._blocked_until = self._clock() + retry_after
                    raise RateLimited(f"{self.name}: asked to wait {retry_after:.0f}s for {safe_url}")
                last_problem = f"HTTP {status}"
                if attempt < self.max_retries:
                    self._sleep(max(retry_after or 0, 2 ** attempt))
                    continue
                error = RateLimited if status == 429 else SourceError    # 429 is rate limiting, wait or not (014 T076)
                raise error(f"{self.name}: HTTP {status} for {safe_url} after {self.max_retries} retries")
            return response
        raise AssertionError("unreachable")

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self.request("POST", url, **kwargs)
