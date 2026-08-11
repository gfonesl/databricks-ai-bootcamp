"""Spark pipeline for Tripwise destination context and Lakebase pgvector loading.

Run as two Lakeflow Job tasks: `--stage ingest` writes Delta, then `--stage vectorize`
reads normalized Delta context and writes Lakebase with psycopg2 (never Spark JDBC).
"""
from __future__ import annotations

import argparse
import json
import os
from hashlib import sha256
from time import sleep
from typing import Any

from pyspark.sql import SparkSession
from pyspark.dbutils import DBUtils
from pyspark.sql.functions import current_timestamp
import requests

# Keep its source/embedding adapter self-contained. Spark Python tasks do not
# guarantee that importing application files by a relative filesystem path works.
DEFAULT_DESTINATIONS = ("Rio de Janeiro", "Chicago", "Paris")
SCHEMA = "tripwise"
WEATHER_CODES = {0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle", 61: "Slight rain", 63: "Rain", 65: "Heavy rain", 80: "Rain showers", 81: "Rain showers", 82: "Violent rain showers", 95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with hail"}


def _hash(*values: object) -> str:
    return sha256("\n".join(str(value or "") for value in values).encode("utf-8")).hexdigest()


def _risk(probability: float | int | None, code: int) -> str:
    if float(probability or 0) >= 60 or code in {65, 82, 95, 96, 99}:
        return "high"
    if float(probability or 0) >= 30 or code in {51, 53, 55, 61, 63, 80, 81}:
        return "moderate"
    return "low"


def _json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        response = requests.get(url, params=params, headers={"User-Agent": "tripwise-capstone/1.0 (Databricks educational project)"}, timeout=20)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as error:
        raise RuntimeError("Public destination source is unavailable.") from error


def collect_context(location: str) -> list[dict[str, Any]]:
    geocoded = _json("https://geocoding-api.open-meteo.com/v1/search", {"name": location, "count": 1, "language": "en", "format": "json"}).get("results") or []
    if not geocoded:
        raise RuntimeError(f"No location was found for {location}.")
    point = geocoded[0]
    canonical = ", ".join(part for part in (point["name"], point.get("country")) if part)
    daily = _json("https://api.open-meteo.com/v1/forecast", {"latitude": point["latitude"], "longitude": point["longitude"], "forecast_days": 7, "timezone": "auto", "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,wind_speed_10m_max,uv_index_max"})["daily"]
    forecast = []
    for index, forecast_date in enumerate(daily["time"]):
        code = int(daily["weather_code"][index])
        forecast.append({"date": forecast_date, "weather_code": code, "condition": WEATHER_CODES.get(code, "Unknown condition"), "temperature_max": daily["temperature_2m_max"][index], "temperature_min": daily["temperature_2m_min"][index], "precipitation_probability_max": daily["precipitation_probability_max"][index], "precipitation_sum": daily["precipitation_sum"][index], "wind_speed_max": daily["wind_speed_10m_max"][index], "uv_index_max": daily["uv_index_max"][index], "risk_level": _risk(daily["precipitation_probability_max"][index], code)})
    text = "\n".join(f"{item['date']}: {item['condition']}; {item['temperature_min']}–{item['temperature_max']}°C; rain probability {item['precipitation_probability_max']}%; wind {item['wind_speed_max']} km/h." for item in forecast)
    documents = [{"document_id": f"open-meteo:{canonical.casefold()}:{forecast[0]['date']}", "location": canonical, "latitude": float(point["latitude"]), "longitude": float(point["longitude"]), "source_type": "weather_forecast", "headline": f"7-day weather outlook for {canonical}", "narrative_text": text, "effective_at": forecast[0]["date"], "payload_json": json.dumps({"location": canonical, "forecast": forecast}), "content_hash": _hash(canonical, text)}]
    try:
        title = point["name"].replace(" ", "_")
        summary = _json(f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}")
        extract = summary.get("extract")
        if extract:
            documents.append({"document_id": f"wikimedia:{str(summary.get('title') or point['name']).casefold()}", "location": canonical, "latitude": float(point["latitude"]), "longitude": float(point["longitude"]), "source_type": "destination_summary", "headline": str(summary.get("title") or point["name"]), "narrative_text": extract, "effective_at": None, "payload_json": json.dumps({"title": summary.get("title"), "url": (summary.get("content_urls") or {}).get("desktop", {}).get("page", "")}), "content_hash": _hash(summary.get("title"), extract)})
    except RuntimeError:
        pass
    sleep(0.1)
    return documents


