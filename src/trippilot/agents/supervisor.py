"""Supervisor: decides which specialists to run and runs them in parallel with Send.

A specialist runs when its result is missing (None). On the first pass that is all four.
Later, a replan (over budget, or the user asks for a cheaper hotel) sets just the affected
result back to None, and the supervisor re-runs only that specialist.
"""

from langgraph.graph import END
from langgraph.types import Send

from trippilot.state import TripState

# graph node name -> the state key that node fills
SPECIALISTS = {
    "flights": "flight_options",
    "hotels": "hotel_options",
    "activities": "activities",
    "weather": "weather",
}


def supervisor(state: TripState) -> dict:
    # The routing decision happens in route_to_specialists; this node is the hub that
    # intake and (later) budget/replan point to.
    return {}


def route_to_specialists(state: TripState) -> list[Send] | str:
    jobs = [
        Send(node, state) for node, key in SPECIALISTS.items() if state.get(key) is None
    ]
    return jobs or END
