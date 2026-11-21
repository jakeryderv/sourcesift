"""Current conditions and forecast from the Open-Meteo API (CC BY 4.0, no key)."""

from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field

from sourcesift.builtin.common import json_object, number, one_line
from sourcesift.contract import Contract
from sourcesift.data import (
    Cell,
    Column,
    GeoPoint,
    GeoPoints,
    Point,
    Series,
    Stat,
    Stats,
    Table,
    TimeSeries,
)
from sourcesift.extend import FetchContext, Record, SourceResult, source
from sourcesift.retrieval.urls import RetrievalError

# WMO weather interpretation codes, as documented by Open-Meteo.
_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Freezing fog", 51: "Light drizzle", 53: "Drizzle",
    55: "Heavy drizzle", 56: "Light freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Light freezing rain",
    67: "Freezing rain", 71: "Light snow", 73: "Snow", 75: "Heavy snow",
    77: "Snow grains", 80: "Light showers", 81: "Showers", 82: "Violent showers",
    85: "Light snow showers", 86: "Snow showers", 95: "Thunderstorm",
    96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}  # fmt: skip


class WeatherParams(Contract):
    """Where and how much weather to look up."""

    place: str = Field(
        min_length=1,
        max_length=80,
        description="A city or town, optionally followed by a region or country "
        "to tell places apart: 'Chicago', 'Portland, Maine', 'Paris, France'.",
    )
    days: int = Field(
        default=3, ge=1, le=7, description="Days of forecast, counting today."
    )
    units: Literal["metric", "imperial"] = Field(
        default="metric",
        description="'imperial' (°F, mph) for places in the United States unless "
        "the user asks otherwise; 'metric' (°C, km/h) elsewhere.",
    )


def _list(data: dict[str, object], key: str) -> list[object]:
    value = data.get(key)
    return value if isinstance(value, list) else []


def _block(data: dict[str, object], key: str) -> dict[str, object]:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _condition(code: object) -> str:
    value = number(code)
    return _CODES.get(int(value), "Unknown") if value is not None else "Unknown"


def _when(value: object) -> datetime | None:
    seconds = number(value)
    try:
        return datetime.fromtimestamp(seconds, UTC) if seconds is not None else None
    except (OverflowError, OSError, ValueError):
        return None


