"""Read-only verification of the deployed Tripwise Lakebase schema.

This helper obtains a short-lived OAuth credential at runtime and never prints it.
"""
from __future__ import annotations

import os

import psycopg2
from databricks.sdk import WorkspaceClient


ENDPOINT = "projects/databricks-ai-bootcamp/branches/production/endpoints/primary"


def main() -> None:
    workspace = WorkspaceClient(profile=os.getenv("DATABRICKS_CONFIG_PROFILE", "BOOTCAMP"))
    endpoint = workspace.postgres.get_endpoint(name=ENDPOINT)
    credential = workspace.postgres.generate_database_credential(endpoint=ENDPOINT).token
    user = workspace.current_user.me().user_name
    with psycopg2.connect(host=endpoint.status.hosts.host, dbname="databricks_postgres", user=user, password=credential, sslmode="require") as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s ORDER BY table_name", ("tripwise",))
            print("Tripwise tables:", ", ".join(row[0] for row in cursor.fetchall()))
            cursor.execute("SELECT count(*) FROM tripwise.knowledge_documents")
            documents = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM tripwise.knowledge_embeddings")
            embeddings = cursor.fetchone()[0]
            cursor.execute("SELECT indexname FROM pg_indexes WHERE schemaname=%s AND tablename=%s AND indexdef ILIKE %s", ("tripwise", "knowledge_embeddings", "%hnsw%"))
            hnsw = bool(cursor.fetchone())
            print(f"Knowledge documents: {documents}; embeddings: {embeddings}; cosine HNSW index: {hnsw}")


if __name__ == "__main__":
    main()
