# Tripwise validation record

## Local hardening validation — 2026-08-14

- Capstone tests against FastMCP 3.4.7: 28 passed, including authenticated MCP handshake/discovery, role enforcement, readiness, fail-fast startup, client/server payload limits, stable source IDs, partial-ingest failure, rollback, and transactional replacement behavior.
- Complete Python portfolio: 49 tests passed across the capstone, Day 2, Day 3 MCP server, and Day 3 dashboard. Both MCP servers were exercised against FastMCP 3.4.7.
- Ruff lint and format checks: passed for all Python source and tests.
- Day 1: typecheck, ESLint, Prettier check, production build, and two Playwright smoke tests passed.
- `npm audit`: zero known vulnerabilities in the locked Day 1 dependency graph.
- `pip-audit`: no known vulnerabilities in the four Python runtime lockfiles or development lockfile. The PyTorch CPU wheel is hosted outside PyPI and was reported as not auditable by `pip-audit`.

The checks above are local evidence. Deployment, OAuth forwarding, App ACLs, and workspace integration were not re-run as part of this change.

## Historical workspace validation — 2026-08-10

## Deployment and data

- App `tripwise-capstone`: `RUNNING`.
- Lakebase database: `databricks_postgres`, schema: `tripwise`.
- Vectorization task: successful; 6 documents received, 6 documents embedded, 6 chunks written.
- Lakebase verification: 6 knowledge documents, 6 embeddings, cosine HNSW index present.

## MCP

- Authenticated Streamable HTTP handshake: successful.
- MCP tools discovered: 6.
- Search operation: successful.
- Write operation: `create_trip` created trip 1, `Chicago weather-aware validation trip`.

## Quality checks

- `python -m pytest tests -q -p no:cacheprovider`: 8 passed.
- `databricks bundle validate --strict --profile BOOTCAMP`: passed.

## Agent Bricks platform limitation

`Tripwise Travel Agent` exists with `tripwise_mcp_connection` attached. The workspace presently blocks the service's `qwen3-embedding-0-6b` capability (`MODEL_DISABLED`), preventing example creation and a complete managed Agent Bricks response. This does not affect the App, Lakebase, pipeline, or authenticated MCP tool validation.
