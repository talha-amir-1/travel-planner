"""Itinerary composer: the AI writes the day-by-day plan from what the other agents found.

Split of work:
- AI writes:   summary (incl. the budget in plain words), the days, packing tips
- Code fills:  flight, hotel, budget report, item costs, warnings (facts the AI must not change)
- Code checks: every day has the right date, and every activity_id really exists
"""

from datetime import timedelta

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from trippilot.llm import get_llm
from trippilot.schemas import Activity, DayPlan, Itinerary
from trippilot.state import TripState
from trippilot.tools.places import FOOD_CATEGORIES

MAX_FOOD_SPOTS = 10

SYSTEM_PROMPT = """You are a travel planner writing a day-by-day itinerary.

Rules:
- Use only the sights and food spots listed below, referenced by their id. Do not name
  any other specific venue; for free time, write something general ("stroll the old town").
- One day per date listed, in order, each with morning, afternoon and evening items.
- Put sights that are close together (similar coordinates) on the same day, and give the
  day's area as its neighborhood.
- On rainy days prefer indoor sights. Respect opening hours and the weekday.
- Day 1 starts after the flight arrives; keep the last day light for the trip home.
- Fit the traveler's interests and constraints (e.g. vegetarian food spots for meals).
- Summary: 3-5 sentences: the idea of the trip, whether it is within budget and by how
  much (use the numbers given), and any problem listed under "Problems".
- Packing tips: 3-6 short tips based on the weather and the activities."""


class ComposedPlan(BaseModel):
    """What the AI writes; everything else in the Itinerary is filled in by code."""

    summary: str
    days: list[DayPlan]
    packing_tips: list[str] = Field(default_factory=list)


def composer(state: TripState) -> dict:
    req = state["request"]
    sights = state.get("planned_activities") or []
    food = [a for a in state.get("activities") or [] if a.category in FOOD_CATEGORIES]
    food = food[:MAX_FOOD_SPOTS]

    writer = get_llm().with_structured_output(ComposedPlan)
    plan: ComposedPlan = writer.invoke(
        [SystemMessage(SYSTEM_PROMPT), HumanMessage(_trip_facts(state, sights, food))]
    )

    itinerary = Itinerary(
        destination=req.destination,
        start_date=req.start_date,
        end_date=req.end_date,
        summary=plan.summary,
        flight=state.get("selected_flight"),
        hotel=state.get("selected_hotel"),
        days=_checked_days(plan.days, req.start_date, req.nights + 1, sights, food),
        budget_report=state.get("budget_report"),
        packing_tips=plan.packing_tips,
        warnings=state.get("errors") or [],
    )
    return {"itinerary": itinerary}


def _checked_days(
    days: list[DayPlan], start, n_days: int, sights: list[Activity], food: list[Activity]
) -> list[DayPlan]:
    """Fix what the AI may get wrong: dates, unknown activity ids, and costs."""
    known = {a.id: a for a in [*sights, *food]}
    sight_ids = {a.id for a in sights}
    days = days[:n_days]
    for i, day in enumerate(days):
        day.date = start + timedelta(days=i)  # dates come from the request, not the AI
        for item in day.items:
            if item.activity_id not in known:
                item.activity_id = None  # the AI referenced something we never found
            # Only sights carry a cost; meals are covered by the budget's food estimate.
            sight = known[item.activity_id] if item.activity_id in sight_ids else None
            item.cost = sight.estimated_cost if sight else None
    return days


def _trip_facts(state: TripState, sights: list[Activity], food: list[Activity]) -> str:
    """Everything the AI needs, as compact text (cheaper than full JSON)."""
    req = state["request"]
    out = [
        f"Trip: {req.origin} -> {req.destination}, {req.start_date} to {req.end_date}, "
        f"{req.travelers} traveler(s).",
        f"Interests: {', '.join(req.interests) or 'general sightseeing'}. "
        f"Constraints: {', '.join(req.constraints) or 'none'}.",
    ]

    flight = state.get("selected_flight")
    if flight:
        arrive = flight.outbound[-1].arrival_time
        out.append(f"Flight arrives {arrive:%a %b %d %H:%M}; return flight time unknown.")
    hotel = state.get("selected_hotel")
    if hotel:
        where = f" at ({hotel.latitude:.3f}, {hotel.longitude:.3f})" if hotel.latitude else ""
        out.append(f"Hotel: {hotel.name}{where}.")

    weather = state.get("weather")
    out.append("\nDates and weather:")
    for i in range(req.nights + 1):
        day = req.start_date + timedelta(days=i)
        w = next((d for d in weather.days if d.date == day), None) if weather else None
        info = (
            f"{w.description}, {w.temp_min_c}-{w.temp_max_c} C{', RAINY' if w.is_rainy else ''}"
            if w else "weather unknown"
        )
        out.append(f"- {day:%Y-%m-%d %a}: {info}")
    if weather and weather.kind == "historical_estimate":
        out.append("(weather is last year's on the same dates, an estimate)")

    out.append("\nSights (already counted in the budget):")
    out += [_activity_line(a) for a in sights] or ["- none found"]
    out.append("\nFood spots:")
    out += [_activity_line(a) for a in food] or ["- none found"]

    report = state.get("budget_report")
    if report:
        status = "within budget" if report.within_budget else "OVER budget"
        out.append(f"\nBudget: total {report.total} of {report.budget}, {status} "
                   f"(remaining {report.remaining}).")
        out += [f"- {ln.category}: {ln.amount}" + (f" ({ln.note})" if ln.note else "")
                for ln in report.lines]

    if state.get("errors"):
        out.append("\nProblems:")
        out += [f"- {e}" for e in state["errors"]]
    return "\n".join(out)


def _activity_line(a: Activity) -> str:
    parts = [f"- [{a.id}] {a.name} ({a.category}) at ({a.latitude:.3f}, {a.longitude:.3f})"]
    if a.indoor is not None:
        parts.append("indoor" if a.indoor else "outdoor")
    if a.opening_hours:
        parts.append(f"open {a.opening_hours}")
    if a.estimated_cost:
        parts.append(f"~{a.estimated_cost}")
    if a.tags:
        parts.append(", ".join(a.tags))
    return "; ".join(parts)
