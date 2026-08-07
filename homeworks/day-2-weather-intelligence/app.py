from __future__ import annotations

import logging
import os
from typing import Any, Callable

from flask import Flask, jsonify, request

from config import DEFAULT_LOCATIONS, MAX_SEARCH_RESULTS, MAX_SYNC_LIMIT
from embedding import EmbeddingError, embed_texts
from lakebase import LakebaseError, WeatherRepository
from weather_client import NWSWeatherClient, WeatherClientError

LOGGER = logging.getLogger(__name__)


def _error(message: str, status_code: int):
    return jsonify({"error": message}), status_code


def _json_body() -> dict[str, Any]:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object.")
    return body


def _locations(value: Any) -> list[str]:
    if value is None:
        return list(DEFAULT_LOCATIONS)
    if not isinstance(value, list) or not value:
        raise ValueError("locations must be a non-empty list of location names.")
    cleaned = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if len(cleaned) != len(value):
        raise ValueError("Each location must be a non-empty string.")
    return cleaned


def _integer(value: Any, name: str, minimum: int, maximum: int, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}.")
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}.") from error
    if not minimum <= number <= maximum:
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}.")
    return number


def create_app(
    repository: WeatherRepository | None = None,
    weather_client: NWSWeatherClient | None = None,
    embedder: Callable[[list[str]], list[list[float]]] = embed_texts,
    initialize_schema: bool = True,
) -> Flask:
    app = Flask(__name__)
    repo = repository or WeatherRepository()
    client = weather_client or NWSWeatherClient()

    if initialize_schema:
        repo.initialize_schema()

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok", "service": "day2-weather-intelligence"})

    @app.post("/weather/sync")
    def sync_weather():
        try:
            body = _json_body()
            locations = _locations(body.get("locations"))
            limit = _integer(body.get("limit"), "limit", 1, MAX_SYNC_LIMIT, MAX_SYNC_LIMIT)
            documents, warnings = client.collect(locations, limit)
            written = repo.upsert_documents(documents)
            return jsonify(
                {
                    "locations": locations,
                    "documents_collected": len(documents),
                    "documents_written": written,
                    "warnings": warnings,
                }
            )
        except ValueError as error:
            return _error(str(error), 400)
        except (WeatherClientError, LakebaseError) as error:
            LOGGER.exception("Weather synchronization failed")
            return _error(str(error), 503)

    @app.post("/weather/search")
    def search_weather():
        try:
            body = _json_body()
            query = body.get("query")
            if not isinstance(query, str) or not query.strip():
                raise ValueError("query must be a non-empty string.")
            top_k = _integer(body.get("top_k"), "top_k", 1, MAX_SEARCH_RESULTS, 5)
            vectors = embedder([query.strip()])
            if len(vectors) != 1:
                raise EmbeddingError("The embedding model did not return one query vector.")
            results = repo.semantic_search(vectors[0], top_k)
            response: dict[str, Any] = {"query": query.strip(), "top_k": top_k, "results": results}
            if not results:
                response["message"] = (
                    "No weather embeddings are available. Run /weather/sync and "
                    "scripts/ingest_weather_embeddings.py first."
                )
            return jsonify(response)
        except ValueError as error:
            return _error(str(error), 400)
        except (EmbeddingError, LakebaseError) as error:
            LOGGER.exception("Weather search failed")
            return _error(str(error), 503)

    return app


app = create_app(initialize_schema=os.getenv("WEATHER_SKIP_SCHEMA_INIT") != "1")