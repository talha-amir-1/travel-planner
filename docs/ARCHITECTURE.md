# TripPilot — Architecture

A guide to what TripPilot does, why it is agentic, and how it is built. Written so a
developer or another LLM can understand and safely change the code.

## 1. What it does

A multi-agent travel planner. One sentence in, for example:

> "Lahore to Istanbul, Dec 10-15, $1500, I love food and history, vegetarian"

→ real flights, a hotel, weather, sights and food spots, a budget breakdown and a
day-by-day itinerary → the user **approves or asks for changes** → a **mock** booking
with fake confirmation codes.

- **Stack:** LangGraph (orchestration), LangChain (`init_chat_model`), Gemini (default
  LLM, swappable via env), Pydantic (schemas and structured output), Streamlit (UI),
  httpx, uv.
- **External APIs:** SerpAPI (Google Flights and Google Hotels), Open-Meteo (geocoding,
  forecast and historical weather), OpenStreetMap Overpass (places), OurAirports CSV
  (airports), Frankfurter and ExchangeRate-API (currency).
- **Entry points:**
  - `ui/app.py`: Streamlit app (live at trippilot.streamlit.app)
  - `python -m trippilot.graph "<request>"`: CLI
  - `python -m trippilot.graph --draw`: regenerates `docs/graph.md`
  - `python -m trippilot.agents.single_agent`: single-agent baseline

## 2. Why it is agentic AI

A **stateful, cyclic graph of cooperating agents**, not one prompt:

1. **Decomposition and parallel routing.** A supervisor fans specialist jobs out in
   parallel with LangGraph `Send`.
2. **Self-correcting loops.** When over budget, the budget agent triggers a replan. The
   supervisor re-runs only the hotel search with a nightly price cap, at most twice.
3. **Human-in-the-loop.** `interrupt()` pauses the graph for clarifying questions and for
   plan approval. A checkpointer saves the paused state between turns.
4. **Tool use against real-world APIs.** A failure becomes a warning, not a crash.
5. **LLM only where judgment is needed.** The LLM understands the request and writes the
   itinerary. Prices, dates and math are deterministic code.

Only 2 of the ~10 nodes call an LLM (intake and composer), so a trip costs 2–3 LLM calls.
The Phase-2 baseline (`agents/single_agent.py`, one ReAct agent with every tool) needed
about 9 and is kept for comparison.

## 3. Graph (`src/trippilot/graph.py`)

```
START → intake ──(missing info)──→ ask_user [interrupt] ──→ intake
          └──(complete)──→ supervisor ──Send (parallel)──→ flights │ hotels │ activities │ weather
                               ↑                                         ↓ (all four join)
                               └──(over budget, replan hotel)──── budget
                                                                   ↓ (ok)
                                                               composer (LLM)
                                                                   ↓
          intake ←──(changes requested)── approval [interrupt]
                                              └──(approved)──→ booking (mock) → END
```

`build_graph()` compiles the graph with an `InMemorySaver` checkpointer, which
`interrupt()` requires. Pydantic types from `schemas.py` are allowlisted for
serialization. The generated Mermaid diagram is in [graph.md](graph.md).

## 4. Shared state (`src/trippilot/state.py`, `TripState` TypedDict)

Each node returns only the keys it changes, and LangGraph merges them.

| Group | Keys |
|---|---|
| Conversation | `messages` (`add_messages` reducer) |
| Intake | `request: TripRequest`, `missing_info: list[str]` |
| Specialist results | `flight_options`, `hotel_options`, `activities`, `weather` |
| Errors | `errors` (custom `add_or_reset` reducer: parallel nodes append; returning `None` clears it) |
| Budget | `selected_flight`, `selected_hotel`, `planned_activities`, `budget_report`, `hotel_max_price`, `replan_count` |
| Output | `itinerary`, `approval` (`pending` / `approved` / `changes_requested`), `bookings` |

**Key convention: `None` means "work to do".** The supervisor dispatches every specialist
whose state key is `None`. An empty list `[]` means "ran, found nothing". A replan works
by setting one key back to `None`.

## 5. Nodes (`src/trippilot/agents/`)

