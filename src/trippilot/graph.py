"""Builds the multi-agent graph and runs it in the terminal.

    START -> intake --(missing)--> ask_user (interrupt: waits for the user) --+
               ^                                                              |
               +--------------------------------------------------------------+
               |
               +--(complete)--> supervisor --Send (in parallel)--> flights    --+
                                  ^                            --> hotels       |
                                  |                            --> activities   |
                                  |                            --> weather    --+
                                  |                                             |
                                  +--(over budget: cheaper hotel)-- budget <----+
                                                                      |
                                                                 (ok) v
               intake <--(changes)-- approval (interrupt) <-- composer (AI)
                                        |
                                  (approved) +--> booking (mock) --> END

    uv run python -m trippilot.graph "5 days in Istanbul in December"
"""

import argparse
import sys
import uuid

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from pydantic import BaseModel

from trippilot import schemas
from trippilot.agents.activities import activities_agent
from trippilot.agents.approval import approval, route_after_approval
from trippilot.agents.booking import booking
from trippilot.agents.budget import budget_agent, route_after_budget
from trippilot.agents.composer import composer
from trippilot.agents.flights import flight_agent
from trippilot.agents.hotels import hotel_agent
from trippilot.agents.intake import ask_user, intake, route_after_intake
from trippilot.agents.supervisor import SPECIALISTS, route_to_specialists, supervisor
from trippilot.agents.weather import weather_agent
from trippilot.config import PROJECT_ROOT
from trippilot.state import TripState

DIAGRAM = PROJECT_ROOT / "docs" / "graph.md"  # GitHub renders the mermaid block as a picture

# The checkpointer saves our Pydantic models; LangGraph wants them listed as safe to load.
SAFE_TYPES = [
    (schemas.__name__, name)
    for name, obj in vars(schemas).items()
    if isinstance(obj, type) and issubclass(obj, BaseModel) and obj.__module__ == schemas.__name__
]


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    builder = StateGraph(TripState)
    builder.add_node("intake", intake)
    builder.add_node("ask_user", ask_user)
    builder.add_node("supervisor", supervisor)
    builder.add_node("flights", flight_agent)
    builder.add_node("hotels", hotel_agent)
    builder.add_node("activities", activities_agent)
    builder.add_node("weather", weather_agent)
    builder.add_node("budget", budget_agent)
    builder.add_node("composer", composer)
    builder.add_node("approval", approval)
    builder.add_node("booking", booking)

    builder.add_edge(START, "intake")
    builder.add_conditional_edges("intake", route_after_intake, ["ask_user", "supervisor"])
    builder.add_edge("ask_user", "intake")
    builder.add_conditional_edges("supervisor", route_to_specialists, [*SPECIALISTS, END])
    for node in SPECIALISTS:
        builder.add_edge(node, "budget")  # budget waits for all specialists sent together
    builder.add_conditional_edges("budget", route_after_budget, ["supervisor", "composer"])
    builder.add_edge("composer", "approval")
    # The only way into booking is through approval: the guardrail is the graph itself.
    builder.add_conditional_edges("approval", route_after_approval, ["booking", "intake"])
    builder.add_edge("booking", END)

    # A checkpointer is required for interrupt(): it saves the paused state between turns.
    if checkpointer is None:
        serde = JsonPlusSerializer(allowed_msgpack_modules=SAFE_TYPES)
        checkpointer = InMemorySaver(serde=serde)
    return builder.compile(checkpointer=checkpointer)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    parser = argparse.ArgumentParser(description="Run the TripPilot graph in the terminal.")
    parser.add_argument("request", nargs="?", help="Trip request")
    parser.add_argument("--draw", action="store_true", help=f"Save the graph to {DIAGRAM}")
    args = parser.parse_args()

    graph = build_graph()
    if args.draw:
        DIAGRAM.parent.mkdir(exist_ok=True)
        mermaid = graph.get_graph().draw_mermaid()
        DIAGRAM.write_text(f"# TripPilot graph\n\n```mermaid\n{mermaid}```\n", encoding="utf-8")
        print(f"Saved {DIAGRAM}")
        return
    if not args.request:
        parser.error("a trip request is required")
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    result = graph.invoke({"messages": [("user", args.request)]}, config)

    # While the graph is paused at an interrupt, show the question and resume with the answer.
    while "__interrupt__" in result:
        pause = result["__interrupt__"][0].value
        if pause["type"] == "approval":
            print_plan(result)
        answer = input(f"\n{pause['question']}\n> ")
        result = graph.invoke(Command(resume=answer), config)

    print("\nBooked:")
    for b in result.get("bookings") or []:
        print(f"  {b.kind:<8}{b.amount}  confirmation {b.confirmation_code}")


def print_plan(state: dict) -> None:
    req = state["request"]
    print(f"\n{req.origin} -> {req.destination}, {req.start_date} to {req.end_date}, "
          f"{req.travelers} traveler(s), budget {req.budget}")

    report = state.get("budget_report")
    if report:
        print("\nBudget:")
        for line in report.lines:
            note = f"  ({line.note})" if line.note else ""
            print(f"  {line.category:<16}{line.amount}{note}")
        status = "within budget" if report.within_budget else "OVER BUDGET"
        print(f"  {'total':<16}{report.total}  -> {status}, remaining {report.remaining}")
        if state.get("replan_count"):
            print(f"  (searched for a cheaper hotel {state['replan_count']} time(s))")

    itinerary = state.get("itinerary")
    if itinerary:
        print(f"\n{itinerary.summary}")
        for day in itinerary.days:
            area = f" - {day.neighborhood}" if day.neighborhood else ""
            print(f"\n{day.date:%a %b %d}: {day.title}{area}")
            if day.weather_note:
                print(f"  ({day.weather_note})")
            for item in day.items:
                cost = f"  [{item.cost}]" if item.cost else ""
                print(f"  {item.time_slot:<10}{item.title}{cost}")
        if itinerary.packing_tips:
            print("\nPacking tips:")
            for tip in itinerary.packing_tips:
                print(f"  - {tip}")

    for error in state.get("errors") or []:
        print(f"Problem: {error}")


if __name__ == "__main__":
    main()
