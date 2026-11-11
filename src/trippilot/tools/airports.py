"""Airport lookup from the OurAirports open dataset (public domain, ~80k airports).

The CSV is downloaded when first needed and kept in memory for the life of the process
(nothing is written to disk, so a fresh container on a cloud host just downloads again).
"""

import csv
import functools
import io
import math
import threading
from dataclasses import dataclass

from trippilot.tools.errors import ExternalAPIError
from trippilot.tools.http import request

AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
AIRPORT_TYPES = {"large_airport", "medium_airport"}

# The parallel specialists (flights, weather, activities) all look up airports at once on
# a cold start; the lock makes one thread download while the others wait for its result.
_load_lock = threading.Lock()


@dataclass(frozen=True)
class Airport:
    iata: str
    name: str
    city: str
    country_code: str
    latitude: float
    longitude: float
    large: bool


def load_airports() -> dict[str, Airport]:
    """IATA code -> Airport, for large/medium airports with scheduled passenger service."""
    with _load_lock:
        return _fetch_airports()


@functools.cache  # a failed download is not cached, so the next call retries
def _fetch_airports() -> dict[str, Airport]:
    try:
        response = request("GET", AIRPORTS_URL, timeout=60)
    except Exception as e:
        raise ExternalAPIError("ourairports", f"download failed: {e}") from e

    airports: dict[str, Airport] = {}
    for row in csv.DictReader(io.StringIO(response.content.decode("utf-8"))):
        iata = row["iata_code"].strip()
        if not iata or row["type"] not in AIRPORT_TYPES or row["scheduled_service"] != "yes":
            continue
        airports[iata] = Airport(
            iata=iata,
            name=row["name"],
            city=row["municipality"],
            country_code=row["iso_country"],
            latitude=float(row["latitude_deg"]),
            longitude=float(row["longitude_deg"]),
            large=row["type"] == "large_airport",
        )
    return airports


def get_airport(code: str) -> Airport | None:
    return load_airports().get(code.strip().upper())


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle (haversine) distance."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def airports_near(
    latitude: float,
    longitude: float,
    country_code: str | None = None,
    large_radius_km: float = 80,
    medium_radius_km: float = 150,
    limit: int = 3,
) -> list[Airport]:
    """Airports serving a location: large ones within `large_radius_km`, else the nearest
    medium ones within `medium_radius_km`. Closest first. With `country_code`, airports in
    that country win over closer ones across a border (Lahore -> LHE, not Amritsar)."""
    by_distance = sorted(
        ((distance_km(latitude, longitude, a.latitude, a.longitude), a)
         for a in load_airports().values()),
        key=lambda pair: pair[0],
    )
    by_distance = [(d, a) for d, a in by_distance if d <= max(large_radius_km, medium_radius_km)]
    if country_code:
        domestic = [(d, a) for d, a in by_distance if a.country_code == country_code.upper()]
        by_distance = domestic or by_distance
    large = [a for d, a in by_distance if a.large and d <= large_radius_km]
    if large:
        return large[:limit]
    return [a for d, a in by_distance if d <= medium_radius_km][:limit]
