"""Flight specialist: searches round-trip flights for the request."""

from trippilot.state import TripState
from trippilot.tools import flights
from trippilot.tools.errors import ToolError


def flight_agent(state: TripState) -> dict:
    req = state["request"]
    try:
        options = flights.search_flights(
            req.origin,
            req.destination,
            req.start_date,
            req.end_date,
            travelers=req.travelers,
            currency=req.budget.currency,
        )
    except ToolError as e:
        return {"flight_options": [], "errors": [f"flights: {e}"]}
    return {"flight_options": options}
