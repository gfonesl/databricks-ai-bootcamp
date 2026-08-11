from __future__ import annotations

import os
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterable

import psycopg2
from databricks.sdk import WorkspaceClient
from psycopg2.extras import Json, RealDictCursor, execute_values

from config import (
    DOCUMENTS_TABLE,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    EMBEDDINGS_TABLE,
)
from embedding import vector_literal
from weather_client import WeatherDocument


class LakebaseError(RuntimeError):
    """Raised when Lakebase cannot be reached or initialized."""


def _connection_settings() -> dict[str, str]:
    required = ("PGHOST", "PGDATABASE", "PGUSER", "LAKEBASE_ENDPOINT")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise LakebaseError(
            "Lakebase connection is not configured. Missing environment variables: "
            + ", ".join(missing)
        )
    return {
        "host": os.environ["PGHOST"],
        "dbname": os.environ["PGDATABASE"],
        "user": os.environ["PGUSER"],
        "port": os.getenv("PGPORT", "5432"),
        "sslmode": os.getenv("PGSSLMODE", "require"),
        "connect_timeout": os.getenv("PGCONNECT_TIMEOUT", "15"),
    }


@lru_cache(maxsize=1)
def _workspace_client() -> WorkspaceClient:
    return WorkspaceClient()


def _database_credential() -> str:
    """Get a short-lived Postgres OAuth token for the running App identity."""
    try:
        credential = _workspace_client().postgres.generate_database_credential(
            endpoint=os.environ["LAKEBASE_ENDPOINT"]
        )
        return credential.token
    except Exception as error:
        raise LakebaseError("Unable to obtain a temporary Lakebase credential.") from error


@contextmanager
def lakebase_connection():
    connection = None
    try:
        connection = psycopg2.connect(password=_database_credential(), **_connection_settings())
        yield connection
        connection.commit()
    except psycopg2.Error as error:
        if connection:
            connection.rollback()
        raise LakebaseError("Lakebase operation failed. Check the App resource and permissions.") from error
    finally:
        if connection:
            connection.close()


