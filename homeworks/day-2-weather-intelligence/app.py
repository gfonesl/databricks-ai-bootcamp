from __future__ import annotations

import logging
import os
from typing import Any, Callable

from config import DEFAULT_LOCATIONS, MAX_SEARCH_RESULTS, MAX_SYNC_LIMIT
from embedding import EmbeddingError, embed_texts
from flask import Flask, jsonify, request
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

    @app.get("/")
    def home():
        return """
        <!doctype html>
        <html lang="en">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>Weather Intelligence</title>
          <style>
            :root { color-scheme: dark; font-family: Inter, system-ui, sans-serif; }
            body { margin: 0; background: #101114; color: #f5f7fa; }
            main { max-width: 880px; margin: 0 auto; padding: 48px 24px 64px; }
            .eyebrow { color: #8db4ff; font-size: .9rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
            h1 { font-size: clamp(2rem, 5vw, 3.4rem); margin: 10px 0; }
            p { color: #c5cad3; line-height: 1.55; }
            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 16px; margin-top: 28px; }
            section { background: #191b20; border: 1px solid #30333a; border-radius: 14px; padding: 20px; }
            h2 { margin-top: 0; font-size: 1.1rem; }
            input { box-sizing: border-box; width: 100%; margin: 9px 0; padding: 11px; border: 1px solid #50545d; border-radius: 8px; background: #101114; color: #f5f7fa; }
            button { margin-top: 8px; padding: 10px 14px; border: 0; border-radius: 8px; background: #3d7eff; color: #fff; font-weight: 700; cursor: pointer; }
            button:disabled { opacity: .6; cursor: wait; }
            pre { min-height: 46px; max-height: 320px; overflow: auto; white-space: pre-wrap; color: #b9d5ff; }
            code { color: #b9d5ff; }
          </style>
        </head>
        <body>
          <main>
            <div class="eyebrow">Databricks AI Bootcamp · Day 2</div>
            <h1>Weather Intelligence</h1>
            <p>Weather documents from the National Weather Service, stored in Lakebase and retrieved with pgvector semantic search.</p>
            <div class="grid">
              <section>
                <h2>1. Sync NWS documents</h2>
                <p>Fetch current forecast narratives for Chicago and Austin.</p>
                <button id="sync">Sync weather data</button>
                <pre id="sync-output">Ready.</pre>
              </section>
              <section>
                <h2>2. Search semantically</h2>
                <input id="query" value="flash flood risk this weekend" aria-label="Search query">
                <input id="top-k" type="number" min="1" max="20" value="5" aria-label="Number of results">
                <button id="search">Search Lakebase</button>
                <pre id="search-output">Run sync and embeddings before searching a new database.</pre>
              </section>
            </div>
            <p><code>GET /healthz</code> · <code>POST /weather/sync</code> · <code>POST /weather/search</code></p>
          </main>
          <script>
            async function callApi(path, body, output, button) {
              button.disabled = true;
              output.textContent = 'Working…';
              try {
                const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
                const payload = await response.json();
                output.textContent = JSON.stringify(payload, null, 2);
              } catch (error) {
                output.textContent = `Request failed: ${error.message}`;
              } finally {
                button.disabled = false;
              }
            }
            const syncButton = document.getElementById('sync');
            syncButton.addEventListener('click', () => callApi('/weather/sync', {locations: ['Chicago, IL', 'Austin, TX'], limit: 50}, document.getElementById('sync-output'), syncButton));
            const searchButton = document.getElementById('search');
            searchButton.addEventListener('click', () => callApi('/weather/search', {query: document.getElementById('query').value, top_k: Number(document.getElementById('top-k').value)}, document.getElementById('search-output'), searchButton));
          </script>
        </body>
        </html>
        """

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
