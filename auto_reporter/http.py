from __future__ import annotations

import time

import httpx

RETRY_STATUS = {429, 500, 502, 503, 504}


def request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    attempts: int = 3,
    backoff_seconds: float = 1.0,
    **kwargs,
) -> httpx.Response:
    response: httpx.Response | None = None
    for attempt in range(attempts):
        response = client.request(method, url, **kwargs)
        if response.status_code not in RETRY_STATUS:
            response.raise_for_status()
            return response
        if attempt < attempts - 1:
            time.sleep(backoff_seconds * 2**attempt)
    assert response is not None
    response.raise_for_status()
    return response
