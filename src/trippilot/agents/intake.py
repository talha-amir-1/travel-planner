"""Intake agent: turns the conversation into a TripRequest, or says what is still missing.

Two graph nodes:
- intake:   LLM structured output -> TripRequestDraft -> TripRequest (or a list of gaps)
- ask_user: pauses the graph with interrupt() and adds the user's answer to the chat

They are separate so that resuming after interrupt() re-runs only ask_user (no LLM call).
"""

from datetime import date

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from trippilot.llm import get_llm
from trippilot.schemas import Money, TripRequest
from trippilot.state import TripState

SYSTEM_PROMPT = """You extract trip details from a conversation with a traveler. Today is {today}.

Fill only what the traveler actually said; leave a field empty if they did not say it.
- Dates: resolve relative dates ("next Friday", "Dec 10-15") using today's date and assume
  the next occurrence in the future. A month or a duration alone ("5 days in December")
  is not enough for exact dates: leave the dates empty.
- Budget: the total for the whole trip. "$" means USD.
- Interests: short keywords, e.g. "food", "history", "nightlife".
- Constraints: dietary needs and travel preferences, e.g. "vegetarian", "no red-eye flights".
Later messages override earlier ones."""

QUESTIONS = {
    "origin": "Which city are you traveling from?",
    "destination": "Where would you like to go?",
    "dates": "What are your exact travel dates (start and end)?",
    "budget": "What is your total budget for the trip, and in which currency?",
}


class TripRequestDraft(BaseModel):
    """Trip details as far as the traveler has given them; empty fields are unknown."""

    origin: str | None = Field(None, description="Departure city or IATA code")
    destination: str | None = Field(None, description="Destination city")
    start_date: date | None = None
    end_date: date | None = None
    travelers: int = Field(1, ge=1)
    budget_amount: float | None = Field(None, description="Total trip budget")
    budget_currency: str = Field("USD", description="ISO 4217 code")
    interests: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)

    def missing(self) -> list[str]:
        gaps = [f for f in ("origin", "destination") if not getattr(self, f)]
        if not (self.start_date and self.end_date) or self.end_date < self.start_date:
            gaps.append("dates")
        if not self.budget_amount:
            gaps.append("budget")
        return gaps

    def to_request(self) -> TripRequest:
        return TripRequest(
            origin=self.origin,
            destination=self.destination,
            start_date=self.start_date,
            end_date=self.end_date,
            travelers=self.travelers,
            budget=Money(amount=self.budget_amount, currency=self.budget_currency),
            interests=self.interests,
            constraints=self.constraints,
        )


def intake(state: TripState) -> dict:
    extractor = get_llm(temperature=0).with_structured_output(TripRequestDraft)
    prompt = SystemMessage(SYSTEM_PROMPT.format(today=date.today().isoformat()))
    draft: TripRequestDraft = extractor.invoke([prompt, *state["messages"]])

    missing = draft.missing()
    if missing:
        return {"request": None, "missing_info": missing}
    return {"request": draft.to_request(), "missing_info": []}


def ask_user(state: TripState) -> dict:
    question = "To plan your trip I need a bit more information:\n" + "\n".join(
        f"- {QUESTIONS[gap]}" for gap in state["missing_info"]
    )
    answer = interrupt({"type": "missing_info", "question": question})
    return {"messages": [AIMessage(question), HumanMessage(answer)]}


def route_after_intake(state: TripState) -> str:
    return "ask_user" if state["missing_info"] else "supervisor"
