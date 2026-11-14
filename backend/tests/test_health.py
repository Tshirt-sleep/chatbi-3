import json
import logging
from types import SimpleNamespace

from backend.chatbi.main import live, ready, request_trace
from fastapi.responses import JSONResponse, Response
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool


def test_live_health_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc123def456")
    assert live() == {
        "status": "ok",
        "service": "chatbi-api",
        "version": "0.1.0",
        "build_id": "abc123def456",
    }

    request = SimpleNamespace(
        state=SimpleNamespace(),
        method="GET",
        url=SimpleNamespace(path="/api/v1/health/live"),
    )
    response = Response()

    async def call_next(_request):
        return response

    middleware_call = request_trace(request, call_next)
    try:
        middleware_call.send(None)
    except StopIteration as result:
        assert result.value is response
    else:
        raise AssertionError("request trace middleware unexpectedly suspended")

    assert request.state.request_id
    assert response.headers["x-request-id"] == request.state.request_id


def test_ready_health_endpoint_reports_seeded_database(monkeypatch) -> None:
    monkeypatch.setattr("backend.chatbi.main.check_database", lambda: True)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc123def456")
    assert ready() == {
        "status": "ready",
        "dependency": "database_and_mock_data",
        "service": "chatbi-api",
        "version": "0.1.0",
        "build_id": "abc123def456",
    }


def test_ready_health_endpoint_reports_unseeded_database(monkeypatch) -> None:
    monkeypatch.setattr("backend.chatbi.main.check_database", lambda: False)
    response = ready()
    assert isinstance(response, JSONResponse)
    assert response.status_code == 503
    assert json.loads(response.body) == {
        "status": "not_ready",
        "dependency": "database_or_mock_data",
        "service": "chatbi-api",
        "version": "0.1.0",
        "build_id": "unknown",
    }


def test_request_log_uses_route_template_and_release_metadata(monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO, logger="chatbi.request")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc123def456")
    session_id = "private-session-token"
    request = SimpleNamespace(
        state=SimpleNamespace(),
        method="POST",
        url=SimpleNamespace(path=f"/api/v1/sessions/{session_id}/turns"),
        scope={"route": SimpleNamespace(path="/api/v1/sessions/{session_id}/turns")},
    )
    response = Response()

    async def call_next(_request):
        return response

    middleware_call = request_trace(request, call_next)
    try:
        middleware_call.send(None)
    except StopIteration:
        pass
    else:
        raise AssertionError("request trace middleware unexpectedly suspended")

    record = next(
        record for record in caplog.records if '"event": "http_request"' in record.message
    )
    payload = json.loads(record.message)
    assert payload["route"] == "/api/v1/sessions/{session_id}/turns"
    assert payload["status_code"] == 200
    assert payload["duration_ms"] >= 0
    assert payload["build_id"] == "abc123def456"
    assert session_id not in record.message


def test_database_readiness_requires_migration_and_both_mock_datasets() -> None:
    from backend.chatbi import database

    incomplete_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with incomplete_engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT)"))

    monkeypatch_engine = database.engine
    database.engine = incomplete_engine
    try:
        assert database.check_database() is False
    finally:
        database.engine = monkeypatch_engine
        incomplete_engine.dispose()
