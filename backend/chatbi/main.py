"""FastAPI application entry point; local development remains loopback-only."""

import json
import logging
import os
import time
import uuid
from collections import deque
from datetime import UTC, datetime
from threading import Lock

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from .access_control import require_dataset_scope, resolve_mock_identity
from .database import SessionFactory, check_database
from .llm_provider import DeepSeekIntentProvider
from .models import TurnFeedback
from .query_schemas import (
    CreateSessionRequest,
    QueryDebug,
    SessionResponse,
    TurnRequest,
    TurnResponse,
)
from .query_service import (
    DATASET_ID,
    answer_question,
    failed_response,
    get_debug_query,
    sessions,
)
from .saas_catalog import ACTIVE_SAAS_CATALOG
from .saas_catalog import DATASET_ID as SAAS_DATASET_ID
from .saas_query_service import answer_saas_question
from .semantic_catalog import ACTIVE_CATALOG

PUBLIC_DEMO = os.getenv("CHATBI_PUBLIC_DEMO", "false").lower() == "true"
app = FastAPI(
    title="ChatBI API",
    version="0.1.0",
    description="Mock-only ChatBI engineering skeleton",
    docs_url=None if PUBLIC_DEMO else "/docs",
    redoc_url=None if PUBLIC_DEMO else "/redoc",
    openapi_url=None if PUBLIC_DEMO else "/openapi.json",
)
cors_origins = [
    origin.strip()
    for origin in os.getenv("CHATBI_CORS_ORIGINS", "http://127.0.0.1:5173").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Request-ID", "X-Mock-User"],
)
logger = logging.getLogger("chatbi.request")
debug_query_owners: dict[str, str] = {}


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: str = Field(pattern="^(positive|negative)$")
    category: str


FEEDBACK_CATEGORIES = {
    "positive": frozenset({"looks_good"}),
    "negative": frozenset(
        {"understanding", "metric_definition", "filter", "result", "chart", "other"}
    ),
}
TURN_OWNERS: dict[str, tuple[str, str]] = {}
_PUBLIC_REQUEST_TIMESTAMPS: deque[float] = deque()
_PUBLIC_REQUEST_LOCK = Lock()


def _enforce_public_request_budget() -> None:
    """Bound anonymous session, query, and feedback writes per process/minute."""
    if os.getenv("CHATBI_PUBLIC_DEMO", "false").lower() != "true":
        return
    try:
        limit = int(os.getenv("CHATBI_PUBLIC_REQUESTS_PER_MINUTE", "60"))
    except ValueError:
        limit = 60
    limit = max(1, min(limit, 1000))
    now = time.monotonic()
    with _PUBLIC_REQUEST_LOCK:
        while _PUBLIC_REQUEST_TIMESTAMPS and _PUBLIC_REQUEST_TIMESTAMPS[0] <= now - 60:
            _PUBLIC_REQUEST_TIMESTAMPS.popleft()
        if len(_PUBLIC_REQUEST_TIMESTAMPS) >= limit:
            retry_after = max(1, int(60 - (now - _PUBLIC_REQUEST_TIMESTAMPS[0])))
            raise HTTPException(
                status_code=429,
                detail="The public demo is busy. Please retry shortly.",
                headers={"Retry-After": str(retry_after)},
            )
        _PUBLIC_REQUEST_TIMESTAMPS.append(now)


def _configured_intent_provider() -> DeepSeekIntentProvider | None:
    """Enable hosted parsing only through an explicit backend environment setting."""
    if os.getenv("CHATBI_PUBLIC_DEMO", "false").lower() == "true":
        return None
    if os.getenv("CHATBI_LLM_PROVIDER", "disabled").lower() != "deepseek":
        return None
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return None
    return DeepSeekIntentProvider(
        api_key,
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )


