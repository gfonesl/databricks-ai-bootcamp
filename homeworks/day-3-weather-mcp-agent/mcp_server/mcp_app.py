from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Callable

from fastapi import FastAPI
from fastmcp import FastMCP

from activity_repository import ActivityRepository, LakebaseError
from config import APP_NAME
from weather_adapter import OpenMeteoWeatherAdapter, WeatherProviderError

LOGGER = logging.getLogger(__name__)
weather = OpenMeteoWeatherAdapter()
activity = ActivityRepository()


@asynccontextmanager
async def mcp_lifespan(_: FastMCP):
    try:
        activity.initialize_schema()
        LOGGER.info("Lakebase MCP telemetry schema initialized")
    except LakebaseError:
        LOGGER.exception("MCP telemetry is unavailable; weather tools will still serve provider data")
    yield {}


mcp = FastMCP(
    "Weather Prediction MCP",
    instructions="Use these tools for current conditions, forecasts, and deterministic travel recommendations. Weather data comes from Open-Meteo.",
    lifespan=mcp_lifespan,
)


def _record(tool_name: str, *, location: str | None, requested_date: str | None = None, forecast_days: int | None = None, outcome: str, summary: str) -> None:
    try:
        activity.log(tool_name=tool_name, location=location, requested_date=requested_date, forecast_days=forecast_days, outcome=outcome, summary=summary)
    except LakebaseError:
        LOGGER.exception("Could not record MCP tool activity")


def _run(tool_name: str, operation: Callable[[], dict[str, Any]], *, location: str | None, requested_date: str | None = None, forecast_days: int | None = None) -> dict[str, Any]:
    try:
        result = operation()
        _record(tool_name, location=location, requested_date=requested_date, forecast_days=forecast_days, outcome="success", summary=f"{tool_name} completed for {result.get('location', location or 'unknown location')}.")
        return result
    except (ValueError, WeatherProviderError) as error:
        message = str(error)
        _record(tool_name, location=location, requested_date=requested_date, forecast_days=forecast_days, outcome="error", summary=message)
        return {"error": "weather_request_failed", "message": message}


def current_weather_tool(location: str) -> dict[str, Any]:
    """Get live current weather for a resolvable city or place.

    Args:
        location: City plus country/state when needed, for example "Chicago, IL".
    Returns:
        Temperature, apparent temperature, humidity, wind, condition and observation time in metric units.
    """
    return _run("get_current_weather", lambda: weather.get_current_weather(location), location=location)


def weather_forecast_tool(location: str, days: int = 3) -> dict[str, Any]:
    """Get a multi-day weather forecast in metric units.

    Args:
        location: City plus country/state when needed.
        days: Number of daily forecasts from 1 through 7.
    Returns:
        Daily high/low temperature, precipitation probability, rainfall, wind and condition.
    """
    return _run("get_weather_forecast", lambda: weather.get_forecast(location, days), location=location, forecast_days=days)


def travel_recommendation_tool(location: str, date: str) -> dict[str, Any]:
    """Make a transparent weather-based packing recommendation for an ISO date.

    Args:
        location: City plus country/state when needed.
        date: Target date in YYYY-MM-DD format, inside the next seven forecast days.
    Returns:
        Deterministic recommendations and the forecast evidence used. Umbrella: rain probability >=40%; jacket: min <=15C; heat: max >=30C; wind warning: >=40 km/h.
    """
    return _run("get_travel_recommendation", lambda: weather.get_travel_recommendation(location, date), location=location, requested_date=date)


# FastMCP v2 exposes decorated functions as FunctionTool objects. Keeping the
# implementation callables above makes their business logic directly testable.
get_current_weather = mcp.tool(name="get_current_weather")(current_weather_tool)
get_weather_forecast = mcp.tool(name="get_weather_forecast")(weather_forecast_tool)
get_travel_recommendation = mcp.tool(name="get_travel_recommendation")(travel_recommendation_tool)


mcp_asgi = mcp.http_app(path="/mcp")
app = FastAPI(title=APP_NAME, lifespan=mcp_asgi.lifespan)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": APP_NAME, "transport": "streamable-http", "mcp_path": "/mcp"}


app.mount("/", mcp_asgi)
