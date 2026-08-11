# Tripwise Capstone Submission

## Project links

- Databricks App: https://tripwise-capstone-7474646632333305.aws.databricksapps.com
- Supervisor Agent: **Tripwise Travel Agent** (`mas-2c74d8ec-endpoint`)
- Source repository: https://github.com/gfonesl/databricks-ai-bootcamp

## Delivered components

- A FastAPI Databricks App with a browser frontend, REST API and FastMCP Streamable HTTP endpoint at `/mcp`.
- A Lakeflow Job, **Tripwise daily destination context**, scheduled for 07:00 `America/Sao_Paulo` and deliberately left paused until operational approval.
- Spark ingestion of Open-Meteo and Wikimedia source material into `workspace.default.tripwise_raw_destination_context` and `workspace.default.tripwise_destination_context`.
- Lakebase operational tables in the dedicated `tripwise` schema, with `vector(384)` knowledge embeddings and a cosine HNSW index.
- A Unity Catalog OAuth M2M HTTP connection, `tripwise_mcp_connection`, attached to the Tripwise Travel Agent.

## Verification completed on 2026-08-10

- The App is `RUNNING` and its service principal owns the Lakebase schema.
- The successful vectorization task processed 6 source documents and wrote 6 embedding chunks through the App's `psycopg2` Lakebase repository; Spark JDBC is not used for these writes.
- The MCP handshake was validated with an authenticated temporary token. It created a session and discovered all 6 tools: `search_destination_context`, `get_trip_context`, `create_trip`, `add_itinerary_item`, `reschedule_itinerary_item`, and `build_packing_list`.
- An authenticated MCP call searched destination context and created the persisted **Chicago weather-aware validation trip** with `trip_id` 1.
- The local verification suite passed: **8 tests passed**. Bundle validation also passed.

## Agent Bricks note

The Supervisor Agent, UC connection and tool attachment were created successfully. This workspace currently returns `MODEL_DISABLED` for the Databricks-managed `qwen3-embedding-0-6b` capability when examples or a complete chat response are requested, so the three Agent Bricks examples cannot be saved and the managed agent response cannot be demonstrated until that workspace capability is enabled. The independently validated MCP server and its persistent read/write tools remain fully operational.

## Screenshot checklist

Before uploading, add these screenshots to the `evidence/` folder if the submission form requires visual proof:

1. The deployed Tripwise App with the persisted validation trip.
2. The Lakeflow Job run and Delta destination-context records.
3. The Lakebase `tripwise` tables, including knowledge documents and embeddings.
4. The Agent Bricks configuration and its MCP tool attachment. If the model capability is enabled, add a successful agent conversation as well.

## Reflection

The most challenging part was separating the repeatable Spark ingestion layer from the low-latency operational experience without compromising secure Lakebase writes. Delta holds reproducible source data for the daily pipeline, while Lakebase holds the relational travel state and pgvector retrieval needed by the App and MCP tools. Building the MCP interface demonstrated that AI actions need validated inputs and durable, inspectable results rather than only generated text. Next, I would derive pipeline destinations from active trips and add an automated evaluation set for both retrieval relevance and itinerary actions.
