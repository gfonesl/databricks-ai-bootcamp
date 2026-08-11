from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import requests

from config import (
    HTTP_TIMEOUT_SECONDS,
    HTTP_USER_AGENT,
    MAX_FORECAST_DAYS,
    MIN_FORECAST_DAYS,
    OPEN_METEO_FORECAST_URL,
    OPEN_METEO_GEOCODING_URL,
)


class WeatherProviderError(RuntimeError):
    """A recoverable Open-Meteo provider failure."""


class LocationNotFoundError(WeatherProviderError):
    """The requested location could not be resolved by Open-Meteo."""


WMO_DESCRIPTIONS = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    80: "Rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def weather_description(code: Any) -> str:
    """Translate the WMO weather code into a readable, stable description."""
    try:
        return WMO_DESCRIPTIONS.get(int(code), "Unknown conditions")
    except (TypeError, ValueError):
        return "Unknown conditions"


@dataclass(frozen=True)
class ResolvedLocation:
    name: str
    country: str
    latitude: float
    longitude: float
    timezone: str

    @property
    def label(self) -> str:
        return f"{self.name}, {self.country}" if self.country else self.name


class OpenMeteoWeatherAdapter:
    """HTTP and parsing boundary for Open-Meteo. MCP tools do not call requests."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": HTTP_USER_AGENT, "Accept": "application/json"})

    def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.session.get(url, params=params, timeout=HTTP_TIMEOUT_SECONDS)
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, ValueError) as error:
            raise WeatherProviderError("The weather provider is temporarily unavailable. Please try again.") from error
        if not isinstance(body, dict):
            raise WeatherProviderError("The weather provider returned an unexpected response.")
        return body

    def resolve_location(self, location: str) -> ResolvedLocation:
        cleaned = _location(location)
        body = self._get_json(
            OPEN_METEO_GEOCODING_URL,
            {"name": cleaned, "count": 1, "language": "en", "format": "json"},
        )
        results = body.get("results")
        if not isinstance(results, list) or not results or not isinstance(results[0], dict):
            raise LocationNotFoundError(f"I could not resolve the location '{cleaned}'. Try a city and country or state.")
        result = results[0]
        try:
            return ResolvedLocation(
                name=str(result["name"]),
                country=str(result.get("country", "")),
                latitude=float(result["latitude"]),
                longitude=float(result["longitude"]),
                timezone=str(result.get("timezone", "auto")),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise WeatherProviderError("The weather provider returned an incomplete location response.") from error

    def _forecast_payload(self, resolved: ResolvedLocation, days: int) -> dict[str, Any]:
        return self._get_json(
            OPEN_METEO_FORECAST_URL,
            {
                "latitude": resolved.latitude,
                "longitude": resolved.longitude,
                "timezone": resolved.timezone,
                "forecast_days": _days(days),
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,rain_sum,wind_speed_10m_max",
                "temperature_unit": "celsius",
                "wind_speed_unit": "kmh",
                "precipitation_unit": "mm",
            },
        )

    def get_current_weather(self, location: str) -> dict[str, Any]:
        resolved = self.resolve_location(location)
        payload = self._forecast_payload(resolved, 1)
        current = payload.get("current")
        if not isinstance(current, dict):
            raise WeatherProviderError("Current conditions were not available for this location.")
        return {
            "location": resolved.label,
            "latitude": resolved.latitude,
            "longitude": resolved.longitude,
            "observed_at": current.get("time"),
            "temperature_c": current.get("temperature_2m"),
            "apparent_temperature_c": current.get("apparent_temperature"),
            "relative_humidity_percent": current.get("relative_humidity_2m"),
            "wind_speed_kmh": current.get("wind_speed_10m"),
            "condition": weather_description(current.get("weather_code")),
            "source": "Open-Meteo",
        }

    def get_forecast(self, location: str, days: int) -> dict[str, Any]:
        resolved = self.resolve_location(location)
        payload = self._forecast_payload(resolved, days)
        daily = payload.get("daily")
        if not isinstance(daily, dict) or not isinstance(daily.get("time"), list):
            raise WeatherProviderError("Forecast data was not available for this location.")
        forecast = []
        for index, forecast_date in enumerate(daily["time"]):
            forecast.append(
                {
                    "date": forecast_date,
                    "condition": weather_description(_at(daily, "weather_code", index)),
                    "temperature_max_c": _at(daily, "temperature_2m_max", index),
                    "temperature_min_c": _at(daily, "temperature_2m_min", index),
                    "precipitation_probability_percent": _at(daily, "precipitation_probability_max", index),
                    "rain_mm": _at(daily, "rain_sum", index),
                    "wind_speed_max_kmh": _at(daily, "wind_speed_10m_max", index),
                }
            )
        return {"location": resolved.label, "latitude": resolved.latitude, "longitude": resolved.longitude, "forecast": forecast, "source": "Open-Meteo"}

    def get_travel_recommendation(self, location: str, requested_date: str) -> dict[str, Any]:
        target = _iso_date(requested_date)
        forecast_payload = self.get_forecast(location, MAX_FORECAST_DAYS)
        day = next((item for item in forecast_payload["forecast"] if item["date"] == target.isoformat()), None)
        if day is None:
            available = [item["date"] for item in forecast_payload["forecast"]]
            raise ValueError(f"{target.isoformat()} is outside the available forecast horizon ({available[0]} to {available[-1]}).")

        recommendations: list[str] = []
        if _number(day["precipitation_probability_percent"]) >= 40:
            recommendations.append("Bring an umbrella or waterproof layer.")
        if _number(day["temperature_min_c"]) <= 15:
            recommendations.append("Bring a jacket for cooler conditions.")
        if _number(day["temperature_max_c"]) >= 30:
            recommendations.append("Plan for heat: water, shade, and sun protection.")
        if _number(day["wind_speed_max_kmh"]) >= 40:
            recommendations.append("Expect strong wind; secure loose items and plan outdoor activities carefully.")
        if not recommendations:
            recommendations.append("No special weather gear is indicated by the configured thresholds.")

        return {
            "location": forecast_payload["location"],
            "date": target.isoformat(),
            "recommendation": recommendations,
            "evidence": day,
            "thresholds": {"umbrella_precipitation_probability_percent": 40, "jacket_min_temperature_c": 15, "heat_max_temperature_c": 30, "wind_warning_kmh": 40},
            "source": "Open-Meteo",
        }


def _location(value: Any) -> str:
    if not isinstance(value, str) or not (cleaned := value.strip()) or len(cleaned) > 120:
        raise ValueError("location must be a non-empty place name up to 120 characters.")
    return cleaned


def _days(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(f"days must be an integer between {MIN_FORECAST_DAYS} and {MAX_FORECAST_DAYS}.")
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"days must be an integer between {MIN_FORECAST_DAYS} and {MAX_FORECAST_DAYS}.") from error
    if not MIN_FORECAST_DAYS <= number <= MAX_FORECAST_DAYS:
        raise ValueError(f"days must be an integer between {MIN_FORECAST_DAYS} and {MAX_FORECAST_DAYS}.")
    return number


def _iso_date(value: Any) -> date:
    if not isinstance(value, str):
        raise ValueError("date must use ISO format YYYY-MM-DD.")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("date must use ISO format YYYY-MM-DD.") from error


def _at(payload: dict[str, Any], key: str, index: int) -> Any:
    values = payload.get(key)
    return values[index] if isinstance(values, list) and index < len(values) else None


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
