"""Hotel search: Google Hotels via SerpAPI."""

from datetime import date

from trippilot.schemas import HotelOption, Money
from trippilot.tools.errors import NotFoundError, ToolError
from trippilot.tools.serpapi import serpapi_search


def search_hotels(
    destination: str,
    check_in: date,
    check_out: date,
    guests: int = 1,
    currency: str = "USD",
    max_results: int = 6,
) -> list[HotelOption]:
    """Search hotels in a destination for the given dates."""
    nights = (check_out - check_in).days
    if nights < 1:
        raise ToolError("check_out must be after check_in")
    data = serpapi_search(
        "google_hotels",
        {
            "q": f"hotels in {destination}",
            "check_in_date": check_in.isoformat(),
            "check_out_date": check_out.isoformat(),
            "adults": guests,
            "currency": currency,
        },
    )
    options = []
    for i, p in enumerate(data.get("properties") or []):
        nightly = (p.get("rate_per_night") or {}).get("extracted_lowest")
        if nightly is None:
            continue
        total = (p.get("total_rate") or {}).get("extracted_lowest") or nightly * nights
        gps = p.get("gps_coordinates") or {}
        options.append(
            HotelOption(
                id=f"serp:{p.get('property_token', i)}",
                name=p["name"],
                stars=p.get("extracted_hotel_class"),
                rating=p.get("overall_rating"),
                reviews=p.get("reviews"),
                price_per_night=Money(amount=nightly, currency=currency),
                total_price=Money(amount=total, currency=currency),
                latitude=gps.get("latitude"),
                longitude=gps.get("longitude"),
                amenities=p.get("amenities", [])[:10],
                link=p.get("link"),
            )
        )
    if not options:
        raise NotFoundError(f"No hotels found in {destination}")
    return options[:max_results]
