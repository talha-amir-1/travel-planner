import shutil
from pathlib import Path

import pytest
import respx
from tenacity import wait_none

from trippilot import config
from trippilot.tools import _common, airports

AIRPORTS_FIXTURE = Path(__file__).parent / "data" / "airports.csv"


@pytest.fixture(autouse=True)
def isolated_tools(monkeypatch, tmp_path):
    """No real network, no API keys from the developer's .env, no caching or retry sleeps,
    and a tiny airports dataset instead of the full OurAirports download."""
    settings = config.Settings(
        _env_file=None, SERPAPI_API_KEY=None, TAVILY_API_KEY=None, LANGSMITH_TRACING=False
    )
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    monkeypatch.setattr(_common._request.retry, "wait", wait_none())

    airports_csv = tmp_path / "airports.csv"
    shutil.copy(AIRPORTS_FIXTURE, airports_csv)
    monkeypatch.setattr(airports, "CACHE_PATH", airports_csv)
    airports.load_airports.cache_clear()
    _common.clear_caches()

    with respx.mock(assert_all_called=False) as router:
        yield router

    _common.clear_caches()
    airports.load_airports.cache_clear()


@pytest.fixture
def serpapi_key(monkeypatch):
    settings = config.Settings(_env_file=None, SERPAPI_API_KEY="test-key")
    monkeypatch.setattr(config, "get_settings", lambda: settings)
