"""Attractions / POIs from OpenStreetMap (Overpass API), filtered by traveler interests."""

import logging
from dataclasses import dataclass
from itertools import zip_longest

from trippilot.schemas import Activity, Money
from trippilot.tools.errors import ToolError
from trippilot.tools.http import request_json

log = logging.getLogger(__name__)

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",  # public mirrors, tried in order
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]


@dataclass(frozen=True)
class Category:
    name: str
    selectors: tuple[str, ...]  # Overpass tag selectors, e.g. '["tourism"="museum"]'
    indoor: bool | None
    cost_usd: float  # typical cost per person
    duration_hours: float


CATEGORIES: dict[str, Category] = {
    c.name: c
    for c in [
        Category("museum", ('["tourism"="museum"]',), True, 15, 2.0),
        Category("gallery", ('["tourism"="gallery"]',), True, 8, 1.5),
        Category(
            "historic_site",
            ('["historic"~"castle|monument|ruins|fort|archaeological_site|palace"]',),
            False, 10, 1.5,
        ),
        Category(
            "place_of_worship",
            (
                '["amenity"="place_of_worship"]["tourism"="attraction"]',
                '["amenity"="place_of_worship"]["wikidata"]',
            ),
            True, 0, 1.0,
        ),
        Category("attraction", ('["tourism"="attraction"]',), None, 10, 1.5),
        Category("viewpoint", ('["tourism"="viewpoint"]',), False, 0, 0.75),
        Category("park", ('["leisure"="park"]["name"]',), False, 0, 1.5),
        Category("restaurant", ('["amenity"="restaurant"]',), True, 20, 1.5),
        Category("cafe", ('["amenity"="cafe"]',), True, 8, 1.0),
        Category("market", ('["amenity"="marketplace"]', '["shop"="mall"]'), None, 0, 2.0),
        Category("nightlife", ('["amenity"~"bar|pub|nightclub"]',), True, 15, 2.0),
        Category("beach", ('["natural"="beach"]["name"]',), False, 0, 3.0),
        Category("zoo_aquarium", ('["tourism"~"zoo|aquarium|theme_park"]',), None, 25, 3.0),
    ]
}

INTEREST_CATEGORIES: dict[str, list[str]] = {
    "history": ["historic_site", "museum", "place_of_worship"],
    "culture": ["museum", "gallery", "place_of_worship"],
    "art": ["gallery", "museum"],
    "museums": ["museum"],
    "architecture": ["place_of_worship", "historic_site", "attraction"],
    "religion": ["place_of_worship"],
    "food": ["restaurant", "cafe", "market"],
    "coffee": ["cafe"],
    "nature": ["park", "viewpoint", "beach"],
    "outdoors": ["park", "viewpoint", "beach"],
    "beach": ["beach"],
    "views": ["viewpoint"],
    "photography": ["viewpoint", "attraction"],
    "shopping": ["market"],
    "nightlife": ["nightlife"],
    "family": ["zoo_aquarium", "park"],
    "kids": ["zoo_aquarium", "park"],
    "sightseeing": ["attraction", "viewpoint", "historic_site"],
}
DEFAULT_CATEGORIES = ["attraction", "museum", "viewpoint"]
FOOD_CATEGORIES = {"restaurant", "cafe"}


def categories_for(interests: list[str] | tuple[str, ...]) -> list[str]:
    """Map free-text interests ("History", "street food") to POI categories."""
    found: list[str] = []
    for interest in interests:
        text = interest.lower()
        for keyword, cats in INTEREST_CATEGORIES.items():
            if keyword in text or text in keyword:
                found += [c for c in cats if c not in found]
    return found or list(DEFAULT_CATEGORIES)


def _diet_filter(constraints: list[str]) -> str:
    text = " ".join(constraints).lower()
    if "vegan" in text:
        return '["diet:vegan"~"yes|only"]'
    if "vegetarian" in text:
        return '["diet:vegetarian"~"yes|only"]'
    return ""


