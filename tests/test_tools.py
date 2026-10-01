from datetime import date
from pathlib import Path

import httpx
import pytest

from trippilot.schemas import Money
from trippilot.tools import airports, currency, flights, geo, hotels, places, weather
from trippilot.tools.errors import ExternalAPIError, NotFoundError, ToolError
from trippilot.tools.http import request_json

ISTANBUL = {
    "name": "Istanbul", "latitude": 41.01, "longitude": 28.95,
    "country": "Türkiye", "country_code": "TR", "timezone": "Europe/Istanbul",
}
SERPAPI_URL = "https://serpapi.com/search.json"


# --- shared plumbing ---------------------------------------------------------


def test_request_json_raises_on_http_error(isolated_tools):
    route = isolated_tools.get("https://api.test/x").respond(503)
    with pytest.raises(ExternalAPIError) as exc:
        request_json("test", "https://api.test/x")
    assert exc.value.status_code == 503
    assert route.call_count == 1


def test_request_json_wraps_transport_errors(isolated_tools):
    isolated_tools.get("https://api.test/x").mock(side_effect=httpx.ConnectTimeout("t/o"))
    with pytest.raises(ExternalAPIError, match="ConnectTimeout"):
        request_json("test", "https://api.test/x")


# --- airports & geo ----------------------------------------------------------


def test_load_airports_keeps_only_scheduled_large_and_medium():
    codes = set(airports.load_airports())
    assert codes == {"IST", "SAW", "LHE", "ATQ", "ISB", "GOA", "MQT"}  # heliport & closed dropped


def test_airports_near_prefers_large_airports():
    assert sorted(a.iata for a in airports.airports_near(41.01, 28.95)) == ["IST", "SAW"]
    assert [a.iata for a in airports.airports_near(46.5, -87.4)] == ["MQT"]  # medium fallback
    assert airports.airports_near(0.0, 0.0) == []


def test_airports_near_prefers_same_country():
    # Amritsar (ATQ, India) is ~45 km from Lahore, across the border.
    assert [a.iata for a in airports.airports_near(31.55, 74.34)] == ["LHE", "ATQ"]
    assert [a.iata for a in airports.airports_near(31.55, 74.34, country_code="PK")] == ["LHE"]


def test_airports_downloaded_when_missing(isolated_tools, tmp_path, monkeypatch):
    target = tmp_path / "fresh" / "airports.csv"
    monkeypatch.setattr(airports, "CACHE_PATH", target)
    airports.load_airports.cache_clear()
    route = isolated_tools.get(airports.AIRPORTS_URL).respond(
        content=(Path(__file__).parent / "data" / "airports.csv").read_bytes()
    )
    assert "LHE" in airports.load_airports()
    assert route.call_count == 1 and target.exists()


def test_geocode_parses_results(isolated_tools):
    route = isolated_tools.get(geo.GEOCODING_URL).respond(json={"results": [ISTANBUL]})
    loc = geo.geocode("Istanbul")
    assert (loc.name, loc.country_code) == ("Istanbul", "TR")
    assert sorted(loc.airport_codes) == ["IST", "SAW"]
    assert route.call_count == 1
    assert route.calls[0].request.url.params["name"] == "Istanbul"


def test_geocode_uses_country_hint(isolated_tools):
    paris_tx = {"name": "Paris", "latitude": 33.66, "longitude": -95.55, "country": "United States", "country_code": "US"}
    paris_fr = {"name": "Paris", "latitude": 48.85, "longitude": 2.35, "country": "France", "country_code": "FR"}
    isolated_tools.get(geo.GEOCODING_URL).respond(json={"results": [paris_tx, paris_fr]})
    assert geo.geocode("Paris, France").country_code == "FR"


def test_geocode_not_found(isolated_tools):
    isolated_tools.get(geo.GEOCODING_URL).respond(json={"generationtime_ms": 0.1})
    with pytest.raises(NotFoundError):
        geo.geocode("Atlantis")


def test_resolve_airports_accepts_uppercase_codes_without_network():
    assert geo.resolve_airports("SAW") == ["SAW"]


def test_resolve_airports_geocodes_city_names(isolated_tools):
    lahore = {"name": "Lahore", "latitude": 31.55, "longitude": 74.34, "country_code": "PK"}
    goa = {"name": "Goa", "latitude": 15.3, "longitude": 74.0, "country_code": "IN"}

    def respond(request):
        city = lahore if request.url.params["name"] == "Lahore" else goa
        return httpx.Response(200, json={"results": [city]})

    isolated_tools.get(geo.GEOCODING_URL).mock(side_effect=respond)
    assert geo.resolve_airports("Lahore") == ["LHE"]
    with pytest.raises(NotFoundError):  # "Goa" is a place, not Genoa's GOA code
        geo.resolve_airports("Goa")


# --- weather -----------------------------------------------------------------


