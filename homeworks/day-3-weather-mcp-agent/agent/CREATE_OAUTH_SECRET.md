# Manual security step — never share the secret

Create or choose a dedicated Databricks service principal for the MCP client, then record only placeholders in this repository:

- Service principal: `<WEATHER_MCP_AGENT_CLIENT_NAME>`
- Application ID: `<OAUTH_CLIENT_ID>`
- Secret scope: `<SECRET_SCOPE>`
- Secret key: `<SECRET_KEY>`

In the Databricks Account Console, create an OAuth client secret for that service principal. Copy the value directly into the Databricks secret scope under the chosen key. The value is shown only once: do **not** paste it into Codex, Git, a notebook, a SQL statement, screenshot, shell history, or homework ZIP.

Use the same non-secret placeholders in `create_uc_connection.sql`. The following setup steps are then: create the Unity Catalog HTTP connection, grant it to the Agent Bricks service principal, attach it as the MCP tool, and run the three demonstrations.
