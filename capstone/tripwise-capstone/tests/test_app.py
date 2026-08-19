from datetime import date

import pytest
from app import ItineraryRequest, PipelineContextRequest, PipelineDocument, TripRequest
from pydantic import ValidationError
from travel_sources import content_hash


def test_trip_requires_chronological_dates():
    with pytest.raises(ValidationError):
        TripRequest(
            display_name="Gabriel",
            title="Paris weekend",
            start_date=date(2026, 8, 20),
            end_date=date(2026, 8, 19),
        )


def test_itinerary_accepts_valid_time():
    request = ItineraryRequest(
        title="Museum visit", scheduled_date=date(2026, 8, 20), start_time="09:30"
    )
    assert request.is_outdoor is True


def test_itinerary_rejects_invalid_time():
    with pytest.raises(ValidationError):
        ItineraryRequest(title="Museum visit", scheduled_date=date(2026, 8, 20), start_time="9am")


def _pipeline_document(**changes):
    headline = changes.pop("headline", "7-day weather outlook for Paris")
    narrative = changes.pop("narrative_text", "Clear weather is expected.")
    values = {
        "document_id": "open-meteo:paris, france",
        "location": "Paris, France",
        "latitude": 48.85,
        "longitude": 2.35,
        "source_type": "weather_forecast",
        "headline": headline,
        "narrative_text": narrative,
        "effective_at": "2026-08-14",
        "payload": {},
        "content_hash": content_hash(headline, narrative),
    }
    return PipelineDocument(**(values | changes))


def test_pipeline_document_rejects_tampered_hash():
    with pytest.raises(ValidationError, match="content_hash"):
        _pipeline_document(content_hash="0" * 64)


def test_pipeline_request_rejects_oversized_payload():
    document = _pipeline_document(payload={"raw": "x" * 251_000})
    with pytest.raises(ValidationError, match="must not exceed"):
        PipelineContextRequest(documents=[{"document": document, "chunks": [{"text": "context"}]}])
