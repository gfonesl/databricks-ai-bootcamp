from __future__ import annotations

import unittest

from weather_adapter import OpenMeteoWeatherAdapter


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class FakeSession:
    headers = {}

    def get(self, url, params, timeout):
        if "geocoding" in url:
            return FakeResponse(
                {
                    "results": [
                        {
                            "name": "Chicago",
                            "country": "United States",
                            "latitude": 41.88,
                            "longitude": -87.63,
                            "timezone": "America/Chicago",
                        }
                    ]
                }
            )
        return FakeResponse(
            {
                "current": {
                    "time": "2026-08-10T10:00",
                    "temperature_2m": 22,
                    "apparent_temperature": 21,
                    "relative_humidity_2m": 52,
                    "weather_code": 2,
                    "wind_speed_10m": 13,
                },
                "daily": {
                    "time": ["2026-08-10", "2026-08-11"],
                    "weather_code": [61, 0],
                    "temperature_2m_max": [31, 22],
                    "temperature_2m_min": [14, 12],
                    "precipitation_probability_max": [55, 5],
                    "rain_sum": [4.2, 0],
                    "wind_speed_10m_max": [45, 10],
                },
            }
        )


class WeatherAdapterTests(unittest.TestCase):
    def setUp(self):
        self.adapter = OpenMeteoWeatherAdapter(session=FakeSession())

    def test_current_weather_is_normalized(self):
        result = self.adapter.get_current_weather("Chicago, IL")
        self.assertEqual(result["location"], "Chicago, United States")
        self.assertEqual(result["condition"], "Partly cloudy")
        self.assertEqual(result["temperature_c"], 22)

    def test_forecast_enforces_day_bounds(self):
        with self.assertRaises(ValueError):
            self.adapter.get_forecast("Chicago", 8)

    def test_recommendation_exposes_threshold_evidence(self):
        result = self.adapter.get_travel_recommendation("Chicago", "2026-08-10")
        self.assertTrue(any("umbrella" in item.lower() for item in result["recommendation"]))
        self.assertTrue(any("jacket" in item.lower() for item in result["recommendation"]))
        self.assertTrue(any("wind" in item.lower() for item in result["recommendation"]))

    def test_invalid_location_is_clean_error(self):
        with self.assertRaises(ValueError):
            self.adapter.get_current_weather("")


if __name__ == "__main__":
    unittest.main()
