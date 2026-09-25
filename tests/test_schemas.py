from datetime import date

import pytest
from pydantic import ValidationError

from trippilot.schemas import BudgetLine, BudgetReport, Money, TripRequest


def test_money_normalizes_currency():
    assert Money(amount=10, currency="usd").currency == "USD"


def test_money_rejects_negative():
    with pytest.raises(ValidationError):
        Money(amount=-1)


def test_trip_request_nights_and_date_order():
    req = TripRequest(
        destination="Istanbul",
        start_date=date(2026, 12, 10),
        end_date=date(2026, 12, 15),
        budget=Money(amount=1500),
    )
    assert req.nights == 5
    with pytest.raises(ValidationError):
        TripRequest(
            destination="Istanbul",
            start_date=date(2026, 12, 15),
            end_date=date(2026, 12, 10),
            budget=Money(amount=1500),
        )


def test_budget_report_totals():
    report = BudgetReport(
        budget=Money(amount=1000),
        lines=[
            BudgetLine(category="flights", amount=Money(amount=600)),
            BudgetLine(category="hotel", amount=Money(amount=450.5)),
        ],
    )
    assert report.total.amount == 1050.5
    assert report.remaining == -50.5
    assert report.within_budget is False


def test_budget_report_rejects_mixed_currencies():
    with pytest.raises(ValidationError):
        BudgetReport(
            budget=Money(amount=1000, currency="USD"),
            lines=[BudgetLine(category="hotel", amount=Money(amount=100, currency="EUR"))],
        )
