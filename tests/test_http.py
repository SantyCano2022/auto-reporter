import httpx
import pytest
import respx

from auto_reporter import http as http_mod
from auto_reporter.http import request_with_retry


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(http_mod.time, "sleep", lambda _: None)


@respx.mock
def test_retries_on_5xx_then_succeeds():
    route = respx.get("https://api.test/x").mock(side_effect=[
        httpx.Response(500), httpx.Response(502), httpx.Response(200, json={"ok": True}),
    ])
    with httpx.Client() as client:
        resp = request_with_retry(client, "GET", "https://api.test/x")
    assert resp.json() == {"ok": True}
    assert route.call_count == 3


@respx.mock
def test_raises_after_exhausting_attempts():
    respx.get("https://api.test/x").mock(return_value=httpx.Response(429))
    with httpx.Client() as client, pytest.raises(httpx.HTTPStatusError):
        request_with_retry(client, "GET", "https://api.test/x")


@respx.mock
def test_no_retry_on_4xx_other_than_429():
    route = respx.get("https://api.test/x").mock(return_value=httpx.Response(404))
    with httpx.Client() as client, pytest.raises(httpx.HTTPStatusError):
        request_with_retry(client, "GET", "https://api.test/x")
    assert route.call_count == 1
