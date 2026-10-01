# TripPilot

Multi-agent travel planner & booking agent built with LangGraph. See [PLAN.md](PLAN.md).

## Quickstart

```bash
uv sync
cp .env.example .env   # fill in GOOGLE_API_KEY and LANGSMITH_API_KEY
uv run python -m trippilot.llm

# single-agent baseline (Phase 2); flights/hotels need SERPAPI_API_KEY
uv run python -m trippilot.agents.single_agent "5 days in Istanbul from Lahore in December, \$1500, food and history"
```