class WeatherRepository:
    """The only persistence boundary for the Weather Intelligence application."""

    def initialize_schema(self) -> None:
        with lakebase_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("CREATE SCHEMA IF NOT EXISTS weather_intelligence")
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {DOCUMENTS_TABLE} (
                        id TEXT PRIMARY KEY,
                        location TEXT NOT NULL,
                        latitude DOUBLE PRECISION NOT NULL,
                        longitude DOUBLE PRECISION NOT NULL,
                        source_type TEXT NOT NULL CHECK (source_type IN ('alert', 'forecast')),
                        headline TEXT NOT NULL,
                        narrative_text TEXT NOT NULL,
                        issued_at TIMESTAMPTZ,
                        effective_at TIMESTAMPTZ,
                        payload JSONB NOT NULL,
                        content_hash TEXT NOT NULL,
                        synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        embedded_content_hash TEXT,
                        embedded_model_name TEXT,
                        embedded_at TIMESTAMPTZ
                    )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {EMBEDDINGS_TABLE} (
                        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                        document_id TEXT NOT NULL REFERENCES {DOCUMENTS_TABLE}(id) ON DELETE CASCADE,
                        chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
                        chunk_text TEXT NOT NULL,
                        embedding vector({EMBEDDING_DIMENSIONS}) NOT NULL,
                        model_name TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        UNIQUE (document_id, chunk_index)
                    )
                    """
                )
                cursor.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_weather_documents_location "
                    f"ON {DOCUMENTS_TABLE} (location, source_type, effective_at DESC)"
                )
                cursor.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_weather_documents_embedding_state "
                    f"ON {DOCUMENTS_TABLE} (content_hash, embedded_content_hash)"
                )
                cursor.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_weather_embeddings_document "
                    f"ON {EMBEDDINGS_TABLE} (document_id, chunk_index)"
                )
                cursor.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_weather_embeddings_hnsw "
                    f"ON {EMBEDDINGS_TABLE} USING hnsw (embedding vector_cosine_ops)"
                )

    def upsert_documents(self, documents: Iterable[WeatherDocument]) -> int:
        records = list(documents)
        if not records:
            return 0
        values = [
            (
                document.id,
                document.location,
                document.latitude,
                document.longitude,
                document.source_type,
                document.headline,
                document.narrative_text,
                document.issued_at,
                document.effective_at,
                Json(document.payload),
                document.content_hash,
            )
            for document in records
        ]
        with lakebase_connection() as connection:
            with connection.cursor() as cursor:
                execute_values(
                    cursor,
                    f"""
                    INSERT INTO {DOCUMENTS_TABLE} (
                        id, location, latitude, longitude, source_type, headline, narrative_text,
                        issued_at, effective_at, payload, content_hash
                    ) VALUES %s
                    ON CONFLICT (id) DO UPDATE SET
                        location = EXCLUDED.location,
                        latitude = EXCLUDED.latitude,
                        longitude = EXCLUDED.longitude,
                        source_type = EXCLUDED.source_type,
                        headline = EXCLUDED.headline,
                        narrative_text = EXCLUDED.narrative_text,
                        issued_at = EXCLUDED.issued_at,
                        effective_at = EXCLUDED.effective_at,
                        payload = EXCLUDED.payload,
                        content_hash = EXCLUDED.content_hash,
                        synced_at = NOW()
                    WHERE {DOCUMENTS_TABLE}.content_hash IS DISTINCT FROM EXCLUDED.content_hash
                    """,
                    values,
                )
        return len(records)

    def documents_needing_embeddings(self, limit: int) -> list[dict[str, Any]]:
        with lakebase_connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT id, location, headline, narrative_text, content_hash
                    FROM {DOCUMENTS_TABLE}
                    WHERE embedded_content_hash IS DISTINCT FROM content_hash
                       OR embedded_model_name IS DISTINCT FROM %s
                    ORDER BY synced_at ASC
                    LIMIT %s
                    """,
                    (EMBEDDING_MODEL, limit),
                )
                return [dict(row) for row in cursor.fetchall()]

    def replace_embeddings(
        self,
        document_id: str,
        content_hash: str,
        chunks_and_vectors: Iterable[tuple[str, list[float]]],
    ) -> int:
        rows = list(chunks_and_vectors)
        with lakebase_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"DELETE FROM {EMBEDDINGS_TABLE} WHERE document_id = %s", (document_id,))
                if rows:
                    execute_values(
                        cursor,
                        f"""
                        INSERT INTO {EMBEDDINGS_TABLE} (
                            document_id, chunk_index, chunk_text, embedding, model_name
                        ) VALUES %s
                        """,
                        [
                            (document_id, index, chunk, vector_literal(vector), EMBEDDING_MODEL)
                            for index, (chunk, vector) in enumerate(rows)
                        ],
                        template="(%s, %s, %s, %s::vector, %s)",
                    )
                cursor.execute(
                    f"""
                    UPDATE {DOCUMENTS_TABLE}
                    SET embedded_content_hash = %s,
                        embedded_model_name = %s,
                        embedded_at = NOW()
                    WHERE id = %s
                    """,
                    (content_hash, EMBEDDING_MODEL, document_id),
                )
        return len(rows)

    def semantic_search(self, query_vector: list[float], top_k: int) -> list[dict[str, Any]]:
        vector = vector_literal(query_vector)
        with lakebase_connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        document.location,
                        document.source_type,
                        document.headline,
                        document.effective_at,
                        embedding.chunk_text,
                        1 - (embedding.embedding <=> %s::vector) AS similarity
                    FROM {EMBEDDINGS_TABLE} AS embedding
                    INNER JOIN {DOCUMENTS_TABLE} AS document ON document.id = embedding.document_id
                    ORDER BY embedding.embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (vector, vector, top_k),
                )
                results = []
                for row in cursor.fetchall():
                    result = dict(row)
                    result["similarity"] = float(result["similarity"])
                    if result["effective_at"]:
                        result["effective_at"] = result["effective_at"].isoformat()
                    results.append(result)
                return results