import os
import unittest

os.environ["WEATHER_SKIP_SCHEMA_INIT"] = "1"

from app import create_app
from weather_client import ResolvedLocation, WeatherDocument, content_hash


class FakeRepository:
    def __init__(self):
        self.documents = []
        self.search_arguments = None

    def upsert_documents(self, documents):
        self.documents.extend(documents)
        return len(documents)

    def semantic_search(self, vector, top_k):
        self.search_arguments = (vector, top_k)
        return [{"location": "Chicago, IL", "headline": "Flood Watch", "chunk_text": "Flood risk", "similarity": 0.91}]


class FakeWeatherClient:
    def collect(self, locations, limit):
        location = ResolvedLocation(locations[0], 41.8781, -87.6298, "LOT/76,73")
        document_id = "forecast:LOT/76,73:2026-08-07T18:00:00-05:00"
        document = WeatherDocument(
            id=document_id,
            location=location.label,
            latitude=location.latitude,
            longitude=location.longitude,
            source_type="forecast",
            headline="Tonight",
            narrative_text="Rain is possible.",
            issued_at=None,
            effective_at="2026-08-07T18:00:00-05:00",
            payload={},
            content_hash=content_hash(document_id, "Rain is possible."),
        )
        return [document], [{"location": "Austin, TX", "message": "Temporary provider issue"}]


class WeatherApiTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeRepository()
        self.app = create_app(
            repository=self.repository,
            weather_client=FakeWeatherClient(),
            embedder=lambda texts: [[0.1, 0.2, 0.3] for _ in texts],
            initialize_schema=False,
        )
        self.client = self.app.test_client()

    def test_home_page_explains_the_api_console(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Weather Intelligence", response.data)
        self.assertIn(b"Sync weather data", response.data)
    def test_sync_persists_documents_and_keeps_location_warning(self):
        response = self.client.post("/weather/sync", json={"locations": ["Chicago, IL"], "limit": 10})
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["documents_written"], 1)
        self.assertEqual(len(payload["warnings"]), 1)
        self.assertEqual(len(self.repository.documents), 1)

    def test_sync_rejects_invalid_body(self):
        response = self.client.post("/weather/sync", json={"locations": []})
        self.assertEqual(response.status_code, 400)
        self.assertIn("locations", response.get_json()["error"])

    def test_search_validates_and_returns_semantic_results(self):
        invalid = self.client.post("/weather/search", json={"query": "", "top_k": 5})
        self.assertEqual(invalid.status_code, 400)

        response = self.client.post("/weather/search", json={"query": "flash flood risk", "top_k": 3})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["results"][0]["headline"], "Flood Watch")
        self.assertEqual(self.repository.search_arguments[1], 3)

    def test_search_limits_top_k(self):
        response = self.client.post("/weather/search", json={"query": "rain", "top_k": 21})
        self.assertEqual(response.status_code, 400)
        self.assertIn("top_k", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()