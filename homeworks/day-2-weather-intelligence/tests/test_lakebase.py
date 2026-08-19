import unittest
from unittest.mock import MagicMock, patch

from lakebase import WeatherRepository
from weather_client import ResolvedLocation, normalize_forecast_period


class LakebaseRepositoryTests(unittest.TestCase):
    @patch("lakebase.execute_values")
    @patch("lakebase.lakebase_connection")
    def test_upsert_documents_uses_idempotent_conflict_handling(
        self, connection_factory, execute_values
    ):
        cursor = MagicMock()
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        connection_factory.return_value.__enter__.return_value = connection
        location = ResolvedLocation("Austin, TX", 30.2672, -97.7431, "EWX/156,89")
        document = normalize_forecast_period(
            {
                "name": "Tonight",
                "startTime": "2026-08-07T18:00:00-05:00",
                "shortForecast": "Rain",
                "detailedForecast": "Heavy rain is possible.",
            },
            location,
            "2026-08-07T15:00:00+00:00",
        )

        written = WeatherRepository().upsert_documents([document])

        self.assertEqual(written, 1)
        query = execute_values.call_args.args[1]
        self.assertIn("ON CONFLICT (id) DO UPDATE", query)
        self.assertIn("content_hash IS DISTINCT FROM", query)


if __name__ == "__main__":
    unittest.main()
