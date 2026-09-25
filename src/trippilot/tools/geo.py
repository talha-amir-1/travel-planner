"""Geocoding: place name -> coordinates, country and the airports serving it."""

from trippilot.schemas import GeoLocation
from trippilot.tools._common import NotFoundError, request_json, ttl_cache
from trippilot.tools.airports import airports_near, get_airport

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"


@ttl_cache(ttl=24 * 3600)
def geocode(place: str) -> GeoLocation:
    """Geocode a place like "Istanbul" or "Paris, France" to coordinates, country and
    nearby airport codes."""
    name, _, hint = (p.strip() for p in place.partition(","))
    data = request_json(
        "open-meteo-geocoding",
        GEOCODING_URL,
        params={"name": name, "count": 10, "language": "en", "format": "json"},
    )
    results = data.get("results") or []
    if hint:
        hint_l = hint.lower()
        matching = [
            r for r in results
            if hint_l in (r.get("country") or "").lower()
            or hint_l == (r.get("country_code") or "").lower()
            or hint_l in (r.get("admin1") or "").lower()
        ]
        results = matching or results
    if not results:
        raise NotFoundError(f"Could not geocode '{place}'")
    r = results[0]
    return GeoLocation(
        name=r["name"],
        country=r.get("country"),
        country_code=r.get("country_code"),
        latitude=r["latitude"],
        longitude=r["longitude"],
        timezone=r.get("timezone"),
        airport_codes=[
            a.iata for a in airports_near(r["latitude"], r["longitude"], r.get("country_code"))
        ],
    )


def resolve_airports(place: str) -> list[str]:
    """IATA codes for a city ("Istanbul" -> ["SAW", "IST"]) or an uppercase airport code
    ("SAW" -> ["SAW"]). Lowercase 3-letter words ("Goa") are treated as place names."""
    text = place.strip()
    if len(text) == 3 and text.isalpha() and text.isupper() and get_airport(text):
        return [text]
    codes = geocode(text).airport_codes
    if not codes:
        raise NotFoundError(f"No airport with scheduled flights near '{place}'")
    return codes
