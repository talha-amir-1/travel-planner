from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from trippilot.agents import single_agent
from trippilot.tools import agent_tools, geo

ISTANBUL = {"name": "Istanbul", "latitude": 41.01, "longitude": 28.95, "country_code": "TR"}


class ToolCallingFake(GenericFakeChatModel):
    """Replays scripted AI messages; tool binding is a no-op."""

    def bind_tools(self, tools, **kwargs):
        return self


def test_tool_wrappers_return_plain_data(isolated_tools):
    isolated_tools.get(geo.GEOCODING_URL).respond(json={"results": [ISTANBUL]})
    city = agent_tools.lookup_city.invoke({"place": "Istanbul"})
    assert city["name"] == "Istanbul" and sorted(city["airport_codes"]) == ["IST", "SAW"]
    assert "timezone" not in city  # None fields dropped to save tokens


def test_tool_errors_are_returned_as_text(isolated_tools):
    isolated_tools.get(geo.GEOCODING_URL).respond(json={})
    result = agent_tools.get_weather.invoke(
        {"place": "Atlantis", "start_date": "2026-12-10", "end_date": "2026-12-12"}
    )
    assert result.startswith("Error:")


def test_missing_serpapi_key_is_reported_not_raised():
    result = agent_tools.search_hotels.invoke(
        {"destination": "Istanbul", "check_in": "2026-12-10", "check_out": "2026-12-15"}
    )
    assert "SERPAPI_API_KEY" in result


def test_agent_calls_tools_and_returns_answer():
    model = ToolCallingFake(messages=iter([
        AIMessage(content="", tool_calls=[{
            "name": "convert_currency", "id": "1",
            "args": {"amount": 100, "from_currency": "USD", "to_currency": "USD"},
        }]),
        AIMessage(content="Your plan: 100 USD is plenty."),
    ]))
    result = single_agent.run("Plan a trip", model=model, verbose=False)
    assert result["answer"] == "Your plan: 100 USD is plenty."
    assert result["tool_calls"] == 1