@source(
    id="weather",
    name="Weather (Open-Meteo)",
    website="https://open-meteo.com/",
    aliases=("Open-Meteo", "Weather", "Forecast"),
    description="Current conditions and a forecast of up to 7 days for a named "
    "city or town anywhere in the world: temperature, feels-like, humidity, wind, "
    "and chance of precipitation. Model forecast data, not official warnings or "
    "alerts. Weather data by Open-Meteo.com.",
    topics=("weather", "forecast"),
    geography="Worldwide",
    params=WeatherParams,
    returns=(Stats, TimeSeries, Table, GeoPoints),
    refresh_seconds=900,
    api_hosts=("api.open-meteo.com", "geocoding-api.open-meteo.com"),
)
async def weather(params: WeatherParams, context: FetchContext) -> SourceResult:
    """Resolve a place name, then read its current conditions and forecast."""
    name, _, qualifier = (part.strip() for part in params.place.partition(","))
    found = await context.get(
        "https://geocoding-api.open-meteo.com/v1/search?"
        + urlencode({"name": name, "count": 10, "language": "en", "format": "json"})
    )
    places = [p for p in _list(json_object(found), "results") if isinstance(p, dict)]
    if qualifier:
        wanted = qualifier.casefold()
        places = [
            p
            for p in places
            if any(
                wanted == one_line(p.get(key)).casefold()
                for key in ("admin1", "country", "country_code")
            )
        ] or places
    place = next(
        (
            p
            for p in places
            if number(p.get("latitude")) is not None
            and number(p.get("longitude")) is not None
        ),
        None,
    )
    if place is None:
        raise RetrievalError("No place with that name was found.")
    latitude = max(-85.0, min(85.0, number(place.get("latitude")) or 0.0))
    longitude = max(-180.0, min(180.0, number(place.get("longitude")) or 0.0))
    label = ", ".join(
        dict.fromkeys(
            part
            for key in ("name", "admin1", "country")
            if (part := one_line(place.get(key), 60))
        )
    )[:80]
    imperial = params.units == "imperial"
    page = await context.get(
        "https://api.open-meteo.com/v1/forecast?"
        + urlencode(
            {
                "latitude": round(latitude, 4),
                "longitude": round(longitude, 4),
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                "wind_speed_10m,precipitation,weather_code",
                "hourly": "temperature_2m,apparent_temperature",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max",
                "timezone": "auto",
                "timeformat": "unixtime",
                "forecast_days": params.days,
                "temperature_unit": "fahrenheit" if imperial else "celsius",
                "wind_speed_unit": "mph" if imperial else "kmh",
                "precipitation_unit": "inch" if imperial else "mm",
            }
        )
    )
    data = json_object(page)
    current, hourly, daily = (_block(data, k) for k in ("current", "hourly", "daily"))
    degrees = "°F" if imperial else "°C"
    speed = "mph" if imperial else "km/h"
    try:
        zone = ZoneInfo(one_line(data.get("timezone"), 64) or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
    temperature = number(current.get("temperature_2m"))
    observed = _when(current.get("time"))
    if temperature is None or observed is None:
        raise RetrievalError("The weather service returned no current conditions.")

    days: list[tuple[Cell, ...]] = []
    for index, raw in enumerate(_list(daily, "time")):
        day = _when(raw)
        if day is None:
            continue

        def at(key: str, index: int = index) -> object:
            values = _list(daily, key)
            return values[index] if index < len(values) else None

        days.append(
            (
                day.astimezone(zone).strftime("%a %b %d"),
                _condition(at("weather_code")),
                number(at("temperature_2m_max")),
                number(at("temperature_2m_min")),
                number(at("precipitation_probability_max")),
            )
        )

    def hours(key: str) -> tuple[Point, ...]:
        return tuple(
            Point(at=moment, value=value)
            for raw, item in zip(
                _list(hourly, "time"), _list(hourly, key), strict=False
            )
            if (moment := _when(raw)) is not None
            and (value := number(item)) is not None
        )

    figures = [
        Stat(label="Temperature", value=temperature, unit=degrees),
        *(
            Stat(label=text, value=value, unit=unit)
            for text, key, unit in (
                ("Feels like", "apparent_temperature", degrees),
                ("Humidity", "relative_humidity_2m", "%"),
                ("Wind", "wind_speed_10m", speed),
            )
            if (value := number(current.get(key))) is not None
        ),
    ]
    if days and days[0][2] is not None and days[0][3] is not None:
        figures += [
            Stat(label="High today", value=days[0][2], unit=degrees),
            Stat(label="Low today", value=days[0][3], unit=degrees),
        ]
    condition = _condition(current.get("weather_code"))
    local = observed.astimezone(zone)
    now = "; ".join(
        f"{item.label}: {item.value:g} {item.unit}".replace(" °", "°").replace(
            " %", "%"
        )
        for item in figures
    )
    header = (
        f"Weather for {label} ({latitude:.2f}, {longitude:.2f}), from Open-Meteo "
        f"forecast models. Observed {local:%Y-%m-%d %H:%M} local time ({zone.key})."
    )
    lines = [
        header,
        f"Now: {condition}. {now}.",
        "Daily forecast (high / low, chance of precipitation):",
    ]
    for day, text, high, low, chance in days:
        shown = [value if value is not None else "?" for value in (high, low, chance)]
        lines.append(
            f"{day}: {text}, {shown[0]}{degrees} / {shown[1]}{degrees}, {shown[2]}%"
        )
    lines.append("Model forecast data, not an official warning or alert.")
    shapes: list[Contract] = [
        Stats(name=f"Weather in {label}: {condition}"[:120], items=tuple(figures)),
        GeoPoints(
            name=f"Weather in {label}"[:120],
            points=(
                GeoPoint(
                    label=label,
                    latitude=latitude,
                    longitude=longitude,
                    value=temperature,
                    unit=degrees,
                ),
            ),
        ),
    ]
    series = tuple(
        Series(name=text, points=points)
        for text, key in (
            ("Temperature", "temperature_2m"),
            ("Feels like", "apparent_temperature"),
        )
        if (points := hours(key))
    )
    if series:
        shapes.append(
            TimeSeries(
                name=f"Hourly temperature in {label}"[:120],
                unit=degrees,
                timezone=zone.key,
                series=series,
            )
        )
    if days:
        shapes.append(
            Table(
                name=f"Forecast for {label}"[:120],
                columns=(
                    Column(name="Day"),
                    Column(name="Conditions"),
                    Column(name="High", unit=degrees),
                    Column(name="Low", unit=degrees),
                    Column(name="Chance of precipitation", unit="%"),
                ),
                rows=tuple(days),
            )
        )
    title = f"Weather for {label} ({local:%Y-%m-%d %H:%M} local)"
    return SourceResult([Record(title, page.url, "\n".join(lines), page)], shapes)
