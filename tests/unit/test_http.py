import logging

import httpx
import pytest

from sweetspot.sources.http import RateLimited, RateLimitedClient, ResponseTooLarge, SourceDisabled, SourceError

SECRET = "abc123secretkey"


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make(handler, clock=None, **kw):
    clock = clock or FakeClock()
    client = RateLimitedClient(
        "itad", min_interval=kw.pop("min_interval", 0.4), window_limit=kw.pop("window_limit", None),
        transport=httpx.MockTransport(handler), sleep=clock.sleep, clock=clock.monotonic,
        secrets=[SECRET], **kw,
    )
    return client, clock


def test_requests_are_spaced_by_min_interval():
    client, clock = make(lambda r: httpx.Response(200, json={}))
    for _ in range(3):
        client.get("https://api.example.com/x")
    assert clock.sleeps == pytest.approx([0.4, 0.4])


def test_rolling_window_limit():
    client, clock = make(lambda r: httpx.Response(200), min_interval=0, window_limit=2, window_seconds=300)
    for _ in range(3):
        client.get("https://api.example.com/x")
    assert clock.sleeps == pytest.approx([300.0])


def test_429_waits_retry_after_seconds_then_succeeds():
    calls = iter([httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json={"ok": 1})])
    client, clock = make(lambda r: next(calls), min_interval=0)
    assert client.get("https://api.example.com/x").json() == {"ok": 1}
    assert 7 in clock.sleeps


def test_retry_after_http_date_is_supported():
    calls = iter([httpx.Response(503, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}),
                  httpx.Response(200)])
    client, clock = make(lambda r: next(calls), min_interval=0)
    client.get("https://api.example.com/x")
    assert clock.sleeps and clock.sleeps[0] >= 1  # past date -> falls back to exponential backoff


def test_5xx_gives_up_after_three_retries():
    count = {"n": 0}

    def handler(request):
        count["n"] += 1
        return httpx.Response(502)

    client, _ = make(handler, min_interval=0)
    with pytest.raises(SourceError):
        client.get("https://api.example.com/x")
    assert count["n"] == 4  # first try + 3 retries


def test_excessive_retry_after_stops_instead_of_waiting():
    count = {"n": 0}

    def handler(request):
        count["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "3600"})

    client, clock = make(handler, min_interval=0, max_retry_wait=120)
    with pytest.raises(RateLimited):
        client.get("https://api.example.com/x")
    with pytest.raises(RateLimited):  # still blocked: fail fast without spending more quota
        client.get("https://api.example.com/y")
    assert count["n"] == 1
    assert all(s < 3600 for s in clock.sleeps)


def test_block_that_expires_soon_is_waited_out():
    calls = iter([httpx.Response(429, headers={"Retry-After": "200"}), httpx.Response(200)])
    client, clock = make(lambda r: next(calls), min_interval=0, max_retry_wait=120)
    with pytest.raises(RateLimited):
        client.get("https://api.example.com/x")
    clock.now += 150  # 50s of the block left, within max_retry_wait
    assert client.get("https://api.example.com/y").status_code == 200
    assert clock.sleeps[-1] == pytest.approx(50)


@pytest.mark.parametrize("status", [401, 403])
def test_auth_errors_disable_the_source(status):
    count = {"n": 0}

    def handler(request):
        count["n"] += 1
        return httpx.Response(status)

    client, _ = make(handler, min_interval=0)
    with pytest.raises(SourceDisabled):
        client.get("https://api.example.com/x")
    with pytest.raises(SourceDisabled):
        client.get("https://api.example.com/y")
    assert count["n"] == 1 and client.disabled


def test_network_errors_are_retried_then_raised():
    def handler(request):
        raise httpx.ConnectError("down")

    client, clock = make(handler, min_interval=0)
    with pytest.raises(SourceError):
        client.get("https://api.example.com/x")
    assert len(clock.sleeps) == 3


def test_secrets_are_redacted_in_errors_and_logs(caplog):
    client, _ = make(lambda r: httpx.Response(500), min_interval=0)
    with caplog.at_level(logging.DEBUG, logger="sweetspot"):
        with pytest.raises(SourceError) as info:
            client.get(f"https://api.example.com/x?key={SECRET}&id=1",
                       headers={"ITAD-API-Key": SECRET})
    assert SECRET not in str(info.value)
    assert SECRET not in caplog.text
    assert "key=***" in str(info.value)


def test_user_agent_is_set():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["User-Agent"]
        return httpx.Response(200)

    client, _ = make(handler)
    client.get("https://api.example.com/x")
    assert seen["ua"].startswith("SweetSpot/") and "personal" in seen["ua"]


def test_response_size_cap():
    client, _ = make(lambda r: httpx.Response(200, content=b"x" * 2048), min_interval=0, max_bytes=1024)
    with pytest.raises(ResponseTooLarge):
        client.get("https://api.example.com/x")


def test_other_client_errors_are_returned_to_caller():
    client, _ = make(lambda r: httpx.Response(404), min_interval=0)
    assert client.get("https://api.example.com/x").status_code == 404
