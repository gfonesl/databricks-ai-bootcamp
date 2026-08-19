# Weather Intelligence

A Flask Databricks App that turns National Weather Service (NWS) alerts and forecast narratives into searchable Lakebase PostgreSQL documents backed by pgvector.

## Architecture

```text
NWS alerts + forecast narratives
              |
       POST /weather/sync
              |
weather_intelligence.weather_documents
              |
 scripts/ingest_weather_embeddings.py
              |
weather_intelligence.weather_embeddings (vector(384), HNSW)
              |
      POST /weather/search
```

Nominatim resolves latitude and longitude for locations such as `Chicago, IL` and `Austin, TX`. All retrieved alerts and forecast narratives come from the NWS.

## Lakebase schema

At startup, the Databricks App creates its dedicated `weather_intelligence` schema:

- `weather_documents` stores normalized NWS provenance, location, source type (`alert` or `forecast`), text, timestamps, JSONB payload, and a `content_hash` used for idempotent upserts.
- `weather_embeddings` stores text chunks and `vector(384)` embeddings. Its `document_id` foreign key uses `ON DELETE CASCADE`.
- `idx_weather_embeddings_hnsw` provides cosine similarity search with `vector_cosine_ops`.

Before the first deployment, a database administrator must enable pgvector once:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

The App owns only its schema and does not perform database-level extension management. `databricks-sdk` generates temporary OAuth credentials for new psycopg2 connections; no database password is stored in the repository.

## Dependencies

Runtime dependencies are declared in `requirements.in` and compiled into a universal, hashed lockfile. Regenerate it on Windows or Unix with:

```bash
python scripts/compile_requirements.py
```

The generator resolves `torch` against the official CPU backend while resolving general dependencies from PyPI. It then emits the PyTorch CPU index for `pip --require-hashes` compatibility without changing the pinned package versions or accepted artifact hashes.

## API

Liveness:

```http
GET /healthz
```

Collect weather documents:

```http
POST /weather/sync
Content-Type: application/json

{
  "locations": ["Chicago, IL", "Austin, TX"],
  "limit": 50
}
```

The response reports per-location warnings without discarding successfully collected locations. A request accepts at most 50 documents.

Semantic search:

```http
POST /weather/search
Content-Type: application/json

{
  "query": "flash flood risk this weekend",
  "top_k": 5
}
```

`top_k` must be between 1 and 20. Results include location, source type, headline, retrieved passage, effective date, and similarity. Synchronize documents and generate embeddings before the first search.

## Chunking and embeddings

The ingestion script combines the headline and narrative, then creates 800-character windows with 100-character overlap while attempting to preserve word boundaries. Only new documents or documents whose content hash changed are processed; previous chunks are replaced transactionally.

The runtime is pinned to `sentence-transformers==5.7.0`, and `all-MiniLM-L6-v2` is loaded at immutable revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`.

```bash
python scripts/ingest_weather_embeddings.py --limit 100
```

Run the script on Databricks compute, or in an environment that can receive temporary Lakebase credentials. Use `.env.example` only as a variable-name reference and never store real secrets in it.

## Development and tests

Install the fully pinned runtime graph and run the isolated suite:

```bash
python -m pip install --require-hashes -r requirements.txt
python -m pytest tests -q
```

Tests use fake repositories and source clients, so they do not require Lakebase, NWS access, or an embedding-model download.

## Deployment

Supply your own non-secret Lakebase resource names:

```bash
databricks bundle validate --strict \
  --var postgres_branch=<LAKEBASE_BRANCH> \
  --var postgres_database=<LAKEBASE_DATABASE>
```

Deployment is intentionally separate from local CI and requires an authenticated Databricks workspace.

## Limitations

- NWS, Nominatim, and the first embedding-model download require external network access.
- Embedding generation is manually triggered; a scheduled job is the natural next operational step.
- The API performs retrieval, not LLM answer generation.
- Weather data can change or be temporarily unavailable and must not replace official safety guidance.

## Sources

- [National Weather Service API](https://www.weather.gov/documentation/services-web-api)
- [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/)
- [Sentence Transformers: all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
