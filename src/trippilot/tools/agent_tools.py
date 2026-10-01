"""LangChain tool wrappers around the plain tool functions, for use by agents.

Each wrapper takes LLM-friendly arguments (city names, ISO dates), returns compact JSON-able
data, and turns a ToolError into an "Error: ..." string so the agent can recover or explain.
"""

import functools
from collections.abc import Callable
from datetime import date
from typing import Any

from langchain_core.tools import tool
from pydantic_core import to_jsonable_python

from trippilot.schemas import Money
from trippilot.tools import currency, flights, geo, hotels, places, weather
from trippilot.tools.errors import ToolError


def _safe(fn: Callable) -> Callable:
    """Return tool errors to the model as text instead of crashing the agent."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return to_jsonable_python(fn(*args, **kwargs), exclude_none=True)
        except ToolError as e:
            return f"Error: {e}"

    return wrapper


@tool
@_safe
def lookup_city(place: str):
    """Look up a city: coordinates, country, timezone and nearby airport IATA codes."""
    return geo.geocode(place)


@tool
@_safe
def get_weather(place: str, start_date: date, end_date: date):
    """Daily weather for a city between two dates (YYYY-MM-DD). Uses the forecast for the
    next 16 days, otherwise last year's weather on the same dates as an estimate."""
    loc = geo.geocode(place)
    return weather.get_weather(loc.latitude, loc.longitude, start_date, end_date, loc.name)


@tool
@_safe
def find_activities(place: str, interests: list[str], constraints: list[str] | None = None):
    """Find attractions, sights and food spots in a city matching the traveler's interests
    (e.g. "history", "food", "art"). Dietary constraints ("vegetarian", "vegan") filter
    restaurants. Each result has a typical cost per person and duration."""
    loc = geo.geocode(place)
    return places.search_places(loc.latitude, loc.longitude, interests, constraints, limit=15)


@tool
@_safe
def search_flights(
    origin: str,
    destination: str,
    depart_date: date,
    return_date: date | None = None,
    travelers: int = 1,
    currency: str = "USD",
):
    """Search live flights, cheapest first. origin/destination can be city names or IATA
    codes. Give return_date for a round trip. Prices are totals for all travelers."""
    return flights.search_flights(
        origin, destination, depart_date, return_date, travelers, currency
    )


@tool
@_safe
def search_hotels(
    destination: str, check_in: date, check_out: date, guests: int = 1, currency: str = "USD"
):
    """Search live hotel offers in a city for the given dates, with nightly and total prices."""
    return hotels.search_hotels(destination, check_in, check_out, guests, currency)


@tool
@_safe
def convert_currency(amount: float, from_currency: str, to_currency: str):
    """Convert an amount between currencies (ISO codes like USD, EUR, PKR) at today's rate."""
    return currency.convert(Money(amount=amount, currency=from_currency), to_currency)


ALL_TOOLS = [
    lookup_city,
    get_weather,
    find_activities,
    search_flights,
    search_hotels,
    convert_currency,
]
