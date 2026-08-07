import unittest

from weather_client import ResolvedLocation, normalize_alert, normalize_forecast_period


class WeatherNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.location = ResolvedLocation("Chicago, IL", 41.8781, -87.6298, "LOT/76,73")

    def test_normalize_alert_uses_stable_id_and_instruction(self):
        feature = {
            "id": "urn:oid:2.49.0.1.840.0.alert-123",
            "properties": {
                "event": "Flood Watch",
                "description": "Heavy rain is possible.",
                "instruction": "Avoid flooded roads.",
                "sent": "2026-08-07T12:00:00+00:00",
            },
        }
        document = normalize_alert(feature, self.location)
        self.assertIsNotNone(document)
        self.assertEqual(document.id, "alert:urn:oid:2.49.0.1.840.0.alert-123:LOT/76,73")
        self.assertIn("Avoid flooded roads.", document.narrative_text)
        self.assertEqual(document.source_type, "alert")

    def test_normalize_forecast_uses_grid_and_period_start_for_id(self):
        period = {
            "name": "Tonight",
            "startTime": "2026-08-07T18:00:00-05:00",
            "shortForecast": "Heavy Rain",
            "detailedForecast": "Rain with localized flooding possible.",
        }
        document = normalize_forecast_period(period, self.location, "2026-08-07T15:00:00+00:00")
        self.assertIsNotNone(document)
        self.assertEqual(document.id, "forecast:LOT/76,73:2026-08-07T18:00:00-05:00")
        self.assertEqual(document.headline, "Tonight")
        self.assertIn("localized flooding", document.narrative_text)

    def test_incomplete_nws_records_are_skipped(self):
        self.assertIsNone(normalize_alert({"properties": {"id": "x"}}, self.location))
        self.assertIsNone(normalize_forecast_period({}, self.location, None))


if __name__ == "__main__":
    unittest.main()