from __future__ import annotations

import os
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

import psycopg2
from databricks.sdk import WorkspaceClient
from psycopg2.extras import RealDictCursor

ACTIVITY_TABLE = "weather_agent_ops.mcp_tool_activity"


class LakebaseError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _workspace_client() -> WorkspaceClient:
    return WorkspaceClient()


@contextmanager
def lakebase_connection():
    connection = None
    required = ("PGHOST", "PGDATABASE", "PGUSER", "LAKEBASE_ENDPOINT")
    if any(not os.getenv(key) for key in required):
        raise LakebaseError("Lakebase is not configured for this dashboard.")
    try:
        token = (
            _workspace_client()
            .postgres.generate_database_credential(endpoint=os.environ["LAKEBASE_ENDPOINT"])
            .token
        )
        connection = psycopg2.connect(
            host=os.environ["PGHOST"],
            dbname=os.environ["PGDATABASE"],
            user=os.environ["PGUSER"],
            password=token,
            port=os.getenv("PGPORT", "5432"),
            sslmode="require",
            connect_timeout=15,
        )
        yield connection
        connection.commit()
    except Exception as error:
        if connection:
            connection.rollback()
        raise LakebaseError(
            "The dashboard cannot read MCP activity yet. Confirm its Lakebase grants."
        ) from error
    finally:
        if connection:
            connection.close()


class DashboardRepository:
    def overview(self) -> dict[str, Any]:
        with lakebase_connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT
                      COUNT(*) AS total_calls,
                      COUNT(*) FILTER (WHERE outcome = 'error') AS failures,
                      COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '1 hour') AS last_hour_calls
                    FROM {ACTIVITY_TABLE}
                    """
                )
                overview = dict(cursor.fetchone())
                cursor.execute(
                    f"""
                    SELECT tool_name, location, requested_date, forecast_days, outcome, summary, created_at
                    FROM {ACTIVITY_TABLE}
                    ORDER BY created_at DESC
                    LIMIT 50
                    """
                )
                activity = []
                for row in cursor.fetchall():
                    record = dict(row)
                    record["created_at"] = record["created_at"].isoformat()
                    record["requested_date"] = (
                        record["requested_date"].isoformat() if record["requested_date"] else None
                    )
                    activity.append(record)
                return {
                    "overview": {key: int(value) for key, value in overview.items()},
                    "activity": activity,
                }
