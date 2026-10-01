from datetime import date

import pytest
from langchain_core.runnables import RunnableLambda
from langgraph.types import Command

from trippilot.agents import intake
from trippilot.agents.intake import TripRequestDraft
from trippilot.graph import build_graph

COMPLETE = TripRequestDraft(
    origin="Lahore", destination="Istanbul",
    start_date=date(2026, 12, 10), end_date=date(2026, 12, 15),
    budget_amount=1500, interests=["food"], constraints=["vegetarian"],
)


class FakeExtractor:
    """Stands in for the chat model: with_structured_output() replays scripted drafts."""

    def __init__(self, *drafts):
        self.drafts = iter(drafts)
        self.calls = 0

    def with_structured_output(self, schema):
        def extract(messages):
            self.calls += 1
            return next(self.drafts)

        return RunnableLambda(extract)


@pytest.fixture(autouse=True)
def apis_down(isolated_tools):
    """These tests only check intake; specialists after it get a failing API and move on."""
    isolated_tools.route().respond(503)


@pytest.fixture
def fake_llm(monkeypatch):
    def install(*drafts):
        fake = FakeExtractor(*drafts)
        monkeypatch.setattr(intake, "get_llm", lambda **kwargs: fake)
        return fake

    return install


def test_draft_reports_missing_fields():
    assert TripRequestDraft(destination="Istanbul").missing() == ["origin", "dates", "budget"]
    assert COMPLETE.missing() == []


def test_draft_rejects_end_before_start():
    draft = COMPLETE.model_copy(update={"end_date": date(2026, 12, 1)})
    assert draft.missing() == ["dates"]


def test_draft_converts_to_trip_request():
    request = COMPLETE.to_request()
    assert (request.destination, request.nights, str(request.budget)) == ("Istanbul", 5, "1,500.00 USD")


def test_complete_request_needs_no_questions(fake_llm):
    fake_llm(COMPLETE)
    graph = build_graph()
    config = {"configurable": {"thread_id": "t1"}}
    result = graph.invoke({"messages": [("user", "Lahore to Istanbul...")]}, config)
    assert "__interrupt__" not in result
    assert result["request"].destination == "Istanbul"


def test_missing_info_interrupts_then_resumes(fake_llm):
    fake = fake_llm(TripRequestDraft(destination="Istanbul", origin="Lahore"), COMPLETE)
    graph = build_graph()
    config = {"configurable": {"thread_id": "t2"}}

    result = graph.invoke({"messages": [("user", "Lahore to Istanbul")]}, config)
    question = result["__interrupt__"][0].value["question"]
    assert "travel dates" in question and "budget" in question
    assert result.get("request") is None

    result = graph.invoke(Command(resume="Dec 10-15, $1500"), config)
    assert result["request"].budget.amount == 1500
    assert fake.calls == 2  # resuming re-ran ask_user, not the LLM extraction
    assert result["messages"][-1].content == "Dec 10-15, $1500"
