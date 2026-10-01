"""Weather specialist: daily weather for the trip (forecast or last year's estimate).

Packing tips are written later by the itinerary composer, which sees the whole plan.
"""

from trippilot.state import TripState
from trippilot.tools import geo, weather
from trippilot.tools.errors import ToolError


def weather_agent(state: TripState) -> dict:
    req = state["request"]
    try:
        loc = geo.geocode(req.destination)
        summary = weather.get_weather(
            loc.latitude, loc.longitude, req.start_date, req.end_date, loc.name
        )
    except ToolError as e:
        return {"weather": None, "errors": [f"weather: {e}"]}
    return {"weather": summary}
