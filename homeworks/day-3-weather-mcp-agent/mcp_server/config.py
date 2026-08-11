from __future__ import annotations

import os

APP_NAME = "day3-weather-mcp"
SCHEMA = "weather_agent_ops"
ACTIVITY_TABLE = f"{SCHEMA}.mcp_tool_activity"

OPEN_METEO_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HTTP_TIMEOUT_SECONDS = float(os.getenv("WEATHER_HTTP_TIMEOUT_SECONDS", "12"))
HTTP_USER_AGENT = os.getenv("WEATHER_HTTP_USER_AGENT", "weather-mcp-bootcamp/1.0")

MAX_FORECAST_DAYS = 7
MIN_FORECAST_DAYS = 1
