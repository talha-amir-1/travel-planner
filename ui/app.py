"""TripPilot web UI: chat with the multi-agent graph, see each agent work, approve the plan.

    uv run streamlit run ui/app.py

The app drives the same graph as the terminal runner (trippilot.graph.build_graph):
- a chat message starts the graph, or answers a pause (intake question / change request)
- graph.stream() reports each agent as it finishes -> shown as steps in the chat
- at the approval pause the plan is shown with an "Approve and book" button
"""

import uuid

import pandas as pd
import streamlit as st
from langgraph.types import Command

from trippilot.graph import build_graph

st.set_page_config(page_title="TripPilot", page_icon=":material/flight_takeoff:", layout="wide")

# What each agent's step says when it finishes. The values are its update to the state.
STEP_LABELS = {
    "intake": lambda u: "Understood your request" if u.get("request") else "Need more details",
    "ask_user": lambda u: "Got your answer",
    "supervisor": lambda u: "Sent the specialists to work",
    "flights": lambda u: f"Flights: {len(u.get('flight_options') or [])} options",
    "hotels": lambda u: f"Hotels: {len(u.get('hotel_options') or [])} options",
    "activities": lambda u: f"Activities: {len(u.get('activities') or [])} places",
    "weather": lambda u: "Weather checked" if u.get("weather") else "Weather unavailable",
    "budget": lambda u: (
        "Over budget, looking for a cheaper hotel" if "replan_count" in u else "Budget calculated"
    ),
    "composer": lambda u: "Wrote the day-by-day plan",
    "approval": lambda u: "Re-planning with your changes",
    "booking": lambda u: f"Booked {len(u.get('bookings') or [])} item(s)",
}


@st.cache_resource
def get_graph():
    # One graph for all sessions; each browser session uses its own thread_id.
    return build_graph()


def new_trip() -> None:
    st.session_state.thread_id = str(uuid.uuid4())
    st.session_state.chat = []  # [{"role": "user" | "assistant", "content": str}]
    st.session_state.pause = None  # the graph's current interrupt value, if paused


if "thread_id" not in st.session_state:
    new_trip()

graph = get_graph()
config = {"configurable": {"thread_id": st.session_state.thread_id}}


def run_graph(graph_input) -> None:
    """Run the graph until it pauses or ends, showing each agent as a step in the chat."""
    st.session_state.pause = None
    with (
        st.chat_message("assistant"),
        st.status(":shimmer[Planning your trip]", type="compact") as status,
    ):
        try:
            for update in graph.stream(graph_input, config, stream_mode="updates"):
                for node, values in update.items():
                    if node == "__interrupt__":
                        st.session_state.pause = values[0].value
                    elif node in STEP_LABELS:
                        label = STEP_LABELS[node](values or {})
                        st.status(label, type="step", state="complete")
        except Exception as e:  # e.g. the Gemini quota is used up
            status.update(label="Something went wrong", state="error")
            st.session_state.chat.append({"role": "assistant", "content": f"Error: {e}"})
            return
        status.update(label="Done", state="complete")

    pause = st.session_state.pause
    if pause and pause["type"] == "missing_info":
        reply = pause["question"]
    elif pause and pause["type"] == "approval":
        reply = "Here is your plan. " + pause["question"]
    else:
        reply = "Your trip is booked. Have a great time!"
    st.session_state.chat.append({"role": "assistant", "content": reply})


