from __future__ import annotations

import json

import app as tripwise_app
import pytest
from fastapi.testclient import TestClient
from lakebase import LakebaseError

OWNER = "owner@example.com"
AUTOMATION = "automation-service-principal"
MCP_VERSION = "2025-06-18"


@pytest.fixture(autouse=True)
def configured_identity(monkeypatch):
    monkeypatch.setenv("TRIPWISE_AUTH_MODE", "enforce")
    monkeypatch.setenv("TRIPWISE_OWNER_SUBJECTS", OWNER)
    monkeypatch.setenv("TRIPWISE_AUTOMATION_SUBJECTS", AUTOMATION)
    monkeypatch.setenv("TRIPWISE_SKIP_SCHEMA_INIT", "1")


def _sse_json(response):
    data_line = next(line for line in response.text.splitlines() if line.startswith("data: "))
    return json.loads(data_line.removeprefix("data: "))


def test_owner_routes_require_the_owner_identity(monkeypatch):
    monkeypatch.setattr(tripwise_app.repository, "list_trips", lambda: [])

    with TestClient(tripwise_app.app) as client:
        assert client.get("/").status_code == 401
        assert client.get("/", headers={"X-Forwarded-User": AUTOMATION}).status_code == 403

        response = client.get("/api/trips", headers={"X-Forwarded-User": OWNER})

    assert response.status_code == 200
    assert response.json()["trips"] == []


def test_pipeline_route_requires_the_automation_identity():
    with TestClient(tripwise_app.app) as client:
        assert client.post("/api/pipeline/context", json={}).status_code == 401
        assert (
            client.post(
                "/api/pipeline/context",
                headers={"X-Forwarded-User": OWNER},
                json={},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/pipeline/context",
                headers={"X-Forwarded-User": AUTOMATION},
                json={},
            ).status_code
            == 422
        )
        oversized = client.post(
            "/api/pipeline/context",
            headers={
                "X-Forwarded-User": AUTOMATION,
                "Content-Type": "application/json",
            },
            content=b" " * 250_001,
        )
        assert oversized.status_code == 413


def test_health_and_readiness_have_distinct_semantics(monkeypatch):
    monkeypatch.setattr(tripwise_app.repository, "ping", lambda: None)

    with TestClient(tripwise_app.app) as client:
        liveness = client.get("/healthz")
        readiness = client.get("/readyz")

        assert liveness.status_code == 200
        assert readiness.status_code == 200
        assert liveness.headers["x-content-type-options"] == "nosniff"
        assert "default-src 'self'" in liveness.headers["content-security-policy"]

        def unavailable():
            raise LakebaseError("Lakebase unavailable")

        monkeypatch.setattr(tripwise_app.repository, "ping", unavailable)
        assert client.get("/readyz").status_code == 503
        assert client.get("/healthz").status_code == 200


def test_schema_initialization_failure_stops_startup(monkeypatch):
    monkeypatch.delenv("TRIPWISE_SKIP_SCHEMA_INIT")

    def fail_schema():
        raise LakebaseError("schema unavailable")

    monkeypatch.setattr(tripwise_app.repository, "initialize_schema", fail_schema)
    with pytest.raises(BaseExceptionGroup) as captured:
        with TestClient(tripwise_app.app):
            pass
    assert any(
        isinstance(error, LakebaseError) and str(error) == "schema unavailable"
        for error in captured.value.exceptions
    )


def test_authenticated_mcp_handshake_and_six_tool_discovery():
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": MCP_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "tripwise-test", "version": "1"},
        },
    }
    headers = {
        "X-Forwarded-User": AUTOMATION,
        "Accept": "application/json, text/event-stream",
    }

    with TestClient(tripwise_app.app) as client:
        assert client.post("/mcp", json=initialize).status_code == 401
        assert (
            client.post(
                "/mcp",
                headers={**headers, "X-Forwarded-User": OWNER},
                json=initialize,
            ).status_code
            == 403
        )

        handshake = client.post("/mcp", headers=headers, json=initialize)
        assert handshake.status_code == 200
        assert _sse_json(handshake)["result"]["serverInfo"]["version"] == "3.4.7"

        session_headers = {
            **headers,
            "Mcp-Session-Id": handshake.headers["mcp-session-id"],
            "Mcp-Protocol-Version": MCP_VERSION,
        }
        initialized = client.post(
            "/mcp",
            headers=session_headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        assert initialized.status_code == 202

        discovery = client.post(
            "/mcp",
            headers=session_headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )

    assert discovery.status_code == 200
    tool_names = {tool["name"] for tool in _sse_json(discovery)["result"]["tools"]}
    assert tool_names == {
        "search_destination_context",
        "get_trip_context",
        "create_trip",
        "add_itinerary_item",
        "reschedule_itinerary_item",
        "build_packing_list",
    }
