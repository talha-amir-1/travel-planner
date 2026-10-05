"""The shared state that flows through the multi-agent graph.

Every node reads what it needs from TripState and returns only the keys it changes;
LangGraph merges those updates into the state.
"""

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from trippilot.schemas import (
    Activity,
    BookingConfirmation,
    BudgetReport,
    FlightOption,
    HotelOption,
    Itinerary,
    TripRequest,
    WeatherSummary,
)


def add_or_reset(old: list | None, new: list | None) -> list:
    """Reducer: append new items to the list; a node returning None empties it (re-plan)."""
    if new is None:
        return []
    return (old or []) + new


class TripState(TypedDict, total=False):
    # Conversation with the user; add_messages appends instead of overwriting.
    messages: Annotated[list[AnyMessage], add_messages]

    # Intake
    request: TripRequest | None
    missing_info: list[str]  # what intake still needs to ask the user

    # Specialists (run in parallel)
    flight_options: list[FlightOption]
    hotel_options: list[HotelOption]
    activities: list[Activity]
    weather: WeatherSummary | None
    # Failures reported by specialists, e.g. "flights: SERPAPI_API_KEY not configured".
    # add_or_reset joins lists, so parallel specialists can each add errors safely.
    errors: Annotated[list[str], add_or_reset]

    # Budget: what it picked, the cost breakdown, and replan settings
    selected_flight: FlightOption | None
    selected_hotel: HotelOption | None
    planned_activities: list[Activity]  # sights the budget counted (food spots excluded)
    budget_report: BudgetReport | None
    hotel_max_price: float | None  # nightly cap for a cheaper hotel search on replan
    replan_count: int

    # Composition, approval, booking
    itinerary: Itinerary | None
    approval: Literal["pending", "approved", "changes_requested"] | None
    bookings: list[BookingConfirmation]
