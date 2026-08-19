from __future__ import annotations

import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from config import (
    APP_NAME,
    MAX_DESTINATIONS,
    MAX_PIPELINE_CHUNKS_PER_DOCUMENT,
    MAX_PIPELINE_DOCUMENTS,
    MAX_PIPELINE_REQUEST_BYTES,
    MAX_SEARCH_RESULTS,
)
from embedding import EmbeddingError, embed_texts
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastmcp import FastMCP
from identity import AuthorizationError, authorize, required_role, validate_auth_config
from lakebase import LakebaseError, TripwiseRepository
from pydantic import BaseModel, ConfigDict, Field, model_validator
from travel_sources import (
    DestinationContext,
    OpenMeteoWikimediaClient,
    TravelSourceError,
    content_hash,
)

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).parent
repository = TripwiseRepository()
sources = OpenMeteoWikimediaClient()


def _clean(value: str, name: str, minimum: int = 1, maximum: int = 500) -> str:
    if not isinstance(value, str) or not (minimum <= len(value.strip()) <= maximum):
        raise ValueError(f"{name} must contain between {minimum} and {maximum} characters.")
    return value.strip()


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, ValueError):
        return HTTPException(400, str(error))
    if isinstance(error, (LakebaseError, TravelSourceError, EmbeddingError)):
        LOGGER.exception("Tripwise operation failed")
        return HTTPException(503, str(error))
    LOGGER.exception("Unexpected Tripwise error")
    return HTTPException(500, "Tripwise could not complete the request.")


class TripRequest(BaseModel):
    display_name: str = Field(min_length=2, max_length=120)
    title: str = Field(min_length=3, max_length=160)
    start_date: date
    end_date: date
    interests: list[str] = Field(default_factory=list, max_length=12)
    notes: str | None = Field(default=None, max_length=1200)

    @model_validator(mode="after")
    def valid_range(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date.")
        return self


class DestinationRequest(BaseModel):
    location: str = Field(min_length=2, max_length=160)


class ItineraryRequest(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    scheduled_date: date
    destination_id: int | None = Field(default=None, gt=0)
    start_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    notes: str | None = Field(default=None, max_length=1200)
    is_outdoor: bool = True


class RescheduleRequest(BaseModel):
    scheduled_date: date
    start_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    top_k: int = Field(default=5, ge=1, le=MAX_SEARCH_RESULTS)


class PipelineDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=3, max_length=300)
    location: str = Field(min_length=2, max_length=160)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    source_type: Literal["weather_forecast", "destination_summary"]
    headline: str = Field(min_length=2, max_length=300)
    narrative_text: str = Field(min_length=2, max_length=30000)
    effective_at: str | None = Field(default=None, max_length=32)
    payload: dict[str, Any] = Field(default_factory=dict)
    content_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def valid_provenance(self):
        prefix = {
            "weather_forecast": "open-meteo:",
            "destination_summary": "wikimedia:",
        }[self.source_type]
        if not self.document_id.startswith(prefix):
            raise ValueError(f"document_id must use the {prefix} namespace.")
        expected_hash = content_hash(self.headline, self.narrative_text)
        if not hmac.compare_digest(self.content_hash.casefold(), expected_hash):
            raise ValueError("content_hash does not match the canonical document content.")
        return self


class PipelineChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=1200)


class PipelineContextItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: PipelineDocument
    chunks: list[PipelineChunk] = Field(min_length=1, max_length=MAX_PIPELINE_CHUNKS_PER_DOCUMENT)


class PipelineContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documents: list[PipelineContextItem] = Field(min_length=1, max_length=MAX_PIPELINE_DOCUMENTS)

    @model_validator(mode="after")
    def within_payload_limit(self):
        encoded = json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        if len(encoded) > MAX_PIPELINE_REQUEST_BYTES:
            raise ValueError(
                f"pipeline context must not exceed {MAX_PIPELINE_REQUEST_BYTES} bytes."
            )
        return self


@asynccontextmanager
async def app_lifespan(parent_app: FastAPI):
    # FastMCP's Streamable HTTP transport owns a task group that must be
    # started with the parent FastAPI application.  Without this composed
    # lifespan, authenticated MCP requests fail after deployment.
    async with mcp_asgi.lifespan(parent_app):
        validate_auth_config()
        if os.getenv("TRIPWISE_SKIP_SCHEMA_INIT") != "1":
            repository.initialize_schema()
            LOGGER.info("Tripwise schema initialized")
        yield


