# Homework 3 submission status

## Implemented artifacts

- FastMCP Streamable HTTP server: `mcp_server/`
- Weather adapter using Open-Meteo: `mcp_server/weather_adapter.py`
- Lakebase telemetry schema: `weather_agent_ops.mcp_tool_activity`
- Dashboard source: `dashboard/`
- Agent instructions, connection template and evaluation questions: `agent/`

## Deployment notes

- MCP App and Agent endpoint URLs are intentionally omitted from this public source repository.
- MCP endpoint path: `/mcp`
- Supervisor Agent: `Weather Forecast Agent`

## Evidence still required

- OAuth secret stored by the workspace owner; then UC connection and MCP tool attachment.
- Screenshots of the three Agent Bricks questions showing tool calls and final answers.
- Dashboard screenshot after an App slot becomes available. The workspace currently has its three-App limit occupied by Day 1, Day 2 and the MCP App; the dashboard is an optional stretch feature and its source/tests are complete.
