"""Phase 2 baseline: one ReAct agent with every tool, no orchestration.

It exists to be compared against the multi-agent graph (Phase 3), so keep it simple.

    uv run python -m trippilot.agents.single_agent "5 days in Istanbul in December, $1500"
"""

import argparse
import sys
import time
from datetime import date

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage

from trippilot.llm import get_llm
from trippilot.tools.agent_tools import ALL_TOOLS

SYSTEM_PROMPT = """You are TripPilot, a travel planner. Today is {today}.

Given a trip request, use your tools to build a realistic plan:
1. Work out origin, destination, dates, number of travelers, budget and interests.
   If the origin or dates are missing, make a sensible assumption and state it.
2. Check the weather, search flights and hotels, and find activities that match the interests.
3. Pick one flight and one hotel and keep the total cost within the budget
   (flights + hotel + activities + an estimate for food and local transport).
   Convert currencies when needed.

Only use prices and places returned by your tools; never invent them. If a tool fails,
say what is missing instead of guessing.

Reply with:
- Summary (assumptions included)
- Flight and hotel chosen, with prices
- Day-by-day plan (morning / afternoon / evening), with rainy days indoors
- Budget breakdown and total vs budget
- Weather and packing tips"""


def build_agent(model: BaseChatModel | None = None):
    prompt = SYSTEM_PROMPT.format(today=date.today().isoformat())
    return create_agent(model or get_llm(), ALL_TOOLS, system_prompt=prompt)


def run(request: str, model: BaseChatModel | None = None, verbose: bool = True) -> dict:
    """Run the agent on one request; returns the final answer plus simple run stats."""
    agent = build_agent(model)
    started = time.perf_counter()
    tool_calls = 0
    final: AIMessage | None = None

    for update in agent.stream(
        {"messages": [{"role": "user", "content": request}]}, stream_mode="updates"
    ):
        for node_output in update.values():
            for msg in (node_output or {}).get("messages", []):
                if isinstance(msg, AIMessage):
                    for call in msg.tool_calls:
                        tool_calls += 1
                        if verbose:
                            print(f"-> {call['name']}({call['args']})")
                    if not msg.tool_calls:
                        final = msg
                elif isinstance(msg, ToolMessage) and verbose and msg.text.startswith("Error"):
                    print(f"   {msg.name} failed: {msg.text}")

    return {
        "answer": final.text if final else "",
        "tool_calls": tool_calls,
        "seconds": round(time.perf_counter() - started, 1),
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    parser = argparse.ArgumentParser(description="Plan a trip with the single-agent baseline.")
    parser.add_argument("request", nargs="?", help="Trip request; prompted for if omitted")
    args = parser.parse_args()
    request = args.request or input("Where do you want to go? ")

    result = run(request)
    print("\n" + result["answer"])
    print(f"\n[{result['tool_calls']} tool calls, {result['seconds']}s]")


if __name__ == "__main__":
    main()
