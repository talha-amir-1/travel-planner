"""Weather via Open-Meteo: real forecast (<=16 days out) or last year's weather as an estimate."""

from datetime import date, timedelta

from trippilot.schemas import DailyWeather, WeatherSummary
from trippilot.tools._common import request_json, ttl_cache

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_DAYS = 16

# WMO weather interpretation codes.
WMO_CODES: dict[int, str] = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle",
    56: "Freezing drizzle", 57: "Dense freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Heavy freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light showers", 81: "Showers", 82: "Violent showers",
    85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Severe thunderstorm with hail",
}

_DAILY_VARS = ["temperature_2m_max", "temperature_2m_min", "precipitation_sum", "weather_code"]


def _one_year_earlier(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:  # Feb 29
        return d.replace(year=d.year - 1, day=28)


def _parse_daily(daily: dict, dates: list[date]) -> list[DailyWeather]:
    """Parse Open-Meteo's column-oriented `daily` block, relabelling rows with `dates`."""
    probs = daily.get("precipitation_probability_max") or [None] * len(dates)
    days = []
    for i, d in enumerate(dates):
        code = daily["weather_code"][i]
        days.append(
            DailyWeather(
                date=d,
                temp_max_c=daily["temperature_2m_max"][i],
                temp_min_c=daily["temperature_2m_min"][i],
                precipitation_mm=daily["precipitation_sum"][i],
                precipitation_probability=probs[i],
                weather_code=code,
                description=WMO_CODES.get(code, "Unknown") if code is not None else "Unknown",
            )
        )
    return days


@ttl_cache(ttl=3 * 3600)
def get_weather(
    latitude: float,
    longitude: float,
    start_date: date,
    end_date: date,
    location_name: str = "",
    today: date | None = None,
) -> WeatherSummary:
    """Daily weather for a trip. Uses the forecast when all dates are within 16 days,
    otherwise the same dates one year earlier as a climate estimate."""
    today = today or date.today()
    n_days = (end_date - start_date).days + 1
    trip_dates = [start_date + timedelta(days=i) for i in range(n_days)]
    params = {"latitude": latitude, "longitude": longitude, "timezone": "auto"}

    if today <= start_date and end_date < today + timedelta(days=FORECAST_DAYS):
        data = request_json(
            "open-meteo-forecast",
            FORECAST_URL,
            params={
                **params,
                "daily": ",".join([*_DAILY_VARS, "precipitation_probability_max"]),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )
        kind = "forecast"
    else:
        data = request_json(
            "open-meteo-archive",
            ARCHIVE_URL,
            params={
                **params,
                "daily": ",".join(_DAILY_VARS),
                "start_date": _one_year_earlier(start_date).isoformat(),
                "end_date": _one_year_earlier(end_date).isoformat(),
            },
        )
        kind = "historical_estimate"

    daily = data["daily"]
    days = _parse_daily(daily, trip_dates[: len(daily["time"])])
    return WeatherSummary(
        location=location_name or f"{latitude:.2f},{longitude:.2f}",
        start_date=start_date,
        end_date=end_date,
        kind=kind,
        days=days,
    )