@app.middleware("http")
async def request_trace(request: Request, call_next):  # type: ignore[no-untyped-def]
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        logger.info(
            json.dumps(
                {
                    "event": "http_request",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )


@app.get("/api/v1/health/live", tags=["health"])
def live() -> dict[str, str]:
    return {"status": "ok", "service": "chatbi-api"}


@app.get(
    "/api/v1/health/ready",
    tags=["health"],
    response_model=None,
    responses={503: {"description": "Database or Mock datasets unavailable"}},
)
def ready() -> dict[str, str] | JSONResponse:
    if not check_database():
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "dependency": "database_or_mock_data"},
        )
    return {"status": "ready", "dependency": "database_and_mock_data"}


@app.post("/api/v1/sessions", response_model=SessionResponse, tags=["sessions"])
def create_session(payload: CreateSessionRequest, request: Request) -> SessionResponse:
    _enforce_public_request_budget()
    identity = resolve_mock_identity(request)
    require_dataset_scope(identity, payload.dataset_id)
    snapshot = ACTIVE_CATALOG if payload.dataset_id == DATASET_ID else ACTIVE_SAAS_CATALOG
    session = sessions.create(payload.dataset_id, identity.user_id)
    return SessionResponse(
        session_id=session.session_id,
        dataset_id=payload.dataset_id,
        dataset_version=snapshot.dataset_version,
        semantic_catalog_id=session.semantic_catalog_id,
        semantic_catalog_version=session.semantic_catalog_version,
        request_id=request.state.request_id,
    )


@app.post(
    "/api/v1/sessions/{session_id}/turns",
    response_model=TurnResponse,
    tags=["sessions"],
)
def submit_turn(session_id: str, payload: TurnRequest, request: Request) -> TurnResponse:
    _enforce_public_request_budget()
    identity = resolve_mock_identity(request)
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    if session.owner_user_id != identity.user_id:
        raise HTTPException(status_code=404, detail="Session not found.")
    require_dataset_scope(identity, session.dataset_id)
    snapshot = ACTIVE_CATALOG if session.dataset_id == DATASET_ID else ACTIVE_SAAS_CATALOG
    if (
        session.semantic_catalog_id != snapshot.catalog.catalog_id
        or session.semantic_catalog_version != snapshot.catalog.version
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "The semantic catalog changed for this session. Create a new session "
                "and restate your question."
            ),
        )
    try:
        if session.dataset_id == SAAS_DATASET_ID:
            result = answer_saas_question(
                question=payload.question,
                request_id=request.state.request_id,
                intent_provider=_configured_intent_provider(),
            )
        else:
            result = answer_question(
                question=payload.question,
                request_id=request.state.request_id,
                session=session,
                clarifies_turn_id=payload.clarifies_turn_id,
                intent_provider=_configured_intent_provider(),
            )
        if result.debug_ref:
            debug_query_owners[result.debug_ref] = identity.user_id
            if len(debug_query_owners) > 500:
                debug_query_owners.pop(next(iter(debug_query_owners)))
        if session.turn_statuses is None:
            session.turn_statuses = {}
        session.turn_statuses[result.turn_id] = result.status
        TURN_OWNERS[result.turn_id] = (session.session_id, identity.user_id)
        if len(TURN_OWNERS) > 2000:
            TURN_OWNERS.pop(next(iter(TURN_OWNERS)))
        return result
    except SQLAlchemyError as error:
        original_error = getattr(error, "orig", error)
        sqlstate = getattr(original_error, "sqlstate", None)
        diagnostic = getattr(getattr(original_error, "diag", None), "message_primary", None)
        error_log = {
            "event": "query_execution_failed",
            "request_id": request.state.request_id,
            "error_type": type(error).__name__,
            "sqlstate": sqlstate,
        }
        if os.getenv("CHATBI_PUBLIC_DEMO", "false").lower() != "true":
            error_log["database_message"] = diagnostic
        logger.error(json.dumps(error_log, sort_keys=True))
        return failed_response(request.state.request_id)


