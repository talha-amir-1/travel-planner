import shutil
from pathlib import Path

import pytest
import respx

from trippilot import config
from trippilot.tools import airports

AIRPORTS_FIXTURE = Path(__file__).parent / "data" / "airports.csv"


@pytest.fixture(autouse=True)
def isolated_tools(monkeypatch, tmp_path):
    """No real network, no API keys from the developer's .env, and
    a tiny airports dataset instead of the full OurAirports download."""
    settings = config.Settings(
        _env_file=None, SERPAPI_API_KEY=None, TAVILY_API_KEY=None, LANGSMITH_TRACING=False
    )
    monkeypatch.setattr(config, "get_settings", lambda: settings)

    airports_csv = tmp_path / "airports.csv"
    shutil.copy(AIRPORTS_FIXTURE, airports_csv)
    monkeypatch.setattr(airports, "CACHE_PATH", airports_csv)
    airports.load_airports.cache_clear()

    with respx.mock(assert_all_called=False) as router:
        yield router

    airports.load_airports.cache_clear()


@pytest.fixture
def serpapi_key(monkeypatch):
    settings = config.Settings(_env_file=None, SERPAPI_API_KEY="test-key")
    monkeypatch.setattr(config, "get_settings", lambda: settings)
