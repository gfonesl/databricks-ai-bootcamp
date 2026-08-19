from __future__ import annotations

import os
from contextlib import contextmanager
from functools import lru_cache

import psycopg2
from config import ACTIVITY_TABLE, SCHEMA
from databricks.sdk import WorkspaceClient


class LakebaseError(RuntimeError):
    """Lakebase cannot be reached by the App identity."""


def _settings() -> dict[str, str]:
    required = ("PGHOST", "PGDATABASE", "PGUSER", "LAKEBASE_ENDPOINT")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise LakebaseError("Lakebase is not configured for this App.")
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


@contextmanager
def lakebase_connection():
    connection = None
    try:
        token = (
            _workspace_client()
            .postgres.generate_database_credential(endpoint=os.environ["LAKEBASE_ENDPOINT"])
            .token
        )
        connection = psycopg2.connect(password=token, **_settings())
        yield connection
        connection.commit()
    except Exception as error:
        if connection:
            connection.rollback()
        raise LakebaseError("Lakebase telemetry operation failed.") from error
    finally:
        if connection:
            connection.close()


class ActivityRepository:
    """Persistence boundary for non-sensitive MCP tool activity."""

    def initialize_schema(self) -> None:
        with lakebase_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {ACTIVITY_TABLE} (
                        activity_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                        tool_name TEXT NOT NULL,
                        location TEXT,
                        requested_date DATE,
                        forecast_days SMALLINT CHECK (forecast_days BETWEEN 1 AND 7),
                        outcome TEXT NOT NULL CHECK (outcome IN ('success', 'error')),
                        summary TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_mcp_activity_recent ON {ACTIVITY_TABLE} (created_at DESC)"
                )
                cursor.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_mcp_activity_tool_outcome ON {ACTIVITY_TABLE} (tool_name, outcome, created_at DESC)"
                )

    def log(
        self,
        *,
        tool_name: str,
        location: str | None,
        requested_date: str | None,
        forecast_days: int | None,
        outcome: str,
        summary: str,
    ) -> None:
        with lakebase_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO {ACTIVITY_TABLE} (tool_name, location, requested_date, forecast_days, outcome, summary)
                    VALUES (%s, %s, %s::date, %s, %s, %s)
                    """,
                    (tool_name, location, requested_date, forecast_days, outcome, summary[:500]),
                )