@app.get("/api/v1/debug/queries/{query_id}", response_model=QueryDebug, tags=["debug"])
def get_query_debug(query_id: str, request: Request) -> QueryDebug:
    identity = resolve_mock_identity(request)
    if os.getenv("CHATBI_PUBLIC_DEMO", "false").lower() == "true":
        raise HTTPException(status_code=404, detail="Debug view is disabled.")
    if os.getenv("CHATBI_DEBUG_ENABLED", "false").lower() != "true":
        raise HTTPException(status_code=404, detail="Debug view is disabled.")
    if not identity.can_view_debug or debug_query_owners.get(query_id) != identity.user_id:
        raise HTTPException(status_code=404, detail="Debug query not found.")
    debug = get_debug_query(query_id)
    if debug is None:
        raise HTTPException(status_code=404, detail="Debug query not found.")
    return debug


@app.post("/api/v1/sessions/{session_id}/turns/{turn_id}/feedback", tags=["feedback"])
def submit_feedback(
    session_id: str, turn_id: str, payload: FeedbackRequest, request: Request
) -> dict[str, str]:
    _enforce_public_request_budget()
    identity = resolve_mock_identity(request)
    if not identity.can_submit_feedback:
        raise HTTPException(status_code=403, detail="This Mock identity cannot submit feedback.")
    session = sessions.get(session_id)
    if session is None or session.owner_user_id != identity.user_id:
        raise HTTPException(status_code=404, detail="Turn not found.")
    require_dataset_scope(identity, session.dataset_id)
    if TURN_OWNERS.get(turn_id) != (session_id, identity.user_id):
        raise HTTPException(status_code=404, detail="Turn not found.")
    if not session.turn_statuses or session.turn_statuses.get(turn_id) != "completed":
        raise HTTPException(
            status_code=409, detail="Feedback is available only for completed answers."
        )
    if payload.category not in FEEDBACK_CATEGORIES[payload.rating]:
        raise HTTPException(status_code=422, detail="Feedback category does not match its rating.")
    snapshot = ACTIVE_CATALOG if session.dataset_id == DATASET_ID else ACTIVE_SAAS_CATALOG
    with SessionFactory.begin() as db:
        existing = db.scalar(
            select(TurnFeedback).where(
                TurnFeedback.dataset_id == session.dataset_id,
                TurnFeedback.session_id == session_id,
                TurnFeedback.turn_id == turn_id,
                TurnFeedback.mock_user_id == identity.user_id,
            )
        )
        if existing is None:
            existing = TurnFeedback(
                feedback_id=str(uuid.uuid4()),
                dataset_id=session.dataset_id,
                session_id=session_id,
                turn_id=turn_id,
                mock_user_id=identity.user_id,
                dataset_version=snapshot.dataset_version,
                semantic_catalog_id=snapshot.catalog.catalog_id,
                semantic_catalog_version=snapshot.catalog.version,
            )
            db.add(existing)
        existing.rating = payload.rating
        existing.category = payload.category
        existing.submitted_at = datetime.now(UTC).isoformat()
    return {"status": "saved"}


@app.get("/api/v1/feedback/summary", tags=["feedback"])
def feedback_summary(request: Request) -> dict[str, object]:
    identity = resolve_mock_identity(request)
    if not identity.can_view_feedback_summary:
        raise HTTPException(status_code=403, detail="Feedback summary is admin-only.")
    with SessionFactory() as db:
        rows = db.execute(
            select(
                TurnFeedback.dataset_id, TurnFeedback.rating, TurnFeedback.category, func.count()
            )
            .where(TurnFeedback.dataset_id.in_(identity.dataset_ids))
            .group_by(TurnFeedback.dataset_id, TurnFeedback.rating, TurnFeedback.category)
            .order_by(TurnFeedback.rating, TurnFeedback.category)
        ).all()
    return {
        "total": sum(row[3] for row in rows),
        "counts": [
            {"dataset_id": dataset_id, "rating": rating, "category": category, "count": count}
            for dataset_id, rating, category, count in rows
        ],
    }
