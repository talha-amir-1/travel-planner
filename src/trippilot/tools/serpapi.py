"""Thin SerpAPI client shared by the flights and hotels tools."""

from typing import Any

from trippilot import config
from trippilot.tools._common import ExternalAPIError, request_json

SERPAPI_URL = "https://serpapi.com/search.json"


def serpapi_key() -> str | None:
    key = config.get_settings().serpapi_api_key
    return key.get_secret_value() if key else None


def serpapi_search(engine: str, params: dict[str, Any]) -> dict:
    key = serpapi_key()
    if not key:
        raise ExternalAPIError("serpapi", "SERPAPI_API_KEY not configured")
    data = request_json(
        f"serpapi-{engine}",
        SERPAPI_URL,
        params={"engine": engine, "api_key": key, "hl": "en", **params},
        timeout=30,
    )
    if "error" in data:
        raise ExternalAPIError(f"serpapi-{engine}", data["error"])
    return data