def _daily(dates, with_prob=True):
    n = len(dates)
    block = {
        "time": dates,
        "temperature_2m_max": [20.0] * n,
        "temperature_2m_min": [10.0] * n,
        "precipitation_sum": [0.0, 8.5][:n] + [0.0] * (n - 2),
        "weather_code": [0, 63][:n] + [1] * (n - 2),
    }
    if with_prob:
        block["precipitation_probability_max"] = [5] * n
    return {"daily": block}


def test_weather_uses_forecast_within_16_days(isolated_tools):
    route = isolated_tools.get(weather.FORECAST_URL).respond(
        json=_daily(["2026-10-01", "2026-10-02", "2026-10-03"])
    )
    w = weather.get_weather(41.0, 29.0, date(2026, 10, 1), date(2026, 10, 3), "Istanbul", today=date(2026, 9, 25))
    assert w.kind == "forecast"
    assert len(w.days) == 3
    assert w.days[1].description == "Rain" and w.days[1].is_rainy
    assert w.rainy_days == 1
    assert w.avg_high_c == 20.0
    assert route.calls[0].request.url.params["start_date"] == "2026-10-01"


def test_weather_far_future_uses_last_year(isolated_tools):
    route = isolated_tools.get(weather.ARCHIVE_URL).respond(
        json=_daily(["2025-12-10", "2025-12-11"], with_prob=False)
    )
    w = weather.get_weather(41.0, 29.0, date(2026, 12, 10), date(2026, 12, 11), today=date(2026, 9, 25))
    assert w.kind == "historical_estimate"
    assert [d.date for d in w.days] == [date(2026, 12, 10), date(2026, 12, 11)]
    params = route.calls[0].request.url.params
    assert (params["start_date"], params["end_date"]) == ("2025-12-10", "2025-12-11")


# --- currency ----------------------------------------------------------------


def test_convert_same_currency_needs_no_call():
    assert currency.convert(Money(amount=50, currency="EUR"), "EUR").amount == 50


def test_convert_uses_frankfurter(isolated_tools):
    route = isolated_tools.get(currency.FRANKFURTER_URL).respond(
        json={"amount": 1.0, "base": "USD", "rates": {"EUR": 0.9}}
    )
    assert currency.convert(Money(amount=100), "EUR") == Money(amount=90.0, currency="EUR")
    assert route.calls[0].request.url.params["symbols"] == "EUR"


def test_convert_non_ecb_currency_uses_open_er_api(isolated_tools):
    route = isolated_tools.get(currency.OPEN_ER_URL.format(base="USD")).respond(
        json={"result": "success", "base_code": "USD", "rates": {"PKR": 282.0}}
    )
    assert currency.convert(Money(amount=2), "PKR") == Money(amount=564.0, currency="PKR")
    assert route.call_count == 1


def test_convert_falls_back_to_open_er_api_when_frankfurter_down(isolated_tools):
    isolated_tools.get(currency.FRANKFURTER_URL).respond(500)
    isolated_tools.get(currency.OPEN_ER_URL.format(base="USD")).respond(
        json={"result": "success", "rates": {"EUR": 0.88}}
    )
    assert currency.convert(Money(amount=100), "EUR").amount == 88.0


def test_convert_unknown_currency_raises(isolated_tools):
    isolated_tools.get(currency.OPEN_ER_URL.format(base="USD")).respond(
        json={"result": "success", "rates": {"EUR": 0.88}}
    )
    with pytest.raises(ToolError):
        currency.convert(Money(amount=1), "XXX")


# --- places ------------------------------------------------------------------

OVERPASS_ELEMENTS = {
    "elements": [
        {"type": "node", "id": 1, "lat": 41.0, "lon": 28.9,
         "tags": {"tourism": "museum", "name": "Local Museum"}},
        {"type": "way", "id": 2, "center": {"lat": 41.01, "lon": 28.97},
         "tags": {"tourism": "museum", "name": "Topkapi Sarayi", "name:en": "Topkapi Palace",
                  "wikidata": "Q170495", "opening_hours": "Mo,We-Su 09:00-18:00"}},
        {"type": "node", "id": 3, "lat": 41.02, "lon": 28.98,
         "tags": {"amenity": "restaurant", "name": "Green Plate", "diet:vegetarian": "only"}},
        {"type": "node", "id": 4, "lat": 41.02, "lon": 28.98, "tags": {"tourism": "museum"}},
    ]
}


def test_categories_for_interests():
    assert places.categories_for(["History"])[:2] == ["historic_site", "museum"]
    assert places.categories_for(["street food"]) == ["restaurant", "cafe", "market"]
    assert places.categories_for([]) == places.DEFAULT_CATEGORIES


def test_search_places_parses_ranks_and_filters_diet(isolated_tools):
    route = isolated_tools.post(places.OVERPASS_URLS[0]).respond(json=OVERPASS_ELEMENTS)
    result = places.search_places(41.0, 28.95, ["museums", "food"], ["vegetarian"])

    query = route.calls[0].request.content.decode()
    assert "diet%3Avegetarian" in query  # form-encoded restaurant filter
    names = [a.name for a in result]
    assert names[0] == "Topkapi Palace"  # wikidata-tagged ranks first, English name preferred
    assert "Green Plate" in names
    assert len(names) == 3  # unnamed element dropped
    palace = result[0]
    assert palace.id == "osm:way/2" and palace.indoor and palace.latitude == 41.01


