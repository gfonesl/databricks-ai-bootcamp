from __future__ import annotations

import unittest

import mcp_app
from weather_adapter import WeatherProviderError


class FakeWeather:
    def get_current_weather(self, location):
        return {"location": location, "temperature_c": 20}

    def get_forecast(self, location, days):
        return {"location": location, "forecast": [{"date": "2026-08-10"}] * days}

    def get_travel_recommendation(self, location, date):
        return {"location": location, "date": date, "recommendation": ["Bring an umbrella."]}


class FakeActivity:
    def __init__(self):
        self.events = []

    def log(self, **event):
        self.events.append(event)


class FailingWeather:
    def get_current_weather(self, location):
        raise WeatherProviderError(
            "The weather provider is temporarily unavailable. Please try again."
        )


class McpToolTests(unittest.TestCase):
    def setUp(self):
        self.previous_weather = mcp_app.weather
        self.previous_activity = mcp_app.activity
        self.activity = FakeActivity()
        mcp_app.weather = FakeWeather()
        mcp_app.activity = self.activity

    def tearDown(self):
        mcp_app.weather = self.previous_weather
        mcp_app.activity = self.previous_activity

    def test_tools_delegate_and_log_success(self):
        self.assertEqual(mcp_app.current_weather_tool("Chicago")["temperature_c"], 20)
        self.assertEqual(len(mcp_app.weather_forecast_tool("Austin", 2)["forecast"]), 2)
        self.assertIn(
            "umbrella",
            mcp_app.travel_recommendation_tool("Austin", "2026-08-10")["recommendation"][0].lower(),
        )
        self.assertEqual(
            [event["tool_name"] for event in self.activity.events],
            ["get_current_weather", "get_weather_forecast", "get_travel_recommendation"],
        )

    def test_provider_failure_returns_a_clean_tool_error_and_is_logged(self):
        mcp_app.weather = FailingWeather()
        result = mcp_app.current_weather_tool("Chicago")
        self.assertEqual(result["error"], "weather_request_failed")
        self.assertIn("temporarily unavailable", result["message"])
        self.assertEqual(self.activity.events[0]["outcome"], "error")


if __name__ == "__main__":
    unittest.main()
