from __future__ import annotations

import json

import mcp_app
from fastapi.testclient import TestClient

MCP_VERSION = "2025-06-18"
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def _sse_json(response):
    data_line = next(line for line in response.text.splitlines() if line.startswith("data: "))
    return json.loads(data_line.removeprefix("data: "))


def test_fastmcp3_handshake_discovery_and_tool_call(monkeypatch):
    monkeypatch.setattr(mcp_app.activity, "initialize_schema", lambda: None)
    monkeypatch.setattr(mcp_app.activity, "log", lambda **_kwargs: None)
    monkeypatch.setattr(
        mcp_app.weather,
        "get_current_weather",
        lambda location: {
            "location": location,
            "temperature_c": 21,
            "condition": "Clear sky",
        },
    )
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": MCP_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "weather-test", "version": "1"},
        },
    }

    with TestClient(mcp_app.app) as client:
        handshake = client.post("/mcp", headers=MCP_HEADERS, json=initialize)
        assert handshake.status_code == 200
        assert _sse_json(handshake)["result"]["serverInfo"]["version"] == "3.4.7"

        session_headers = {
            **MCP_HEADERS,
            "Mcp-Session-Id": handshake.headers["mcp-session-id"],
            "Mcp-Protocol-Version": MCP_VERSION,
        }
        assert (
            client.post(
                "/mcp",
                headers=session_headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            ).status_code
            == 202
        )

        discovery = client.post(
            "/mcp",
            headers=session_headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        call = client.post(
            "/mcp",
            headers=session_headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "get_current_weather",
                    "arguments": {"location": "Paris"},
                },
            },
        )

    assert discovery.status_code == 200
    assert {tool["name"] for tool in _sse_json(discovery)["result"]["tools"]} == {
        "get_current_weather",
        "get_weather_forecast",
        "get_travel_recommendation",
    }
    result = _sse_json(call)["result"]
    assert call.status_code == 200
    assert result["isError"] is False
    assert result["structuredContent"]["location"] == "Paris"
