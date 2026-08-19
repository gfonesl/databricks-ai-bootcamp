from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from typing import Any

import requests
from config import MAX_SYNC_LIMIT

NWS_BASE_URL = "https://api.weather.gov"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


class WeatherClientError(RuntimeError):
    """Raised for invalid locations and upstream weather API failures."""


@dataclass(frozen=True)
class ResolvedLocation:
    label: str
    latitude: float
    longitude: float
    grid_id: str


@dataclass(frozen=True)
class WeatherDocument:
    id: str
    location: str
    latitude: float
    longitude: float
    source_type: str
    headline: str
    narrative_text: str
    issued_at: str | None
    effective_at: str | None
    payload: dict[str, Any]
    content_hash: str

    def as_record(self) -> dict[str, Any]:
        return asdict(self)


def content_hash(*values: object) -> str:
    serialized = json.dumps(values, sort_keys=True, default=str, ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _narrative(*parts: str | None) -> str:
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def normalize_alert(feature: dict[str, Any], location: ResolvedLocation) -> WeatherDocument | None:
    properties = feature.get("properties") or {}
    narrative = _narrative(properties.get("description"), properties.get("instruction"))
    source_id = properties.get("id") or feature.get("id")
    if not source_id or not narrative:
        return None
    document_id = f"alert:{source_id}:{location.grid_id}"
    return WeatherDocument(
        id=document_id,
        location=location.label,
        latitude=location.latitude,
        longitude=location.longitude,
        source_type="alert",
        headline=properties.get("event") or properties.get("headline") or "Weather alert",
        narrative_text=narrative,
        issued_at=properties.get("sent") or properties.get("onset"),
        effective_at=properties.get("effective") or properties.get("onset"),
        payload={"feature": feature, "grid_id": location.grid_id},
        content_hash=content_hash(document_id, narrative),
    )


def normalize_forecast_period(
    period: dict[str, Any], location: ResolvedLocation, generated_at: str | None
) -> WeatherDocument | None:
    narrative = _narrative(period.get("detailedForecast"), period.get("shortForecast"))
    period_start = period.get("startTime")
    if not period_start or not narrative:
        return None
    document_id = f"forecast:{location.grid_id}:{period_start}"
    headline = period.get("name") or period.get("shortForecast") or "Weather forecast"
    return WeatherDocument(
        id=document_id,
        location=location.label,
        latitude=location.latitude,
        longitude=location.longitude,
        source_type="forecast",
        headline=headline,
        narrative_text=narrative,
        issued_at=generated_at,
        effective_at=period_start,
        payload={"period": period, "grid_id": location.grid_id},
        content_hash=content_hash(document_id, narrative),
    )


class NWSWeatherClient:
    """Collect NWS alerts and detailed forecast narratives for US locations."""

    def __init__(self, session: requests.Session | None = None, geocode_delay_seconds: float = 1.0):
        self.session = session or requests.Session()
        self.geocode_delay_seconds = geocode_delay_seconds
        self.session.headers.update(
            {
                "Accept": "application/geo+json, application/json",
                "User-Agent": os.getenv(
                    "WEATHER_HTTP_USER_AGENT", "weather-intelligence-bootcamp/1.0"
                ),
            }
        )
        self._locations: dict[str, ResolvedLocation] = {}

    def _get_json(self, url: str, **kwargs: Any) -> Any:
        try:
            response = self.session.get(url, timeout=20, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as error:
            raise WeatherClientError(f"Weather provider request failed: {error}") from error

    def resolve_location(self, location: str) -> ResolvedLocation:
        label = location.strip()
        if not label:
            raise WeatherClientError("Location cannot be empty.")
        if label in self._locations:
            return self._locations[label]

        geocoded = self._get_json(
            NOMINATIM_URL,
            params={"q": f"{label}, USA", "format": "jsonv2", "limit": 1, "countrycodes": "us"},
        )
        if not geocoded:
            raise WeatherClientError(f"Location not found: {label}")
        latitude = float(geocoded[0]["lat"])
        longitude = float(geocoded[0]["lon"])
        if self.geocode_delay_seconds:
            time.sleep(self.geocode_delay_seconds)

        point = self._get_json(f"{NWS_BASE_URL}/points/{latitude},{longitude}")
        properties = point.get("properties") or {}
        office = properties.get("gridId")
        grid_x = properties.get("gridX")
        grid_y = properties.get("gridY")
        forecast_url = properties.get("forecast")
        if not office or grid_x is None or grid_y is None or not forecast_url:
            raise WeatherClientError(f"NWS does not provide a forecast grid for: {label}")
        resolved = ResolvedLocation(label, latitude, longitude, f"{office}/{grid_x},{grid_y}")
        self._locations[label] = resolved
        return resolved

    def collect_location(self, location_name: str) -> list[WeatherDocument]:
        location = self.resolve_location(location_name)
        alerts = self._get_json(
            f"{NWS_BASE_URL}/alerts/active",
            params={"point": f"{location.latitude},{location.longitude}"},
        )
        point = self._get_json(f"{NWS_BASE_URL}/points/{location.latitude},{location.longitude}")
        forecast_url = (point.get("properties") or {}).get("forecast")
        if not forecast_url:
            raise WeatherClientError(f"NWS does not provide a forecast URL for: {location.label}")
        forecast = self._get_json(forecast_url)

        documents = [
            document
            for feature in alerts.get("features") or []
            if (document := normalize_alert(feature, location)) is not None
        ]
        forecast_properties = forecast.get("properties") or {}
        documents.extend(
            document
            for period in forecast_properties.get("periods") or []
            if (
                document := normalize_forecast_period(
                    period,
                    location,
                    forecast_properties.get("generatedAt") or forecast_properties.get("updated"),
                )
            )
            is not None
        )
        return documents

    def collect(
        self, locations: list[str], limit: int = MAX_SYNC_LIMIT
    ) -> tuple[list[WeatherDocument], list[dict[str, str]]]:
        capped_limit = max(1, min(int(limit), MAX_SYNC_LIMIT))
        documents: list[WeatherDocument] = []
        warnings: list[dict[str, str]] = []
        seen: set[str] = set()
        for location in locations:
            try:
                for document in self.collect_location(location):
                    if document.id not in seen and len(documents) < capped_limit:
                        documents.append(document)
                        seen.add(document.id)
            except WeatherClientError as error:
                warnings.append({"location": location, "message": str(error)})
            if len(documents) >= capped_limit:
                break
        return documents, warnings