def show_plan(values: dict) -> None:
    itinerary = values.get("itinerary")
    report = values.get("budget_report")
    if not itinerary:
        return

    st.header(f"{itinerary.destination}, {itinerary.start_date:%b %d} - {itinerary.end_date:%b %d}")
    st.write(itinerary.summary)
    for warning in itinerary.warnings:
        st.warning(warning, icon=":material/warning:")

    if report:
        with st.container(horizontal=True):
            st.metric("Total", str(report.total), border=True)
            st.metric("Budget", str(report.budget), border=True)
            st.metric("Remaining", f"{report.remaining:,.2f}", border=True,
                      delta="within budget" if report.within_budget else "over budget",
                      delta_color="normal" if report.within_budget else "inverse")

    flight_col, hotel_col = st.columns(2)
    with flight_col, st.container(border=True):
        st.subheader(":material/flight: Flight")
        if itinerary.flight:
            f = itinerary.flight
            first, last = f.outbound[0], f.outbound[-1]
            st.write(f"**{first.departure_airport} -> {last.arrival_airport}**, "
                     f"{f.stops} stop(s), {f.price}")
            st.caption(f"{first.airline}, departs {first.departure_time:%b %d %H:%M}, "
                       f"arrives {last.arrival_time:%b %d %H:%M}")
        else:
            st.caption("No flight found")
    with hotel_col, st.container(border=True):
        st.subheader(":material/hotel: Hotel")
        if itinerary.hotel:
            h = itinerary.hotel
            stars = f", {h.stars:.0f} stars" if h.stars else ""
            rating = f", rated {h.rating}/5" if h.rating else ""
            st.write(f"**{h.name}**{stars}{rating}")
            st.caption(f"{h.total_price} total ({h.price_per_night} per night)")
        else:
            st.caption("No hotel found")

    plan_tab, budget_tab, map_tab = st.tabs(["Day by day", "Budget", "Map"])
    with plan_tab:
        for i, day in enumerate(itinerary.days):
            area = f" - {day.neighborhood}" if day.neighborhood else ""
            with st.expander(f"{day.date:%a %b %d}: {day.title}{area}", expanded=i == 0):
                if day.weather_note:
                    st.caption(day.weather_note)
                for item in day.items:
                    cost = f" ({item.cost})" if item.cost else ""
                    st.markdown(f"**{item.time_slot.capitalize()}:** {item.title}{cost}")
                    if item.notes:
                        st.caption(item.notes)
        if itinerary.packing_tips:
            st.subheader("Packing tips")
            st.markdown("\n".join(f"- {tip}" for tip in itinerary.packing_tips))
    with budget_tab:
        if report:
            st.table(pd.DataFrame(
                [{"Category": ln.category.replace("_", " "), "Amount": str(ln.amount),
                  "Note": ln.note or ""} for ln in report.lines]
            ))
    with map_tab:
        places = values.get("planned_activities") or []
        if places:
            st.map(pd.DataFrame([{"lat": a.latitude, "lon": a.longitude} for a in places]))
        else:
            st.caption("No places to show")


def show_bookings(values: dict) -> None:
    bookings = values.get("bookings") or []
    if bookings:
        st.success("Booked (mock booking, no real reservation)", icon=":material/check_circle:")
        st.table(pd.DataFrame(
            [{"Item": b.kind, "Amount": str(b.amount), "Confirmation": b.confirmation_code}
             for b in bookings]
        ))


# --- Page -------------------------------------------------------------------

with st.sidebar:
    st.title(":material/flight_takeoff: TripPilot")
    st.caption("A multi-agent travel planner built with LangGraph.")
    if st.button("New trip", icon=":material/add:", width="stretch"):
        new_trip()
        st.rerun()

for msg in st.session_state.chat:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

values = graph.get_state(config).values  # the trip so far, saved by the checkpointer
pause = st.session_state.pause
trip_done = bool(values.get("bookings"))

if trip_done:
    placeholder = "Start a new trip from the sidebar"
elif pause and pause["type"] == "approval":
    placeholder = "Ask for changes, e.g. make it $1200"
elif pause:
    placeholder = "Your answer"
else:
    placeholder = "e.g. Lahore to Istanbul, Dec 10-15, $1500, food and history, vegetarian"

prompt = st.chat_input(placeholder, disabled=trip_done, submit_mode="disable")

if pause and pause["type"] == "approval":
    if st.button("Approve and book", icon=":material/check:", type="primary"):
        st.session_state.chat.append({"role": "user", "content": "Approve"})
        run_graph(Command(resume="approve"))
        st.rerun()
    show_plan(values)
show_bookings(values)

if prompt:
    st.session_state.chat.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    # Paused -> the message answers the pause; otherwise it starts (or restarts) the graph.
    run_graph(Command(resume=prompt) if pause else {"messages": [("user", prompt)]})
    st.rerun()
