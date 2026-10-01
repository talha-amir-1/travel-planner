"""Builds the multi-agent graph. Grows phase by phase.

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
                                                                  (ok) +--> END
    (next: the composer comes after budget instead of END)

    uv run python -m trippilot.graph "5 days in Istanbul in December"
"""

import argparse
import sys
import uuid

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from trippilot.agents.activities import activities_agent
from trippilot.agents.budget import budget_agent, route_after_budget
from trippilot.agents.flights import flight_agent
from trippilot.agents.hotels import hotel_agent
from trippilot.agents.intake import ask_user, intake, route_after_intake
from trippilot.agents.supervisor import SPECIALISTS, route_to_specialists, supervisor
from trippilot.agents.weather import weather_agent
from trippilot.state import TripState


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

    builder.add_edge(START, "intake")
    builder.add_conditional_edges("intake", route_after_intake, ["ask_user", "supervisor"])
    builder.add_edge("ask_user", "intake")
    builder.add_conditional_edges("supervisor", route_to_specialists, [*SPECIALISTS, END])
    for node in SPECIALISTS:
        builder.add_edge(node, "budget")  # budget waits for all specialists sent together
    builder.add_conditional_edges("budget", route_after_budget, ["supervisor", END])

    # A checkpointer is required for interrupt(): it saves the paused state between turns.
    return builder.compile(checkpointer=checkpointer or InMemorySaver())


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    parser = argparse.ArgumentParser(description="Run the TripPilot graph in the terminal.")
    parser.add_argument("request", help="Trip request")
    args = parser.parse_args()

    graph = build_graph()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    result = graph.invoke({"messages": [("user", args.request)]}, config)

    # While the graph is paused at an interrupt, show the question and resume with the answer.
    while "__interrupt__" in result:
        question = result["__interrupt__"][0].value["question"]
        answer = input(f"\n{question}\n> ")
        result = graph.invoke(Command(resume=answer), config)

    print("\nTrip request:")
    print(result["request"].model_dump_json(indent=2))


if __name__ == "__main__":
    main()