def test_search_places_uses_mirror_when_main_server_down(isolated_tools):
    isolated_tools.post(places.OVERPASS_URLS[0]).respond(504)
    mirror = isolated_tools.post(places.OVERPASS_URLS[1]).respond(json=OVERPASS_ELEMENTS)
    assert places.search_places(41.0, 28.95, ["museums"])
    assert mirror.call_count == 1


def test_search_places_raises_when_all_servers_down(isolated_tools):
    for url in places.OVERPASS_URLS:
        isolated_tools.post(url).respond(504)
    with pytest.raises(ExternalAPIError):
        places.search_places(41.0, 28.95, ["museums"])


# --- flights -----------------------------------------------------------------

SERP_FLIGHTS = {
    "best_flights": [{
        "flights": [
            {"departure_airport": {"id": "LHE", "time": "2026-12-10 04:00"},
             "arrival_airport": {"id": "IST", "time": "2026-12-10 09:30"},
             "duration": 450, "airline": "Turkish Airlines", "flight_number": "TK 715"},
        ],
        "total_duration": 450, "price": 820,
    }],
    "other_flights": [{
        "flights": [
            {"departure_airport": {"id": "LHE", "time": "2026-12-10 03:00"},
             "arrival_airport": {"id": "DXB", "time": "2026-12-10 05:30"},
             "duration": 210, "airline": "Emirates"},
            {"departure_airport": {"id": "DXB", "time": "2026-12-10 08:00"},
             "arrival_airport": {"id": "SAW", "time": "2026-12-10 12:00"},
             "duration": 300, "airline": "Emirates"},
        ],
        "total_duration": 660, "price": 610,
    }],
}


def test_flights_require_serpapi_key():
    with pytest.raises(ExternalAPIError, match="SERPAPI_API_KEY"):
        flights.search_flights("LHE", "IST", date(2026, 12, 10), date(2026, 12, 15))


def test_flights_serpapi_parsing(isolated_tools, serpapi_key):
    isolated_tools.get(geo.GEOCODING_URL).respond(json={"results": [ISTANBUL]})
    route = isolated_tools.get(SERPAPI_URL).respond(json=SERP_FLIGHTS)
    result = flights.search_flights("LHE", "Istanbul", date(2026, 12, 10), date(2026, 12, 15))

    params = route.calls[0].request.url.params
    assert params["engine"] == "google_flights" and params["departure_id"] == "LHE"
    assert sorted(params["arrival_id"].split(",")) == ["IST", "SAW"]  # all city airports
    assert params["type"] == "1" and params["return_date"] == "2026-12-15"
    assert [o.price.amount for o in result] == [610, 820]
    assert result[0].stops == 1 and result[0].outbound[-1].arrival_airport == "SAW"


def test_flights_serpapi_error_is_raised(isolated_tools, serpapi_key):
    isolated_tools.get(SERPAPI_URL).respond(json={"error": "Invalid API key"})
    with pytest.raises(ExternalAPIError, match="Invalid API key"):
        flights.search_flights("LHE", "IST", date(2026, 12, 10))


def test_flights_no_results_raises(isolated_tools, serpapi_key):
    isolated_tools.get(SERPAPI_URL).respond(json={"best_flights": []})
    with pytest.raises(NotFoundError):
        flights.search_flights("LHE", "IST", date(2026, 12, 10))


# --- hotels ------------------------------------------------------------------


def test_hotels_require_serpapi_key():
    with pytest.raises(ExternalAPIError, match="SERPAPI_API_KEY"):
        hotels.search_hotels("Istanbul", date(2026, 12, 10), date(2026, 12, 15))


def test_hotels_reject_bad_dates():
    with pytest.raises(ToolError):
        hotels.search_hotels("Istanbul", date(2026, 12, 10), date(2026, 12, 10))


def test_hotels_serpapi_parsing(isolated_tools, serpapi_key):
    route = isolated_tools.get(SERPAPI_URL).respond(json={"properties": [
        {"name": "Pera Palace", "property_token": "abc", "extracted_hotel_class": 5,
         "overall_rating": 4.6, "reviews": 3100,
         "rate_per_night": {"extracted_lowest": 210},
         "total_rate": {"extracted_lowest": 1050},
         "gps_coordinates": {"latitude": 41.03, "longitude": 28.97},
         "amenities": ["Free Wi-Fi", "Spa"]},
        {"name": "No price hotel"},
    ]})
    result = hotels.search_hotels("Istanbul", date(2026, 12, 10), date(2026, 12, 15), guests=2)
    params = route.calls[0].request.url.params
    assert (params["engine"], params["q"], params["adults"]) == ("google_hotels", "hotels in Istanbul", "2")
    assert len(result) == 1
    h = result[0]
    assert (h.id, h.stars, h.total_price.amount, h.latitude) == ("serp:abc", 5, 1050, 41.03)
