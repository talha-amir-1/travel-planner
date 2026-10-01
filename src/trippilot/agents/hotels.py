"""Hotel specialist: searches hotels for the trip dates.

On a budget replan, hotel_max_price (set by the budget agent) limits the nightly rate.
"""

from trippilot.state import TripState
from trippilot.tools import hotels
from trippilot.tools.errors import ToolError


def hotel_agent(state: TripState) -> dict:
    req = state["request"]
    if req.nights == 0:  # day trip, no hotel needed
        return {"hotel_options": []}
    try:
        options = hotels.search_hotels(
            req.destination,
            req.start_date,
            req.end_date,
            guests=req.travelers,
            currency=req.budget.currency,
            max_price=state.get("hotel_max_price"),
        )
    except ToolError as e:
        return {"hotel_options": [], "errors": [f"hotels: {e}"]}
    return {"hotel_options": options}