| Node | LLM? | Behavior |
|---|---|---|
| `intake` | Yes | `with_structured_output(TripRequestDraft)` over the whole chat at temperature 0. Code (`draft.missing()`, not the LLM) checks for missing origin, destination, dates or budget. Later messages override earlier ones. |
| `ask_user` | No | `interrupt()` with the questions, then appends the Q&A to `messages`. It is a separate node so that resuming does not repeat the LLM call. |
| `supervisor` | No | A no-op hub. `route_to_specialists` returns `Send(node, state)` for each `None` result, or `END` if there are none. |
| `flights` / `hotels` / `activities` / `weather` | No | Each is a thin wrapper around one tool. A `ToolError` becomes `[]` (or `weather: None`) plus a message in `errors`. `hotels` respects `hotel_max_price` and skips day trips (0 nights). |
| `budget` | No | Converts currencies, takes the cheapest flight, estimates food ($35/day/person) and local transport ($10/day/person), and counts up to 2 non-food sights per day. It picks the best-rated affordable hotel. When over budget it first drops to free sights only. If still over, it sets `hotel_options=None` with a nightly cap and increments `replan_count` (max 2), so `route_after_budget` goes back to the supervisor. Otherwise it goes to the composer. |
| `composer` | Yes | Builds a compact text "facts" prompt and gets a `ComposedPlan` (summary, days, packing tips) back as structured output. Code then attaches the flight, hotel, budget and warnings, forces correct dates, nulls any `activity_id` that was never found, and sets costs from real data. **The LLM never sets prices or dates.** |
| `approval` | No | `interrupt()`. Approve words (approve / yes / ok / book it) lead to `booking`. Anything else is a change request: all planning results are reset (`RESET_ON_CHANGE`) and the graph returns to `intake`, which re-reads the chat (e.g. "make it $1200"). |
| `booking` | No | Mock booking with a UUID and a random hex confirmation code. It can only be reached through approval, and it re-checks `approval == "approved"` as a second safeguard. |

## 6. Tools layer (`src/trippilot/tools/`)

Plain functions with no AI. They return Pydantic models and raise typed errors
(`ToolError`, `NotFoundError`, `ExternalAPIError` in `errors.py`).

| Module | Purpose |
|---|---|
| `http.py` | Shared httpx client: connection pool, User-Agent, timeouts |
| `geo.py` | Place name → coordinates, country and nearest airports (Open-Meteo geocoding) |
| `airports.py` | OurAirports CSV, downloaded on first use and kept in memory (no disk); a lock makes parallel specialists share one download |
| `serpapi.py` | Thin SerpAPI client used by flights and hotels |
| `flights.py` | Google Flights via SerpAPI |
| `hotels.py` | Google Hotels via SerpAPI, optional `max_price` |
| `places.py` | OSM Overpass (with mirror fallback), interest → category mapping, diet filter, balanced ranking |
| `weather.py` | Forecast up to 16 days out; beyond that, last year's weather as an estimate |
| `currency.py` | Frankfurter (ECB), with ExchangeRate-API as fallback |
| `agent_tools.py` | `@tool` wrappers, used only by the single-agent baseline |

## 7. Other modules

- `schemas.py`: `Money`, `TripRequest`, `GeoLocation`, `FlightOption`, `HotelOption`,
  `Activity`, `WeatherSummary`, `BudgetReport`, `Itinerary`, `DayPlan`,
  `BookingConfirmation`, and others.
- `llm.py`: `get_llm()` wraps `init_chat_model`. The provider and model come from
  config; the default is `google_genai` / `gemini-3.5-flash`.
- `config.py`: pydantic-settings reading `.env` (`GOOGLE_API_KEY`, `SERPAPI_API_KEY`,
  `TRIPPILOT_LLM_PROVIDER`, `TRIPPILOT_LLM_MODEL`, optional LangSmith tracing).
- `ui/app.py`: Streamlit app that drives the same graph. It uses `graph.stream()` to
  show each agent's step live, resumes interrupts with `Command(resume=...)`, and shows
  the plan with an "Approve and book" button.

## 8. Design rules to keep when changing the code

1. Use the AI only for judgment (understanding requests, writing the plan). Money, dates
   and IDs are handled by code.
2. Use structured output wherever the LLM writes data, then have code validate and
   overwrite the facts.
3. Enforce safety rules with graph edges (booking only after approval), not prompts.
4. Keep replans targeted: clear one state key and the supervisor re-runs only that
   specialist.
5. An API failure becomes a message in `errors` and `itinerary.warnings`, never a crash.

**One subtle behavior:** if the weather call fails, it returns `weather: None` rather
than an empty value. Because `None` means "work to do", a later hotel replan will also
re-run the weather specialist.

## 9. Limitations

- Booking is a mock: no real reservations are made.
- Food, local transport and sight costs are estimates.
- Return-flight times are not fetched (needs a second SerpAPI request).
- The free Gemini tier is limited (about 20 requests a day).
- Tests (`tests/`) cover schemas, tools, intake and the single agent with mocks. Code is
  checked with ruff.
