from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from time import sleep
from typing import Any

import requests


class TravelSourceError(RuntimeError):
    """A public travel source could not provide a usable response."""


WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    80: "Rain showers",
    81: "Rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with hail",
}


@dataclass(frozen=True)
class DestinationContext:
    source_id: str
    location: str
    latitude: float
    longitude: float
    source_type: str
    headline: str
    narrative_text: str
    effective_at: str | None
    payload: dict[str, Any]
    content_hash: str


def content_hash(headline: str, narrative_text: str) -> str:
    """Return the canonical hash shared by producers and the App boundary."""
    material = f"{headline.strip()}\n{narrative_text.strip()}"
    return sha256(material.encode("utf-8")).hexdigest()


def risk_level(precipitation_probability: float | int | None, weather_code: int | None) -> str:
    probability = float(precipitation_probability or 0)
    if probability >= 60 or weather_code in {65, 82, 95, 96, 99}:
        return "high"
    if probability >= 30 or weather_code in {51, 53, 55, 61, 63, 80, 81}:
        return "moderate"
    return "low"


def packing_recommendations(forecast: dict[str, Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    rain = float(forecast.get("precipitation_probability_max") or 0)
    low = float(forecast.get("temperature_min") or 99)
    high = float(forecast.get("temperature_max") or -99)
    wind = float(forecast.get("wind_speed_max") or 0)
    if rain >= 40:
        items.append(
            {"item": "Umbrella or rain shell", "reason": f"Rain probability is {rain:.0f}%."}
        )
    if low <= 15:
        items.append(
            {"item": "Warm layer or jacket", "reason": f"Low temperature may reach {low:.0f}°C."}
        )
    if high >= 30:
        items.append(
            {
                "item": "Sunscreen and water bottle",
                "reason": f"High temperature may reach {high:.0f}°C.",
            }
        )
    if wind >= 40:
        items.append(
            {"item": "Wind-resistant outer layer", "reason": f"Wind may reach {wind:.0f} km/h."}
        )
    if not items:
        items.append(
            {
                "item": "Comfortable walking shoes",
                "reason": "No material weather risk is currently forecast.",
            }
        )
    return items


class OpenMeteoWikimediaClient:
    def __init__(self, session: requests.Session | None = None, timeout: int = 20):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.session.headers.update(
            {"User-Agent": "tripwise-capstone/1.0 (educational Databricks project)"}
        )

    def _get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as error:
            raise TravelSourceError(
                "The destination provider is temporarily unavailable."
            ) from error
        if not isinstance(data, dict):
            raise TravelSourceError("The destination provider returned an unexpected response.")
        return data

    def resolve_location(self, location: str) -> dict[str, Any]:
        cleaned = location.strip()
        if not cleaned:
            raise ValueError("location must be a non-empty string.")
        data = self._get_json(
            "https://geocoding-api.open-meteo.com/v1/search",
            {"name": cleaned, "count": 1, "language": "en", "format": "json"},
        )
        results = data.get("results") or []
        if not results:
            raise ValueError(
                f"No location was found for '{cleaned}'. Add a country or region and try again."
            )
        item = results[0]
        return {
            "name": item["name"],
            "country": item.get("country"),
            "latitude": float(item["latitude"]),
            "longitude": float(item["longitude"]),
        }

    def forecast(self, location: str, days: int = 7) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if not 1 <= days <= 7:
            raise ValueError("days must be between 1 and 7.")
        resolved = self.resolve_location(location)
        data = self._get_json(
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": resolved["latitude"],
                "longitude": resolved["longitude"],
                "forecast_days": days,
                "timezone": "auto",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,wind_speed_10m_max,uv_index_max",
            },
        )
        daily = data.get("daily") or {}
        required = (
            "time",
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_probability_max",
            "wind_speed_10m_max",
            "uv_index_max",
        )
        if any(key not in daily for key in required):
            raise TravelSourceError(
                "The weather provider did not return a complete daily forecast."
            )
        rows = []
        for index, day_value in enumerate(daily["time"]):
            code = int(daily["weather_code"][index])
            rows.append(
                {
                    "date": day_value,
                    "weather_code": code,
                    "condition": WEATHER_CODES.get(code, "Unknown condition"),
                    "temperature_max": daily["temperature_2m_max"][index],
                    "temperature_min": daily["temperature_2m_min"][index],
                    "precipitation_probability_max": daily["precipitation_probability_max"][index],
                    "precipitation_sum": (
                        daily.get("precipitation_sum") or [None] * len(daily["time"])
                    )[index],
                    "wind_speed_max": daily["wind_speed_10m_max"][index],
                    "uv_index_max": daily["uv_index_max"][index],
                    "risk_level": risk_level(daily["precipitation_probability_max"][index], code),
                }
            )
        return resolved, rows

    def wikipedia_summary(self, location: str) -> dict[str, str]:
        title = location.strip().replace(" ", "_")
        data = self._get_json(f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}")
        extract = data.get("extract")
        if not isinstance(extract, str) or not extract.strip():
            raise TravelSourceError("Wikimedia did not return a description for this destination.")
        return {
            "title": str(data.get("title") or location),
            "extract": extract.strip(),
            "url": str((data.get("content_urls") or {}).get("desktop", {}).get("page") or ""),
        }

    def collect_context(self, location: str) -> list[DestinationContext]:
        resolved, forecasts = self.forecast(location)
        canonical = ", ".join(part for part in (resolved["name"], resolved.get("country")) if part)
        weather_text = "\n".join(
            f"{row['date']}: {row['condition']}; {row['temperature_min']}–{row['temperature_max']}°C; rain probability {row['precipitation_probability_max']}%; wind {row['wind_speed_max']} km/h."
            for row in forecasts
        )
        weather_payload = {"location": canonical, "forecast": forecasts}
        weather_headline = f"7-day weather outlook for {canonical}"
        documents = [
            DestinationContext(
                source_id=f"open-meteo:{canonical.casefold()}",
                location=canonical,
                latitude=resolved["latitude"],
                longitude=resolved["longitude"],
                source_type="weather_forecast",
                headline=weather_headline,
                narrative_text=weather_text,
                effective_at=forecasts[0]["date"],
                payload=weather_payload,
                content_hash=content_hash(weather_headline, weather_text),
            )
        ]
        try:
            summary = self.wikipedia_summary(resolved["name"])
            documents.append(
                DestinationContext(
                    source_id=f"wikimedia:{summary['title'].casefold()}",
                    location=canonical,
                    latitude=resolved["latitude"],
                    longitude=resolved["longitude"],
                    source_type="destination_summary",
                    headline=summary["title"],
                    narrative_text=summary["extract"],
                    effective_at=None,
                    payload=summary,
                    content_hash=content_hash(summary["title"], summary["extract"]),
                )
            )
        except TravelSourceError:
            # Weather context remains useful when the supplemental text source is unavailable.
            pass
        sleep(0.1)
        return documents
