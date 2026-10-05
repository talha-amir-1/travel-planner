"""Typed domain models shared by tools, agents, API and UI."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator


class Money(BaseModel):
    amount: float = Field(ge=0)
    currency: str = Field("USD", pattern=r"^[A-Z]{3}$", description="ISO 4217 code, e.g. USD")

    @field_validator("currency", mode="before")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper() if isinstance(v, str) else v

    def __str__(self) -> str:
        return f"{self.amount:,.2f} {self.currency}"


class TripRequest(BaseModel):
    origin: str | None = Field(None, description="Departure city or IATA code")
    destination: str
    start_date: date
    end_date: date
    travelers: int = Field(1, ge=1)
    budget: Money
    interests: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(
        default_factory=list, description='e.g. "vegetarian", "no red-eye flights"'
    )

    @model_validator(mode="after")
    def _check_dates(self) -> "TripRequest":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self

    @property
    def nights(self) -> int:
        return (self.end_date - self.start_date).days


class GeoLocation(BaseModel):
    name: str
    country: str | None = None
    country_code: str | None = None
    latitude: float
    longitude: float
    timezone: str | None = None
    airport_codes: list[str] = Field(default_factory=list, description="IATA codes, nearest first")


class FlightSegment(BaseModel):
    airline: str
    flight_number: str | None = None
    departure_airport: str
    arrival_airport: str
    departure_time: datetime
    arrival_time: datetime
    duration_minutes: int


class FlightOption(BaseModel):
    id: str
    outbound: list[FlightSegment]
    inbound: list[FlightSegment] = Field(
        default_factory=list, description="Empty when the provider only prices the round trip"
    )
    price: Money = Field(description="Total price for all travelers")
    stops: int
    total_duration_minutes: int


class HotelOption(BaseModel):
    id: str
    name: str
    stars: float | None = None
    rating: float | None = Field(None, description="Guest rating out of 5")
    reviews: int | None = None
    price_per_night: Money
    total_price: Money
    neighborhood: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    amenities: list[str] = Field(default_factory=list)
    link: str | None = None


class Activity(BaseModel):
    id: str
    name: str
    category: str
    latitude: float
    longitude: float
    description: str | None = None
    estimated_cost: Money | None = Field(None, description="Typical cost per person")
    duration_hours: float | None = None
    indoor: bool | None = None
    opening_hours: str | None = None
    url: str | None = None
    tags: list[str] = Field(default_factory=list)


class DailyWeather(BaseModel):
    date: date
    temp_min_c: float | None = None
    temp_max_c: float | None = None
    precipitation_mm: float | None = None
    precipitation_probability: int | None = None
    weather_code: int | None = None
    description: str = "Unknown"

    @computed_field
    @property
    def is_rainy(self) -> bool:
        if self.precipitation_probability is not None and self.precipitation_probability >= 60:
            return True
        return (self.precipitation_mm or 0) >= 2.0


class WeatherSummary(BaseModel):
    location: str
    start_date: date
    end_date: date
    kind: Literal["forecast", "historical_estimate"] = Field(
        description="historical_estimate = same dates last year, used beyond the forecast window"
    )
    days: list[DailyWeather]

    @computed_field
    @property
    def avg_high_c(self) -> float | None:
        vals = [d.temp_max_c for d in self.days if d.temp_max_c is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    @computed_field
    @property
    def avg_low_c(self) -> float | None:
        vals = [d.temp_min_c for d in self.days if d.temp_min_c is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    @computed_field
    @property
    def rainy_days(self) -> int:
        return sum(d.is_rainy for d in self.days)


BudgetCategory = Literal["flights", "hotel", "activities", "food", "local_transport", "other"]


class BudgetLine(BaseModel):
    category: BudgetCategory
    amount: Money
    note: str | None = None


class BudgetReport(BaseModel):
    budget: Money
    lines: list[BudgetLine] = Field(description="All amounts already in the budget currency")

    @model_validator(mode="after")
    def _same_currency(self) -> "BudgetReport":
        bad = [ln.category for ln in self.lines if ln.amount.currency != self.budget.currency]
        if bad:
            raise ValueError(f"lines must be in {self.budget.currency}: {bad}")
        return self

    @computed_field
    @property
    def total(self) -> Money:
        amount = round(sum(ln.amount.amount for ln in self.lines), 2)
        return Money(amount=amount, currency=self.budget.currency)

    @computed_field
    @property
    def remaining(self) -> float:
        return round(self.budget.amount - self.total.amount, 2)

    @computed_field
    @property
    def within_budget(self) -> bool:
        return self.remaining >= 0


class ItineraryItem(BaseModel):
    time_slot: Literal["morning", "afternoon", "evening"]
    title: str
    activity_id: str | None = None
    notes: str | None = None
    cost: Money | None = None


class DayPlan(BaseModel):
    date: date
    title: str
    neighborhood: str | None = None
    weather_note: str | None = None
    items: list[ItineraryItem]


class Itinerary(BaseModel):
    destination: str
    start_date: date
    end_date: date
    summary: str
    flight: FlightOption | None = None
    hotel: HotelOption | None = None
    days: list[DayPlan]
    budget_report: BudgetReport | None = None
    packing_tips: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(
        default_factory=list, description="Problems the traveler should know, e.g. no flights found"
    )


class BookingConfirmation(BaseModel):
    booking_id: str
    kind: Literal["flight", "hotel", "activity"]
    item_id: str
    status: Literal["held", "confirmed", "cancelled", "failed"]
    confirmation_code: str | None = None
    amount: Money
    created_at: datetime
