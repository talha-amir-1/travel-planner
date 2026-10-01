"""Activities specialist: finds sights and food spots matching interests and diet."""

from trippilot.state import TripState
from trippilot.tools import geo, places
from trippilot.tools.errors import ToolError


def activities_agent(state: TripState) -> dict:
    req = state["request"]
    try:
        loc = geo.geocode(req.destination)
        found = places.search_places(
            loc.latitude, loc.longitude, req.interests, req.constraints
        )
    except ToolError as e:
        return {"activities": [], "errors": [f"activities: {e}"]}
    return {"activities": found}
