from __future__ import annotations

import unittest

from app import create_app
from lakebase import LakebaseError


class FakeRepository:
    def overview(self):
        return {"overview": {"total_calls": 3, "failures": 1, "last_hour_calls": 2}, "activity": [{"tool_name": "get_current_weather", "location": "Chicago", "requested_date": None, "forecast_days": None, "outcome": "success", "summary": "ok", "created_at": "2026-08-10T12:00:00+00:00"}]}


class FailingRepository:
    def overview(self):
        raise LakebaseError("missing grant")


class DashboardTests(unittest.TestCase):
    def test_dashboard_displays_activity(self):
        response = create_app(FakeRepository()).test_client().get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Total calls", response.data)
        self.assertIn(b"Chicago", response.data)

    def test_api_reports_read_grant_problem(self):
        response = create_app(FailingRepository()).test_client().get("/api/activity")
        self.assertEqual(response.status_code, 503)
        self.assertIn("missing grant", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