def build_query(
    lat: float, lon: float, categories: list[str], radius_m: int, constraints: list[str]
) -> str:
    diet = _diet_filter(constraints)
    around = f"(around:{radius_m},{lat},{lon})"
    lines = []
    for name in categories:
        extra = diet if name in FOOD_CATEGORIES else ""
        lines += [f"  nwr{sel}{extra}{around};" for sel in CATEGORIES[name].selectors]
    return "[out:json][timeout:25];\n(\n" + "\n".join(lines) + "\n);\nout center tags 400;"


def _classify(tags: dict, categories: list[str]) -> Category | None:
    for name in categories:
        for sel in CATEGORIES[name].selectors:
            if _matches(tags, sel):
                return CATEGORIES[name]
    return None


def _matches(tags: dict, selector: str) -> bool:
    """Evaluate a simple Overpass selector ('["k"="v"]', '["k"~"a|b"]', '["k"]') on tags."""
    for part in selector.strip("[]").split("]["):
        if "~" in part:
            key, pattern = (s.strip('"') for s in part.split("~", 1))
            if tags.get(key) not in pattern.split("|"):
                return False
        elif "=" in part:
            key, value = (s.strip('"') for s in part.split("=", 1))
            if tags.get(key) != value:
                return False
        elif part.strip('"') not in tags:
            return False
    return True


def _score(tags: dict) -> float:
    return (
        2.0 * ("wikidata" in tags or "wikipedia" in tags)
        + 0.5 * ("website" in tags)
        + 0.5 * ("opening_hours" in tags)
        + 0.25 * ("name:en" in tags)
    )


def _to_activity(el: dict, category: Category) -> Activity | None:
    tags = el.get("tags", {})
    name = tags.get("name:en") or tags.get("name")
    lat = el.get("lat", el.get("center", {}).get("lat"))
    lon = el.get("lon", el.get("center", {}).get("lon"))
    if not name or lat is None or lon is None:
        return None
    cost = 0.0 if tags.get("fee") == "no" else category.cost_usd
    return Activity(
        id=f"osm:{el['type']}/{el['id']}",
        name=name,
        category=category.name,
        latitude=lat,
        longitude=lon,
        description=tags.get("description"),
        estimated_cost=Money(amount=cost, currency="USD"),
        duration_hours=category.duration_hours,
        indoor=category.indoor,
        opening_hours=tags.get("opening_hours"),
        url=tags.get("website"),
        tags=[t for t in ("cuisine", "diet:vegetarian", "diet:vegan") if t in tags],
    )


def _balanced(by_category: dict[str, list[Activity]], limit: int) -> list[Activity]:
    """Round-robin across categories so one category can't crowd out the rest."""
    out: list[Activity] = []
    for row in zip_longest(*by_category.values()):
        out += [a for a in row if a is not None]
    return out[:limit]


def _overpass(query: str) -> dict:
    """Run a query on the main Overpass server, then the mirror if it is down."""
    error: ToolError | None = None
    for url in OVERPASS_URLS:
        try:
            return request_json("overpass", url, method="POST", data={"data": query}, timeout=35)
        except ToolError as e:
            log.warning("Overpass server %s failed: %s", url, e)
            error = e
    raise error


def search_places(
    latitude: float,
    longitude: float,
    interests: list[str],
    constraints: list[str] | None = None,
    radius_m: int = 3000,  # larger areas time out on the free servers in big cities
    limit: int = 25,
) -> list[Activity]:
    """Find attractions, food spots etc. near a point, matched to the traveler's interests.
    Dietary constraints ("vegetarian", "vegan") filter restaurants and cafes."""
    categories = categories_for(interests)
    query = build_query(latitude, longitude, categories, radius_m, constraints or [])
    data = _overpass(query)

    by_category: dict[str, list[tuple[float, Activity]]] = {c: [] for c in categories}
    seen: set[str] = set()
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        category = _classify(tags, categories)
        activity = _to_activity(el, category) if category else None
        if activity is None or activity.name in seen:
            continue
        seen.add(activity.name)
        by_category[category.name].append((_score(tags), activity))

    ranked = {
        c: [a for _, a in sorted(items, key=lambda x: x[0], reverse=True)]
        for c, items in by_category.items()
    }
    return _balanced(ranked, limit)
