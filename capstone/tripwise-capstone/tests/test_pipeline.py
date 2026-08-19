from argparse import Namespace
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import Mock

import pytest

PIPELINE_PATH = Path(__file__).parents[1] / "jobs" / "tripwise_pipeline.py"
SPEC = spec_from_file_location("tripwise_pipeline", PIPELINE_PATH)
pipeline = module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(pipeline)


def test_validated_app_url_accepts_only_databricks_apps_hosts():
    assert (
        pipeline.validated_app_url("https://tripwise-123.databricksapps.com/")
        == "https://tripwise-123.databricksapps.com"
    )
    for value in (
        "http://tripwise-123.databricksapps.com",
        "https://example.com",
        "https://tripwise-123.databricksapps.com/other",
        "https://tripwise-123.databricksapps.com?redirect=example.com",
    ):
        with pytest.raises(ValueError):
            pipeline.validated_app_url(value)


def test_ingest_does_not_overwrite_when_a_destination_fails(monkeypatch):
    monkeypatch.setattr(pipeline, "DEFAULT_DESTINATIONS", ("Paris", "Chicago"))
    monkeypatch.setattr(
        pipeline,
        "collect_context",
        Mock(side_effect=[[{"location": "Paris"}], RuntimeError("provider unavailable")]),
    )
    spark = Mock()

    with pytest.raises(RuntimeError, match="collection was incomplete"):
        pipeline.ingest(spark, Namespace(catalog="workspace", schema="default"))

    spark.createDataFrame.assert_not_called()


def test_weather_document_ids_are_stable(monkeypatch):
    geocode = {"results": [{"name": "Paris", "country": "France", "latitude": 1, "longitude": 2}]}
    forecast = {
        "daily": {
            "time": ["2026-08-14"],
            "weather_code": [0],
            "temperature_2m_max": [25],
            "temperature_2m_min": [15],
            "precipitation_probability_max": [5],
            "precipitation_sum": [0],
            "wind_speed_10m_max": [10],
            "uv_index_max": [5],
        }
    }
    summary = {"title": "Paris", "extract": "A city.", "content_urls": {}}
    monkeypatch.setattr(pipeline, "_json", Mock(side_effect=[geocode, forecast, summary]))
    monkeypatch.setattr(pipeline, "sleep", Mock())

    documents = pipeline.collect_context("Paris")

    assert documents[0]["document_id"] == "open-meteo:paris, france"
    assert documents[0]["content_hash"] == pipeline._hash(
        documents[0]["headline"], documents[0]["narrative_text"]
    )


def test_pipeline_payload_limits_are_checked_before_send():
    valid_item = {
        "document": {"document_id": "open-meteo:paris"},
        "chunks": [{"text": "weather"}],
    }
    pipeline.validate_pipeline_payload([valid_item])

    with pytest.raises(ValueError, match="1 to 12 documents"):
        pipeline.validate_pipeline_payload([valid_item] * 13)
    with pytest.raises(ValueError, match="1 to 20 chunks"):
        pipeline.validate_pipeline_payload([{**valid_item, "chunks": [{"text": "weather"}] * 21}])
    with pytest.raises(ValueError, match="250000 bytes"):
        pipeline.validate_pipeline_payload(
            [
                {
                    "document": {
                        "document_id": "open-meteo:paris",
                        "narrative_text": "x" * 250_000,
                    },
                    "chunks": [{"text": "weather"}],
                }
            ]
        )