def chunk_text(text: str, size: int = 800, overlap: int = 100) -> list[str]:
    normalized = " ".join(text.split())
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + size, len(normalized))
        if end < len(normalized) and not normalized[end].isspace():
            end = max(normalized.rfind(" ", start + 1, end), start + 1)
        chunks.append(normalized[start:end].strip())
        if end >= len(normalized): break
        start = max(end - overlap, start + 1)
    return [item for item in chunks if item]


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Tripwise context with Spark.")
    parser.add_argument("--stage", choices=("ingest", "vectorize"), required=True)
    parser.add_argument("--catalog", default="workspace")
    parser.add_argument("--schema", default="default")
    parser.add_argument("--lakebase-endpoint", default=os.getenv("LAKEBASE_ENDPOINT"))
    parser.add_argument("--pipeline-api-url", default=os.getenv("TRIPWISE_PIPELINE_API_URL"))
    parser.add_argument("--pipeline-oauth-client-id", default=os.getenv("TRIPWISE_PIPELINE_OAUTH_CLIENT_ID"))
    parser.add_argument("--pipeline-oauth-secret-scope", default=os.getenv("TRIPWISE_PIPELINE_OAUTH_SECRET_SCOPE"))
    parser.add_argument("--pipeline-oauth-secret-key", default=os.getenv("TRIPWISE_PIPELINE_OAUTH_SECRET_KEY"))
    return parser.parse_args()


def table_name(args: argparse.Namespace, name: str) -> str:
    return f"{args.catalog}.{args.schema}.{name}"


def ingest(spark: SparkSession, args: argparse.Namespace) -> None:
    contexts: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    for location in DEFAULT_DESTINATIONS:
        try:
            contexts.extend(collect_context(location))
        except Exception as error:
            warnings.append({"location": location, "message": str(error)})
    if not contexts:
        raise RuntimeError(f"No source contexts were collected: {warnings}")
    raw_rows = [{"ingested_location": d["location"], "source_id": d["document_id"], "source_type": d["source_type"], "payload_json": d["payload_json"], "content_hash": d["content_hash"]} for d in contexts]
    normalized_rows = contexts
    spark.createDataFrame(raw_rows).withColumn("ingested_at", current_timestamp()).write.mode("overwrite").format("delta").saveAsTable(table_name(args, "tripwise_raw_destination_context"))
    spark.createDataFrame(normalized_rows).withColumn("prepared_at", current_timestamp()).write.mode("overwrite").format("delta").saveAsTable(table_name(args, "tripwise_destination_context"))
    print(json.dumps({"documents": len(contexts), "warnings": warnings, "raw_table": table_name(args, "tripwise_raw_destination_context"), "normalized_table": table_name(args, "tripwise_destination_context")}))


def vectorize(spark: SparkSession, args: argparse.Namespace) -> None:
    required = (args.pipeline_api_url, args.pipeline_oauth_client_id, args.pipeline_oauth_secret_scope, args.pipeline_oauth_secret_key)
    if not all(required):
        raise ValueError("Pipeline App URL and OAuth secret reference are required for the vectorize stage.")
    records = [row.asDict(recursive=True) for row in spark.table(table_name(args, "tripwise_destination_context")).select("document_id", "location", "latitude", "longitude", "source_type", "headline", "narrative_text", "effective_at", "payload_json", "content_hash").collect()]
    documents = []
    for record in records:
        chunks = chunk_text(f"{record['headline']}\n\n{record['narrative_text']}")
        documents.append({
            "document": {**record, "payload": json.loads(record.pop("payload_json"))},
            "chunks": [{"text": chunk} for chunk in chunks],
        })
    client_secret = DBUtils(spark).secrets.get(args.pipeline_oauth_secret_scope, args.pipeline_oauth_secret_key)
    workspace_host = os.environ.get("DATABRICKS_HOST", "https://dbc-a2b59cb4-753d.cloud.databricks.com")
    token_response = requests.post(
        workspace_host.rstrip("/") + "/oidc/v1/token",
        data={"grant_type": "client_credentials", "scope": "all-apis"},
        auth=(args.pipeline_oauth_client_id, client_secret),
        timeout=20,
    )
    if not token_response.ok:
        detail = token_response.text.strip().replace("\n", " ")[:200]
        raise RuntimeError(f"Tripwise pipeline OAuth token request returned HTTP {token_response.status_code}: {detail}")
    headers = {"Authorization": f"Bearer {token_response.json()['access_token']}"}
    response = requests.post(
        args.pipeline_api_url.rstrip("/") + "/api/pipeline/context",
        headers=headers,
        json={"documents": documents},
        timeout=90,
    )
    if not response.ok:
        detail = response.text.strip().replace("\n", " ")[:300]
        raise RuntimeError(f"Tripwise Lakebase writer returned HTTP {response.status_code}: {detail}")
    result = response.json()
    print(json.dumps({**result, "embedding_runtime": "Databricks App process", "write_method": "psycopg2 via Databricks App", "spark_jdbc": False}))


def main() -> None:
    args = arguments()
    spark = SparkSession.builder.getOrCreate()
    if args.stage == "ingest": ingest(spark, args)
    else: vectorize(spark, args)


if __name__ == "__main__":
    main()
