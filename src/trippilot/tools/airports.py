"""Airport lookup from the OurAirports open dataset (public domain, ~80k airports).

The CSV is downloaded once, cached under .cache/ and refreshed monthly.
"""

import csv
import functools
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path

from trippilot.config import PROJECT_ROOT
from trippilot.tools._common import ExternalAPIError, _request

log = logging.getLogger(__name__)

AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
CACHE_PATH = PROJECT_ROOT / ".cache" / "airports.csv"
MAX_AGE_SECONDS = 30 * 24 * 3600
AIRPORT_TYPES = {"large_airport", "medium_airport"}


@dataclass(frozen=True)
class Airport:
    iata: str
    name: str
    city: str
    country_code: str
    latitude: float
    longitude: float
    large: bool


def _download(path: Path) -> None:
    try:
        response = _request("GET", AIRPORTS_URL, timeout=60)
    except Exception as e:
        raise ExternalAPIError("ourairports", f"download failed: {e}") from e
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(response.content)
    tmp.replace(path)


def _csv_path() -> Path:
    path = CACHE_PATH
    if path.exists() and time.time() - path.stat().st_mtime < MAX_AGE_SECONDS:
        return path
    try:
        _download(path)
    except ExternalAPIError:
        if not path.exists():
            raise
        log.warning("Could not refresh airport data; using cached copy from %s", path)
    return path


@functools.cache
def load_airports() -> dict[str, Airport]:
    """IATA code -> Airport, for large/medium airports with scheduled passenger service."""
    airports: dict[str, Airport] = {}
    with _csv_path().open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
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
