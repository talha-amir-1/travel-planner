"""Shared HTTP client for the tools: one connection pool, a User-Agent and timeouts."""

from typing import Any

import httpx

from trippilot.tools.errors import ExternalAPIError

USER_AGENT = "TripPilot/0.1 (portfolio travel-planner project)"
DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

_client = httpx.Client(
    timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True
)


def request(method: str, url: str, **kwargs: Any) -> httpx.Response:
    """Send a request and raise httpx.HTTPStatusError on a 4xx/5xx response."""
    response = _client.request(method, url, **kwargs)
    response.raise_for_status()
    return response


def request_json(
    service: str,
    url: str,
    *,
    method: str = "GET",
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> Any:
    """Call an API and return parsed JSON, raising ExternalAPIError on any failure."""
    kwargs: dict[str, Any] = {"params": params, "data": data}
    if timeout is not None:
        kwargs["timeout"] = timeout
    try:
        return request(method, url, **kwargs).json()
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        raise ExternalAPIError(service, f"HTTP {status}", status) from e
    except (httpx.HTTPError, ValueError) as e:
        raise ExternalAPIError(service, f"{type(e).__name__}: {e}") from e
