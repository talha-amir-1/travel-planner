"""Approval: pauses the graph so the traveler can approve the plan or ask for changes.

- "approve" (or yes / ok / book it) -> booking
- anything else is a change request -> added to the chat, all results cleared, back to
  intake, which reads the change ("make it $1200", "Dec 12-16 instead") and re-plans.
"""

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt

from trippilot.state import TripState

APPROVE_WORDS = {"approve", "approved", "yes", "y", "ok", "book", "book it"}

QUESTION = (
    'Type "approve" to book this trip, or tell me what to change '
    "(dates, budget, interests, ...)."
)

# Everything the planning agents produced; cleared on a change request so they run again.
RESET_ON_CHANGE = {
    "flight_options": None,
    "hotel_options": None,
    "activities": None,
    "weather": None,
    "errors": None,  # add_or_reset empties the list
    "selected_flight": None,
    "selected_hotel": None,
    "planned_activities": None,
    "budget_report": None,
    "hotel_max_price": None,
    "replan_count": 0,
    "itinerary": None,
}


def approval(state: TripState) -> dict:
    report = state["itinerary"].budget_report
    total = f" Total: {report.total} of {report.budget}." if report else ""
    answer = interrupt({"type": "approval", "question": QUESTION + total})

    if answer.strip().lower().rstrip("!.") in APPROVE_WORDS:
        return {"approval": "approved"}
    return {
        **RESET_ON_CHANGE,
        "approval": "changes_requested",
        "messages": [AIMessage(QUESTION), HumanMessage(answer)],
    }


def route_after_approval(state: TripState) -> str:
    return "booking" if state["approval"] == "approved" else "intake"
