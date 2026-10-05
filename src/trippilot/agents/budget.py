"""Budget agent: picks a flight and hotel, adds up the trip cost, and replans when over budget.

No AI here: money math must be exact. The composer explains the budget to the traveler.

Order of savings when over budget:
1. Keep only free sights (drop paid activities)            -> done here, no new search
2. Search hotels again with a nightly price cap (replan)   -> back to the supervisor,
   which re-runs only the hotel specialist, at most MAX_REPLANS times
"""

from trippilot.schemas import Activity, BudgetLine, BudgetReport, HotelOption, Money
from trippilot.state import TripState
from trippilot.tools import currency
from trippilot.tools.errors import ToolError
from trippilot.tools.places import FOOD_CATEGORIES

# Daily estimates per person, in USD (no API gives these).
FOOD_PER_DAY_USD = 35.0
LOCAL_TRANSPORT_PER_DAY_USD = 10.0
SIGHTS_PER_DAY = 2
MAX_REPLANS = 2


def budget_agent(state: TripState) -> dict:
    req = state["request"]
    cur = req.budget.currency
    try:
        usd = currency.get_rate("USD", cur)  # activity costs and estimates are in USD
    except ToolError as e:
        return {"budget_report": None, "errors": [f"budget: {e}"]}

    days = req.nights + 1  # calendar days, e.g. Dec 10-15 = 6 days
    people = req.travelers
    flights = state.get("flight_options") or []
    flight = flights[0] if flights else None  # options come sorted cheapest first
    food = FOOD_PER_DAY_USD * days * people * usd
    transport = LOCAL_TRANSPORT_PER_DAY_USD * days * people * usd

    # The previous pick stays a candidate, in case a cheaper search finds nothing.
    hotels = state.get("hotel_options") or []
    previous = state.get("selected_hotel")
    if previous and previous.id not in {h.id for h in hotels}:
        hotels = [*hotels, previous]

    def plan(free_only: bool) -> tuple[list[Activity], float, HotelOption | None, float]:
        sights = _plan_sights(state.get("activities") or [], days, free_only)
        sights_cost = sum(a.estimated_cost.amount for a in sights if a.estimated_cost)
        sights_cost *= people * usd
        fixed = (flight.price.amount if flight else 0) + food + transport + sights_cost
        hotel = _pick_hotel(hotels, money_left=req.budget.amount - fixed)
        total = fixed + (hotel.total_price.amount if hotel else 0)
        return sights, sights_cost, hotel, total

    sights, sights_cost, hotel, total = plan(free_only=False)
    if total > req.budget.amount:
        sights, sights_cost, hotel, total = plan(free_only=True)

    over = total > req.budget.amount
    replans = state.get("replan_count", 0)
    if over and hotel and replans < MAX_REPLANS:
        money_for_hotel = req.budget.amount - (total - hotel.total_price.amount)
        if money_for_hotel > 0:
            return {
                "hotel_options": None,  # empty box -> supervisor re-runs only hotels
                "hotel_max_price": money_for_hotel / req.nights,
                "selected_hotel": hotel,
                "replan_count": replans + 1,
            }

    if hotel:
        hotel_note = hotel.name
    else:
        hotel_note = "day trip, no hotel" if req.nights == 0 else "no hotel found, not included"
    lines = [
        _line("flights", flight.price.amount if flight else 0, cur,
              None if flight else "no flight found, not included"),
        _line("hotel", hotel.total_price.amount if hotel else 0, cur, hotel_note),
        _line("activities", sights_cost, cur, f"{len(sights)} sights, estimated entry fees"),
        _line("food", food, cur, f"estimate: {FOOD_PER_DAY_USD:.0f} USD/person/day"),
        _line("local_transport", transport, cur,
              f"estimate: {LOCAL_TRANSPORT_PER_DAY_USD:.0f} USD/person/day"),
    ]
    return {
        "budget_report": BudgetReport(budget=req.budget, lines=lines),
        "selected_flight": flight,
        "selected_hotel": hotel,
        "planned_activities": sights,
    }


def route_after_budget(state: TripState) -> str:
    # hotel_options was emptied -> replan; otherwise write the itinerary
    return "supervisor" if state.get("hotel_options") is None else "composer"


def _plan_sights(activities: list[Activity], days: int, free_only: bool) -> list[Activity]:
    """Sights to count in the budget: up to SIGHTS_PER_DAY a day, best-ranked first.
    Restaurants and cafes are left out: meals are covered by the food estimate."""
    sights = [a for a in activities if a.category not in FOOD_CATEGORIES]
    if free_only:
        sights = [a for a in sights if not a.estimated_cost or a.estimated_cost.amount == 0]
    return sights[: SIGHTS_PER_DAY * days]


def _pick_hotel(options: list[HotelOption], money_left: float) -> HotelOption | None:
    """Best-rated hotel we can afford; if none fits, the cheapest one."""
    if not options:
        return None
    affordable = [h for h in options if h.total_price.amount <= money_left]
    if affordable:
        return max(affordable, key=lambda h: (h.rating or 0, -h.total_price.amount))
    return min(options, key=lambda h: h.total_price.amount)


def _line(category: str, amount: float, cur: str, note: str | None) -> BudgetLine:
    return BudgetLine(category=category, amount=Money(amount=round(amount, 2), currency=cur),
                      note=note)
