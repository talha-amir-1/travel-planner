"""Flight search: Google Flights via SerpAPI."""

from datetime import date, datetime

from trippilot.schemas import FlightOption, FlightSegment, Money
from trippilot.tools.errors import NotFoundError
from trippilot.tools.geo import resolve_airports
from trippilot.tools.serpapi import serpapi_search


def _parse_segment(seg: dict) -> FlightSegment:
    fmt = "%Y-%m-%d %H:%M"
    return FlightSegment(
        airline=seg.get("airline", "Unknown"),
        flight_number=seg.get("flight_number"),
        departure_airport=seg["departure_airport"]["id"],
        arrival_airport=seg["arrival_airport"]["id"],
        departure_time=datetime.strptime(seg["departure_airport"]["time"], fmt),
        arrival_time=datetime.strptime(seg["arrival_airport"]["time"], fmt),
        duration_minutes=seg.get("duration", 0),
    )


def search_flights(
    origin: str,
    destination: str,
    depart_date: date,
    return_date: date | None = None,
    travelers: int = 1,
    currency: str = "USD",
    max_results: int = 5,
) -> list[FlightOption]:
    """Search round-trip (or one-way) flights, cheapest first. origin/destination may be
    city names (all nearby airports are searched) or uppercase IATA codes."""
    origin_codes = ",".join(resolve_airports(origin))
    dest_codes = ",".join(resolve_airports(destination))
    params = {
        "departure_id": origin_codes,
        "arrival_id": dest_codes,
        "outbound_date": depart_date.isoformat(),
        "type": 1 if return_date else 2,  # 1 = round trip, 2 = one way
        "adults": travelers,
        "currency": currency,
    }
    if return_date:
        params["return_date"] = return_date.isoformat()
    searched = (
        f"{origin_codes} -> {dest_codes}, {depart_date}"
        + (f" to {return_date}" if return_date else " one way")
        + f", {travelers} adult(s), {currency}"
    )
    try:
        data = serpapi_search("google_flights", params)
    except NotFoundError as e:
        raise NotFoundError(f"No flights found for {searched} ({e})") from e

    raw =(data.get("best_flights") or []) + (data.get("other_flights") or [])
    options = []
    for i, item in enumerate(raw):
        if "price" not in item or not item.get("flights"):
            continue
        segments = [_parse_segment(s) for s in item["flights"]]
        options.append(
            FlightOption(
                id=f"serp:{segments[0].departure_airport}-{segments[-1].arrival_airport}:{i}",
                outbound=segments,
                price=Money(amount=item["price"], currency=currency),
                stops=len(segments) - 1,
                total_duration_minutes=item.get("total_duration")
                or sum(s.duration_minutes for s in segments),
            )
        )
    if not options:
        raise NotFoundError(f"No flights found for {searched}")
    return sorted(options, key=lambda o: o.price.amount)[:max_results]
