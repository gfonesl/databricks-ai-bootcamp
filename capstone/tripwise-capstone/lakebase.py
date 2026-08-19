from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, datetime
from functools import lru_cache
from typing import Any, Iterable

import psycopg2
from config import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, SCHEMA
from databricks.sdk import WorkspaceClient
from embedding import vector_literal
from psycopg2.extras import Json, RealDictCursor, execute_values
from travel_sources import DestinationContext


class LakebaseError(RuntimeError):
    """The Tripwise persistence layer is unavailable."""


def _settings() -> dict[str, str]:
    required = ("PGHOST", "PGDATABASE", "PGUSER", "LAKEBASE_ENDPOINT")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise LakebaseError("Lakebase is not configured for Tripwise.")
    return {
        "host": os.environ["PGHOST"],
        "dbname": os.environ["PGDATABASE"],
        "user": os.environ["PGUSER"],
        "port": os.getenv("PGPORT", "5432"),
        "sslmode": "require",
        "connect_timeout": "15",
    }


@lru_cache(maxsize=1)
def _workspace_client() -> WorkspaceClient:
    return WorkspaceClient()


def _credential() -> str:
    try:
        return (
            _workspace_client()
            .postgres.generate_database_credential(endpoint=os.environ["LAKEBASE_ENDPOINT"])
            .token
        )
    except Exception as error:
        raise LakebaseError("Unable to obtain a temporary Lakebase credential.") from error


@contextmanager
def lakebase_connection():
    connection = None
    try:
        connection = psycopg2.connect(password=_credential(), **_settings())
        yield connection
        connection.commit()
    except psycopg2.Error as error:
        if connection:
            connection.rollback()
        raise LakebaseError(
            "Lakebase operation failed. Check the App resource and permissions."
        ) from error
    except Exception:
        if connection:
            connection.rollback()
        raise
    finally:
        if connection:
            connection.close()


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, (datetime, date)) else value