mcp = FastMCP(
    "Tripwise Travel MCP",
    instructions=(
        "Use the Tripwise tools to retrieve destination context and make persistent trip changes. "
        "Never claim a forecast or make an itinerary modification without first using a tool."
    ),
)


def mcp_search_destination_context(query: str, trip_id: int | None = None) -> dict[str, Any]:
    """Search relevant destination, attraction and weather context semantically.

    Args:
        query: A specific travel, weather or destination question.
        trip_id: Optional existing trip id to make the request easier to interpret.
    """
    try:
        _clean(query, "query", 2)
        results = repository.search_context(embed_texts([query.strip()])[0], 5)
        return {
            "query": query.strip(),
            "trip_id": trip_id,
            "results": results,
            "source": "Lakebase pgvector",
        }
    except Exception as error:
        return {"error": "context_search_failed", "message": str(error)}


def mcp_get_trip_context(trip_id: int) -> dict[str, Any]:
    """Return the persisted dates, destinations, weather and itinerary for a trip."""
    try:
        trip = repository.get_trip(trip_id)
        if not trip:
            return {"error": "trip_not_found", "message": "No trip exists with that trip_id."}
        return trip
    except Exception as error:
        return {"error": "trip_lookup_failed", "message": str(error)}


def mcp_create_trip(
    display_name: str,
    title: str,
    start_date: str,
    end_date: str,
    interests: list[str] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Create a persistent Tripwise trip. Dates must use YYYY-MM-DD."""
    try:
        request = TripRequest(
            display_name=display_name,
            title=title,
            start_date=start_date,
            end_date=end_date,
            interests=interests or [],
            notes=notes,
        )
        return repository.create_trip(
            request.display_name,
            request.title,
            request.start_date.isoformat(),
            request.end_date.isoformat(),
            request.interests,
            request.notes,
        )
    except Exception as error:
        return {"error": "trip_create_failed", "message": str(error)}


def mcp_add_itinerary_item(
    trip_id: int,
    title: str,
    scheduled_date: str,
    destination_id: int | None = None,
    start_time: str | None = None,
    notes: str | None = None,
    is_outdoor: bool = True,
) -> dict[str, Any]:
    """Add a persistent itinerary item to an existing trip."""
    try:
        request = ItineraryRequest(
            title=title,
            scheduled_date=scheduled_date,
            destination_id=destination_id,
            start_time=start_time,
            notes=notes,
            is_outdoor=is_outdoor,
        )
        return repository.add_itinerary_item(
            trip_id,
            request.title,
            request.scheduled_date.isoformat(),
            request.destination_id,
            request.start_time,
            request.notes,
            request.is_outdoor,
        )
    except Exception as error:
        return {"error": "itinerary_create_failed", "message": str(error)}


def mcp_reschedule_itinerary_item(
    itinerary_item_id: int, scheduled_date: str, start_time: str | None = None
) -> dict[str, Any]:
    """Move an existing itinerary item to another date inside its trip."""
    try:
        request = RescheduleRequest(scheduled_date=scheduled_date, start_time=start_time)
        return repository.reschedule_item(
            itinerary_item_id, request.scheduled_date.isoformat(), request.start_time
        )
    except Exception as error:
        return {"error": "itinerary_reschedule_failed", "message": str(error)}


def mcp_build_packing_list(trip_id: int) -> dict[str, Any]:
    """Build and persist a packing list using the current Tripwise weather snapshots."""
    try:
        return {
            "trip_id": trip_id,
            "items": repository.build_packing_list(trip_id),
            "source": "Lakebase weather snapshots",
        }
    except Exception as error:
        return {"error": "packing_list_failed", "message": str(error)}


mcp.tool(name="search_destination_context")(mcp_search_destination_context)
mcp.tool(name="get_trip_context")(mcp_get_trip_context)
mcp.tool(name="create_trip")(mcp_create_trip)
mcp.tool(name="add_itinerary_item")(mcp_add_itinerary_item)
mcp.tool(name="reschedule_itinerary_item")(mcp_reschedule_itinerary_item)
mcp.tool(name="build_packing_list")(mcp_build_packing_list)

# Let FastMCP own the canonical endpoint path. Mounting a root-path MCP app at
# ``/mcp`` makes Starlette redirect ``/mcp`` to ``/mcp/``; Agent Bricks starts
# at the former, so that redirect prevents tool registration.
mcp_asgi = mcp.http_app(path="/mcp")
app = FastAPI(title=APP_NAME, lifespan=app_lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.middleware("http")
async def secure_request_boundary(request: Request, call_next):
    """Normalize MCP requests, enforce caller roles, and emit safe audit metadata.

    Some clients begin at ``/mcp`` and subsequently send a session request to
    ``/mcp/``. Normalizing the latter before Starlette routes the request avoids
    a 307 redirect, which Agent Bricks intentionally does not follow for MCP.
    """
    started_at = perf_counter()
    if request.scope["path"] == "/mcp/":
        request.scope["path"] = "/mcp"
        request.scope["raw_path"] = b"/mcp"
    path = request.scope["path"]
    role = required_role(path)
    if path == "/api/pipeline/context":
        content_length = request.headers.get("content-length")
        try:
            declared_length = int(content_length) if content_length else 0
        except ValueError:
            return _finish_request(
                JSONResponse(
                    content={"detail": "Content-Length must be an integer."},
                    status_code=400,
                ),
                request,
                path,
                request.headers.get("x-forwarded-user", "missing"),
                role.value if role else "probe",
                started_at,
            )
        if declared_length > MAX_PIPELINE_REQUEST_BYTES:
            return _finish_request(
                JSONResponse(
                    content={"detail": "Pipeline context request is too large."},
                    status_code=413,
                ),
                request,
                path,
                request.headers.get("x-forwarded-user", "missing"),
                role.value if role else "probe",
                started_at,
            )

    try:
        actor = authorize(request.headers, role)
    except AuthorizationError as error:
        return _finish_request(
            JSONResponse(content={"detail": str(error)}, status_code=error.status_code),
            request,
            path,
            request.headers.get("x-forwarded-user", "missing"),
            role.value if role else "probe",
            started_at,
        )

    request.state.actor = actor
    response = await call_next(request)
    return _finish_request(
        response,
        request,
        path,
        actor.subject,
        actor.role.value,
        started_at,
    )


def _safe_audit_value(value: str, maximum: int = 160) -> str:
    sanitized = "".join(
        character if character.isalnum() or character in "-_.@:" else "_" for character in value
    )
    return sanitized[:maximum] or "unavailable"


def _finish_request(response, request, path, subject, role, started_at):
    elapsed_ms = (perf_counter() - started_at) * 1000
    LOGGER.info(
        "request_complete request_id=%s subject=%s role=%s method=%s path=%s status=%s duration_ms=%.1f",
        _safe_audit_value(request.headers.get("x-request-id", "unavailable")),
        _safe_audit_value(subject),
        _safe_audit_value(role),
        request.method,
        path,
        response.status_code,
        elapsed_ms,
    )
    return _secure_response(response)


def _secure_response(response):
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": APP_NAME, "mcp_path": "/mcp"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    try:
        repository.ping()
        return {"status": "ready", "service": APP_NAME, "lakebase": "available"}
    except LakebaseError as error:
        raise HTTPException(503, str(error)) from error


@app.get("/")
def home():
    return FileResponse(ROOT / "templates" / "index.html")


@app.get("/api/trips")
def list_trips():
    try:
        return {"trips": repository.list_trips(), "source": "Lakebase tripwise"}
    except Exception as error:
        raise _http_error(error)


@app.post("/api/trips", status_code=201)
def create_trip(request: TripRequest):
    try:
        return repository.create_trip(
            request.display_name,
            request.title,
            request.start_date.isoformat(),
            request.end_date.isoformat(),
            request.interests,
            request.notes,
        )
    except Exception as error:
        raise _http_error(error)


@app.get("/api/trips/{trip_id}")
def get_trip(trip_id: int):
    try:
        trip = repository.get_trip(trip_id)
        if not trip:
            raise HTTPException(404, "Trip not found.")
        return trip
    except HTTPException:
        raise
    except Exception as error:
        raise _http_error(error)


@app.post("/api/trips/{trip_id}/destinations", status_code=201)
def add_destination(trip_id: int, request: DestinationRequest):
    try:
        resolved = sources.resolve_location(request.location)
        row = repository.add_destination(
            trip_id,
            ", ".join(part for part in (resolved["name"], resolved.get("country")) if part),
            resolved["latitude"],
            resolved["longitude"],
        )
        return row
    except Exception as error:
        raise _http_error(error)


@app.post("/api/trips/{trip_id}/sync-weather")
def sync_weather(trip_id: int):
    try:
        trip = repository.get_trip(trip_id)
        if not trip:
            raise HTTPException(404, "Trip not found.")
        written = 0
        warnings = []
        for destination in trip["destinations"][:MAX_DESTINATIONS]:
            try:
                _, forecasts = sources.forecast(destination["location"])
                written += repository.save_weather(destination["destination_id"], forecasts)
            except (ValueError, TravelSourceError) as error:
                warnings.append({"location": destination["location"], "message": str(error)})
        return {"weather_snapshots_written": written, "warnings": warnings}
    except HTTPException:
        raise
    except Exception as error:
        raise _http_error(error)


@app.post("/api/trips/{trip_id}/itinerary", status_code=201)
def add_item(trip_id: int, request: ItineraryRequest):
    try:
        return repository.add_itinerary_item(
            trip_id,
            request.title,
            request.scheduled_date.isoformat(),
            request.destination_id,
            request.start_time,
            request.notes,
            request.is_outdoor,
        )
    except Exception as error:
        raise _http_error(error)


@app.patch("/api/itinerary-items/{itinerary_item_id}")
def reschedule_item(itinerary_item_id: int, request: RescheduleRequest):
    try:
        return repository.reschedule_item(
            itinerary_item_id, request.scheduled_date.isoformat(), request.start_time
        )
    except Exception as error:
        raise _http_error(error)


@app.delete("/api/itinerary-items/{itinerary_item_id}", status_code=204)
def delete_item(itinerary_item_id: int):
    try:
        repository.delete_item(itinerary_item_id)
    except Exception as error:
        raise _http_error(error)


@app.post("/api/trips/{trip_id}/packing-list")
def build_packing_list(trip_id: int):
    try:
        return {"trip_id": trip_id, "items": repository.build_packing_list(trip_id)}
    except Exception as error:
        raise _http_error(error)


@app.post("/api/search-context")
def search_context(request: SearchRequest):
    try:
        results = repository.search_context(embed_texts([request.query.strip()])[0], request.top_k)
        return {
            "query": request.query.strip(),
            "results": results,
            "source": "Lakebase pgvector; Open-Meteo + Wikimedia context",
        }
    except Exception as error:
        raise _http_error(error)


@app.post("/api/pipeline/context")
def persist_pipeline_context(request: PipelineContextRequest):
    """Persist serverless Spark output through the App's psycopg2 Lakebase layer."""
    try:
        documents = [
            DestinationContext(
                source_id=item.document.document_id,
                location=item.document.location,
                latitude=item.document.latitude,
                longitude=item.document.longitude,
                source_type=item.document.source_type,
                headline=item.document.headline,
                narrative_text=item.document.narrative_text,
                effective_at=item.document.effective_at,
                payload=item.document.payload,
                content_hash=item.document.content_hash,
            )
            for item in request.documents
        ]
        repository.upsert_documents(documents)
        repository.delete_superseded_weather_documents(documents)
        pending_document_ids = {
            candidate["document_id"]
            for candidate in repository.documents_needing_embeddings(limit=200)
        }
        items_to_embed = [
            item for item in request.documents if item.document.document_id in pending_document_ids
        ]
        chunk_texts = [chunk.text for item in items_to_embed for chunk in item.chunks]
        vectors = iter(embed_texts(chunk_texts)) if chunk_texts else iter(())
        chunks_written = sum(
            repository.replace_embeddings_if_needed(
                item.document.document_id,
                item.document.content_hash,
                [(chunk.text, next(vectors)) for chunk in item.chunks],
            )
            for item in items_to_embed
        )
        return {
            "documents_received": len(documents),
            "documents_embedded": len(items_to_embed),
            "chunks_written": chunks_written,
        }
    except Exception as error:
        raise _http_error(error)


# This fallback mount is intentionally last: the API and static routes above
# remain owned by FastAPI, while FastMCP receives its declared ``/mcp`` route
# without a trailing-slash redirect.
app.mount("/", mcp_asgi)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("DATABRICKS_APP_PORT", "8000")))
