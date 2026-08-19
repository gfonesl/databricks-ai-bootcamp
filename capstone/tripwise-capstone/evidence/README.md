# Tripwise evidence index

Only evidence captured from a real Databricks workspace may be added here. Do not create simulated screenshots, illustrative replacements, or links to files that are not committed.

The existing [validation record](validation.md) is a text record of a historical workspace run. New screenshots should use the names below and must be reviewed for secrets and personal identifiers before commit.

| File name | Required proof | Capture requirements |
| --- | --- | --- |
| `tripwise-app.png` | Deployed Tripwise App showing a real trip, destination forecast, itinerary, and generated packing list. | Include the browser application only; crop workspace/user identifiers and exclude tokens, request headers, or private URLs. |
| `lakeflow-job.png` | Lakeflow Job run with both ingest and vectorize tasks successful. | Show task names, run status, and execution time; hide workspace identifiers and secret values. |
| `lakebase.png` | Lakebase query or explorer showing Tripwise schema objects and non-sensitive aggregate counts. | Use aggregate/count evidence only; do not expose user notes, document payloads, credentials, or connection strings. |
| `agent-bricks.png` | Agent Bricks configuration or successful interaction using the Tripwise MCP connection. | Show the connection/tool result and six-tool integration without OAuth material, private prompts, or user data. |

Before adding any image:

1. Verify the capture came from the deployed code revision being documented.
2. Confirm every visible claim can be reproduced from the workspace.
3. Redact personal names, application URLs, workspace IDs, tokens, secret-scope values, and database endpoints.
4. Update `validation.md` with the date, commit revision, commands, and observed result.
5. Add the Markdown link only after the image exists in this directory.

Absence of a listed screenshot means that evidence has not yet been published; it must not be represented by a placeholder.