class TripwiseRepository:
    """Single persistence boundary for the App, MCP tools, and batch loader."""

    def ping(self) -> None:
        with lakebase_connection() as connection, connection.cursor() as cursor:
            cursor.execute(f"SELECT 1 FROM {SCHEMA}.trips LIMIT 1")

    def initialize_schema(self) -> None:
        with lakebase_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {SCHEMA}.users (
                      user_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                      display_name TEXT NOT NULL UNIQUE,
                      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    CREATE TABLE IF NOT EXISTS {SCHEMA}.trips (
                      trip_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                      user_id BIGINT NOT NULL REFERENCES {SCHEMA}.users(user_id),
                      title TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 3 AND 160),
                      start_date DATE NOT NULL,
                      end_date DATE NOT NULL CHECK (end_date >= start_date),
                      interests TEXT[] NOT NULL DEFAULT '{{}}',
                      notes TEXT,
                      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    CREATE TABLE IF NOT EXISTS {SCHEMA}.destinations (
                      destination_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                      trip_id BIGINT NOT NULL REFERENCES {SCHEMA}.trips(trip_id) ON DELETE CASCADE,
                      location TEXT NOT NULL,
                      latitude DOUBLE PRECISION,
                      longitude DOUBLE PRECISION,
                      arrival_date DATE,
                      departure_date DATE,
                      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                      UNIQUE(trip_id, location)
                    );
                    CREATE TABLE IF NOT EXISTS {SCHEMA}.activities (
                      activity_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                      destination_id BIGINT REFERENCES {SCHEMA}.destinations(destination_id) ON DELETE CASCADE,
                      title TEXT NOT NULL,
                      description TEXT,
                      is_outdoor BOOLEAN NOT NULL DEFAULT TRUE,
                      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    CREATE TABLE IF NOT EXISTS {SCHEMA}.itinerary_items (
                      itinerary_item_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                      trip_id BIGINT NOT NULL REFERENCES {SCHEMA}.trips(trip_id) ON DELETE CASCADE,
                      destination_id BIGINT REFERENCES {SCHEMA}.destinations(destination_id) ON DELETE SET NULL,
                      activity_id BIGINT REFERENCES {SCHEMA}.activities(activity_id) ON DELETE SET NULL,
                      scheduled_date DATE NOT NULL,
                      start_time TIME,
                      title TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 2 AND 160),
                      notes TEXT,
                      is_outdoor BOOLEAN NOT NULL DEFAULT TRUE,
                      status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned','completed','cancelled')),
                      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    CREATE TABLE IF NOT EXISTS {SCHEMA}.weather_snapshots (
                      weather_snapshot_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                      destination_id BIGINT NOT NULL REFERENCES {SCHEMA}.destinations(destination_id) ON DELETE CASCADE,
                      forecast_date DATE NOT NULL,
                      condition TEXT NOT NULL,
                      weather_code INTEGER,
                      temperature_min DOUBLE PRECISION,
                      temperature_max DOUBLE PRECISION,
                      precipitation_probability_max DOUBLE PRECISION,
                      wind_speed_max DOUBLE PRECISION,
                      uv_index_max DOUBLE PRECISION,
                      risk_level TEXT NOT NULL CHECK (risk_level IN ('low','moderate','high')),
                      source_payload JSONB NOT NULL,
                      fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                      UNIQUE(destination_id, forecast_date)
                    );
                    CREATE TABLE IF NOT EXISTS {SCHEMA}.packing_items (
                      packing_item_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                      trip_id BIGINT NOT NULL REFERENCES {SCHEMA}.trips(trip_id) ON DELETE CASCADE,
                      item_text TEXT NOT NULL,
                      reason TEXT NOT NULL,
                      is_packed BOOLEAN NOT NULL DEFAULT FALSE,
                      generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                      UNIQUE(trip_id, item_text)
                    );
                    CREATE TABLE IF NOT EXISTS {SCHEMA}.knowledge_documents (
                      document_id TEXT PRIMARY KEY,
                      location TEXT NOT NULL,
                      latitude DOUBLE PRECISION,
                      longitude DOUBLE PRECISION,
                      source_type TEXT NOT NULL CHECK (source_type IN ('weather_forecast','destination_summary')),
                      headline TEXT NOT NULL,
                      narrative_text TEXT NOT NULL,
                      effective_at DATE,
                      payload JSONB NOT NULL,
                      content_hash TEXT NOT NULL,
                      embedded_content_hash TEXT,
                      embedded_model_name TEXT,
                      embedded_at TIMESTAMPTZ,
                      synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    CREATE TABLE IF NOT EXISTS {SCHEMA}.knowledge_embeddings (
                      embedding_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                      document_id TEXT NOT NULL REFERENCES {SCHEMA}.knowledge_documents(document_id) ON DELETE CASCADE,
                      chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
                      chunk_text TEXT NOT NULL,
                      embedding vector({EMBEDDING_DIMENSIONS}) NOT NULL,
                      model_name TEXT NOT NULL,
                      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                      UNIQUE(document_id, chunk_index)
                    );
                """)
                for statement in (
                    f"CREATE INDEX IF NOT EXISTS idx_tripwise_trips_user_dates ON {SCHEMA}.trips(user_id, start_date DESC)",
                    f"CREATE INDEX IF NOT EXISTS idx_tripwise_destinations_trip ON {SCHEMA}.destinations(trip_id)",
                    f"CREATE INDEX IF NOT EXISTS idx_tripwise_itinerary_date ON {SCHEMA}.itinerary_items(trip_id, scheduled_date, start_time)",
                    f"CREATE INDEX IF NOT EXISTS idx_tripwise_weather_destination_date ON {SCHEMA}.weather_snapshots(destination_id, forecast_date)",
                    f"CREATE INDEX IF NOT EXISTS idx_tripwise_documents_location ON {SCHEMA}.knowledge_documents(location, source_type, effective_at DESC)",
                    f"CREATE INDEX IF NOT EXISTS idx_tripwise_embeddings_hnsw ON {SCHEMA}.knowledge_embeddings USING hnsw (embedding vector_cosine_ops)",
                ):
                    cursor.execute(statement)

    def _row(self, cursor) -> dict[str, Any] | None:
        row = cursor.fetchone()
        return {key: _iso(value) for key, value in dict(row).items()} if row else None

    def list_trips(self) -> list[dict[str, Any]]:
        with (
            lakebase_connection() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(f"""SELECT t.trip_id,t.title,t.start_date,t.end_date,t.interests,t.notes,t.updated_at,u.display_name,
              count(DISTINCT d.destination_id) AS destination_count,count(DISTINCT i.itinerary_item_id) AS itinerary_count
              FROM {SCHEMA}.trips t JOIN {SCHEMA}.users u ON u.user_id=t.user_id
              LEFT JOIN {SCHEMA}.destinations d ON d.trip_id=t.trip_id LEFT JOIN {SCHEMA}.itinerary_items i ON i.trip_id=t.trip_id
              GROUP BY t.trip_id,u.display_name ORDER BY t.start_date DESC""")
            return [
                {key: _iso(value) for key, value in dict(row).items()} for row in cursor.fetchall()
            ]

    def create_trip(
        self,
        display_name: str,
        title: str,
        start_date: str,
        end_date: str,
        interests: list[str] | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        with (
            lakebase_connection() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                f"INSERT INTO {SCHEMA}.users(display_name) VALUES (%s) ON CONFLICT(display_name) DO UPDATE SET display_name=EXCLUDED.display_name RETURNING user_id",
                (display_name.strip(),),
            )
            user_id = cursor.fetchone()["user_id"]
            cursor.execute(
                f"""INSERT INTO {SCHEMA}.trips(user_id,title,start_date,end_date,interests,notes)
              VALUES (%s,%s,%s::date,%s::date,%s,%s) RETURNING trip_id,title,start_date,end_date,interests,notes,created_at""",
                (user_id, title.strip(), start_date, end_date, interests or [], notes),
            )
            return self._row(cursor) or {}

    def add_destination(
        self,
        trip_id: int,
        location: str,
        latitude: float | None = None,
        longitude: float | None = None,
        arrival_date: str | None = None,
        departure_date: str | None = None,
    ) -> dict[str, Any]:
        with (
            lakebase_connection() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                f"""INSERT INTO {SCHEMA}.destinations(trip_id,location,latitude,longitude,arrival_date,departure_date)
              VALUES(%s,%s,%s,%s,%s::date,%s::date) RETURNING *""",
                (trip_id, location.strip(), latitude, longitude, arrival_date, departure_date),
            )
            return self._row(cursor) or {}

    def add_itinerary_item(
        self,
        trip_id: int,
        title: str,
        scheduled_date: str,
        destination_id: int | None = None,
        start_time: str | None = None,
        notes: str | None = None,
        is_outdoor: bool = True,
    ) -> dict[str, Any]:
        with (
            lakebase_connection() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                f"SELECT start_date,end_date FROM {SCHEMA}.trips WHERE trip_id=%s", (trip_id,)
            )
            trip = cursor.fetchone()
            if not trip:
                raise ValueError("trip_id does not reference an existing trip.")
            if not trip["start_date"] <= date.fromisoformat(scheduled_date) <= trip["end_date"]:
                raise ValueError("scheduled_date must fall within the trip dates.")
            if destination_id:
                cursor.execute(
                    f"SELECT 1 FROM {SCHEMA}.destinations WHERE destination_id=%s AND trip_id=%s",
                    (destination_id, trip_id),
                )
                if not cursor.fetchone():
                    raise ValueError("destination_id must belong to this trip.")
            cursor.execute(
                f"""INSERT INTO {SCHEMA}.itinerary_items(trip_id,destination_id,scheduled_date,start_time,title,notes,is_outdoor)
              VALUES(%s,%s,%s::date,%s::time,%s,%s,%s) RETURNING *""",
                (
                    trip_id,
                    destination_id,
                    scheduled_date,
                    start_time,
                    title.strip(),
                    notes,
                    is_outdoor,
                ),
            )
            return self._row(cursor) or {}

    def reschedule_item(
        self, itinerary_item_id: int, scheduled_date: str, start_time: str | None = None
    ) -> dict[str, Any]:
        with (
            lakebase_connection() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                f"""UPDATE {SCHEMA}.itinerary_items i SET scheduled_date=%s::date,start_time=COALESCE(%s::time,i.start_time),updated_at=NOW()
              FROM {SCHEMA}.trips t WHERE i.itinerary_item_id=%s AND t.trip_id=i.trip_id AND %s::date BETWEEN t.start_date AND t.end_date RETURNING i.*""",
                (scheduled_date, start_time, itinerary_item_id, scheduled_date),
            )
            row = self._row(cursor)
            if not row:
                raise ValueError("Itinerary item was not found or the date falls outside its trip.")
            return row

    def delete_item(self, itinerary_item_id: int) -> None:
        with lakebase_connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"DELETE FROM {SCHEMA}.itinerary_items WHERE itinerary_item_id=%s",
                (itinerary_item_id,),
            )
            if cursor.rowcount == 0:
                raise ValueError("Itinerary item was not found.")

    def save_weather(self, destination_id: int, forecasts: Iterable[dict[str, Any]]) -> int:
        rows = list(forecasts)
        if not rows:
            raise ValueError("At least one weather forecast is required.")
        with lakebase_connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"SELECT 1 FROM {SCHEMA}.destinations WHERE destination_id=%s FOR UPDATE",
                (destination_id,),
            )
            if not cursor.fetchone():
                raise ValueError("destination_id does not reference an existing destination.")
            cursor.execute(
                f"DELETE FROM {SCHEMA}.weather_snapshots WHERE destination_id=%s",
                (destination_id,),
            )
            execute_values(
                cursor,
                f"""INSERT INTO {SCHEMA}.weather_snapshots(destination_id,forecast_date,condition,weather_code,temperature_min,temperature_max,precipitation_probability_max,wind_speed_max,uv_index_max,risk_level,source_payload)
              VALUES %s""",
                [
                    (
                        destination_id,
                        row["date"],
                        row["condition"],
                        row["weather_code"],
                        row["temperature_min"],
                        row["temperature_max"],
                        row["precipitation_probability_max"],
                        row["wind_speed_max"],
                        row["uv_index_max"],
                        row["risk_level"],
                        Json(row),
                    )
                    for row in rows
                ],
            )
        return len(rows)

    def get_trip(self, trip_id: int) -> dict[str, Any] | None:
        with (
            lakebase_connection() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                f"SELECT t.*,u.display_name FROM {SCHEMA}.trips t JOIN {SCHEMA}.users u ON u.user_id=t.user_id WHERE t.trip_id=%s",
                (trip_id,),
            )
            trip = self._row(cursor)
            if not trip:
                return None
            cursor.execute(
                f"SELECT d.*, COALESCE(json_agg(w ORDER BY w.forecast_date) FILTER (WHERE w.weather_snapshot_id IS NOT NULL),'[]') AS weather FROM {SCHEMA}.destinations d LEFT JOIN {SCHEMA}.weather_snapshots w ON w.destination_id=d.destination_id WHERE d.trip_id=%s GROUP BY d.destination_id ORDER BY d.created_at",
                (trip_id,),
            )
            trip["destinations"] = [
                {key: _iso(value) for key, value in dict(row).items()} for row in cursor.fetchall()
            ]
            cursor.execute(
                f"SELECT * FROM {SCHEMA}.itinerary_items WHERE trip_id=%s ORDER BY scheduled_date,start_time NULLS LAST,itinerary_item_id",
                (trip_id,),
            )
            trip["itinerary"] = [
                {key: _iso(value) for key, value in dict(row).items()} for row in cursor.fetchall()
            ]
            cursor.execute(
                f"SELECT * FROM {SCHEMA}.packing_items WHERE trip_id=%s ORDER BY item_text",
                (trip_id,),
            )
            trip["packing_items"] = [
                {key: _iso(value) for key, value in dict(row).items()} for row in cursor.fetchall()
            ]
            return trip

    def upsert_documents(self, documents: Iterable[DestinationContext]) -> int:
        rows = list(documents)
        if not rows:
            return 0
        with lakebase_connection() as connection, connection.cursor() as cursor:
            execute_values(
                cursor,
                f"""INSERT INTO {SCHEMA}.knowledge_documents(document_id,location,latitude,longitude,source_type,headline,narrative_text,effective_at,payload,content_hash)
              VALUES %s ON CONFLICT(document_id) DO UPDATE SET location=EXCLUDED.location,latitude=EXCLUDED.latitude,longitude=EXCLUDED.longitude,source_type=EXCLUDED.source_type,headline=EXCLUDED.headline,narrative_text=EXCLUDED.narrative_text,effective_at=EXCLUDED.effective_at,payload=EXCLUDED.payload,content_hash=EXCLUDED.content_hash,synced_at=NOW() WHERE {SCHEMA}.knowledge_documents.content_hash IS DISTINCT FROM EXCLUDED.content_hash""",
                [
                    (
                        d.source_id,
                        d.location,
                        d.latitude,
                        d.longitude,
                        d.source_type,
                        d.headline,
                        d.narrative_text,
                        d.effective_at,
                        Json(d.payload),
                        d.content_hash,
                    )
                    for d in rows
                ],
            )
        return len(rows)

    def delete_superseded_weather_documents(self, documents: Iterable[DestinationContext]) -> int:
        weather_documents = [
            document for document in documents if document.source_type == "weather_forecast"
        ]
        if not weather_documents:
            return 0
        locations = sorted({document.location for document in weather_documents})
        active_ids = sorted({document.source_id for document in weather_documents})
        with lakebase_connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""DELETE FROM {SCHEMA}.knowledge_documents
                    WHERE source_type='weather_forecast'
                      AND location = ANY(%s)
                      AND NOT (document_id = ANY(%s))""",
                (locations, active_ids),
            )
            return cursor.rowcount

    def documents_needing_embeddings(self, limit: int = 200) -> list[dict[str, Any]]:
        with (
            lakebase_connection() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                f"SELECT document_id,headline,narrative_text,content_hash FROM {SCHEMA}.knowledge_documents WHERE embedded_content_hash IS DISTINCT FROM content_hash OR embedded_model_name IS DISTINCT FROM %s ORDER BY synced_at LIMIT %s",
                (EMBEDDING_MODEL, limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    def replace_embeddings(
        self, document_id: str, content_hash: str, chunks_vectors: Iterable[tuple[str, list[float]]]
    ) -> int:
        rows = list(chunks_vectors)
        with lakebase_connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"DELETE FROM {SCHEMA}.knowledge_embeddings WHERE document_id=%s", (document_id,)
            )
            if rows:
                execute_values(
                    cursor,
                    f"INSERT INTO {SCHEMA}.knowledge_embeddings(document_id,chunk_index,chunk_text,embedding,model_name) VALUES %s",
                    [
                        (document_id, index, chunk, vector_literal(vector), EMBEDDING_MODEL)
                        for index, (chunk, vector) in enumerate(rows)
                    ],
                    template="(%s,%s,%s,%s::vector,%s)",
                )
            cursor.execute(
                f"UPDATE {SCHEMA}.knowledge_documents SET embedded_content_hash=%s,embedded_model_name=%s,embedded_at=NOW() WHERE document_id=%s",
                (content_hash, EMBEDDING_MODEL, document_id),
            )
        return len(rows)

    def replace_embeddings_if_needed(
        self, document_id: str, content_hash: str, chunks_vectors: Iterable[tuple[str, list[float]]]
    ) -> int:
        """Replace a document's vectors only when source content or model changed."""
        rows = list(chunks_vectors)
        with (
            lakebase_connection() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                f"SELECT content_hash, embedded_content_hash, embedded_model_name FROM {SCHEMA}.knowledge_documents WHERE document_id=%s",
                (document_id,),
            )
            document = self._row(cursor)
            if not document:
                raise LakebaseError("Prepared context document was not found after upsert.")
            if document["content_hash"] != content_hash:
                raise LakebaseError(
                    "Prepared context content hash does not match the stored document."
                )
            if (
                document["embedded_content_hash"] == content_hash
                and document["embedded_model_name"] == EMBEDDING_MODEL
            ):
                return 0
            cursor.execute(
                f"DELETE FROM {SCHEMA}.knowledge_embeddings WHERE document_id=%s", (document_id,)
            )
            if rows:
                execute_values(
                    cursor,
                    f"INSERT INTO {SCHEMA}.knowledge_embeddings(document_id,chunk_index,chunk_text,embedding,model_name) VALUES %s",
                    [
                        (document_id, index, chunk, vector_literal(vector), EMBEDDING_MODEL)
                        for index, (chunk, vector) in enumerate(rows)
                    ],
                    template="(%s,%s,%s,%s::vector,%s)",
                )
            cursor.execute(
                f"UPDATE {SCHEMA}.knowledge_documents SET embedded_content_hash=%s,embedded_model_name=%s,embedded_at=NOW() WHERE document_id=%s",
                (content_hash, EMBEDDING_MODEL, document_id),
            )
        return len(rows)

    def search_context(self, query_vector: list[float], top_k: int) -> list[dict[str, Any]]:
        vector = vector_literal(query_vector)
        with (
            lakebase_connection() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                f"""SELECT d.location,d.source_type,d.headline,d.effective_at,e.chunk_text,1-(e.embedding <=> %s::vector) AS similarity FROM {SCHEMA}.knowledge_embeddings e JOIN {SCHEMA}.knowledge_documents d ON d.document_id=e.document_id ORDER BY e.embedding <=> %s::vector LIMIT %s""",
                (vector, vector, top_k),
            )
            return [
                {
                    **{key: _iso(value) for key, value in dict(row).items()},
                    "similarity": float(row["similarity"]),
                }
                for row in cursor.fetchall()
            ]

    def build_packing_list(self, trip_id: int) -> list[dict[str, Any]]:
        with (
            lakebase_connection() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                f"SELECT 1 FROM {SCHEMA}.trips WHERE trip_id=%s FOR UPDATE",
                (trip_id,),
            )
            if not cursor.fetchone():
                raise ValueError("trip_id does not reference an existing trip.")
            cursor.execute(
                f"""SELECT max(precipitation_probability_max) AS precipitation_probability_max,min(temperature_min) AS temperature_min,max(temperature_max) AS temperature_max,max(wind_speed_max) AS wind_speed_max FROM {SCHEMA}.weather_snapshots w JOIN {SCHEMA}.destinations d ON d.destination_id=w.destination_id WHERE d.trip_id=%s""",
                (trip_id,),
            )
            forecast = dict(cursor.fetchone())
            if all(value is None for value in forecast.values()):
                raise ValueError("Sync current weather before building a packing list.")
            from travel_sources import packing_recommendations

            items = packing_recommendations(forecast)
            cursor.execute(f"DELETE FROM {SCHEMA}.packing_items WHERE trip_id=%s", (trip_id,))
            if items:
                execute_values(
                    cursor,
                    f"INSERT INTO {SCHEMA}.packing_items(trip_id,item_text,reason) VALUES %s ON CONFLICT(trip_id,item_text) DO UPDATE SET reason=EXCLUDED.reason,generated_at=NOW()",
                    [(trip_id, item["item"], item["reason"]) for item in items],
                )
            return items
