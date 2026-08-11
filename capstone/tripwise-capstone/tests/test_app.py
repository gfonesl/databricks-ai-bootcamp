from datetime import date

import pytest
from pydantic import ValidationError

from app import ItineraryRequest, TripRequest


def test_trip_requires_chronological_dates():
    with pytest.raises(ValidationError):
        TripRequest(display_name="Gabriel", title="Paris weekend", start_date=date(2026, 8, 20), end_date=date(2026, 8, 19))


def test_itinerary_accepts_valid_time():
    request = ItineraryRequest(title="Museum visit", scheduled_date=date(2026, 8, 20), start_time="09:30")
    assert request.is_outdoor is True


def test_itinerary_rejects_invalid_time():
    with pytest.raises(ValidationError):
        ItineraryRequest(title="Museum visit", scheduled_date=date(2026, 8, 20), start_time="9am")

