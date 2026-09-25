"""Shared plumbing for tools: typed errors, HTTP with timeouts/retries, TTL caching."""

import functools
from collections.abc import Callable
from typing import Any

import httpx
from cachetools import TTLCache
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

USER_AGENT = "TripPilot/0.1 (portfolio travel-planner project)"
DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class ToolError(Exception):
    """Base class for all tool failures."""


class NotFoundError(ToolError):
    """The requested entity (city, route, ...) does not exist."""


class ExternalAPIError(ToolError):
    """An upstream API failed after retries."""

    def __init__(self, service: str, message: str, status_code: int | None = None):
        self.service = service
        self.status_code = status_code
        super().__init__(f"{service}: {message}")


# --- HTTP -------------------------------------------------------------------

_client = httpx.Client(
    timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True
)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


@retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, max=4),
    reraise=True,
)
def _request(method: str, url: str, **kwargs: Any) -> httpx.Response:
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
        return _request(method, url, **kwargs).json()
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        raise ExternalAPIError(service, f"HTTP {status}", status) from e
    except (httpx.HTTPError, ValueError) as e:
        raise ExternalAPIError(service, f"{type(e).__name__}: {e}") from e


# --- Caching ----------------------------------------------------------------

_caches: list[TTLCache] = []


def ttl_cache(ttl: int, maxsize: int = 256) -> Callable:
    """Memoize a function with hashable args for `ttl` seconds."""

    def decorator(fn: Callable) -> Callable:
        cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)
        _caches.append(cache)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = (args, tuple(sorted(kwargs.items())))
            if key in cache:
                return cache[key]
            result = fn(*args, **kwargs)
            cache[key] = result
            return result

        return wrapper

    return decorator


def clear_caches() -> None:
    for cache in _caches:
        cache.clear()
