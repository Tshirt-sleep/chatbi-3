from __future__ import annotations

from types import SimpleNamespace

import pytest
from backend.chatbi import main
from backend.chatbi.access_control import MOCK_IDENTITIES
from backend.chatbi.database import SessionFactory
from backend.chatbi.models import TurnFeedback
from backend.chatbi.query_schemas import CreateSessionRequest, TurnRequest
from backend.chatbi.query_service import sessions
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select


def request(user: str | None) -> SimpleNamespace:
    headers = {} if user is None else {"x-mock-user": user}
    return SimpleNamespace(state=SimpleNamespace(request_id="access-test"), headers=headers)


def test_mock_roles_are_fixed_and_scope_limited() -> None:
    assert MOCK_IDENTITIES["viewer"].dataset_ids == frozenset({"ecommerce_mock_v1"})
    with pytest.raises(HTTPException) as missing:
        main.create_session(CreateSessionRequest(), request(None))
    assert missing.value.status_code == 401
    with pytest.raises(HTTPException) as denied:
        main.create_session(
            CreateSessionRequest(dataset_id="saas_subscription_mock_v1"), request("viewer")
        )
    assert denied.value.status_code == 403


def test_sessions_turns_and_debug_are_owner_bound(monkeypatch) -> None:
    monkeypatch.setenv("CHATBI_DEBUG_ENABLED", "true")
    owner_request = request("analyst")
    response = main.create_session(CreateSessionRequest(), owner_request)
    session = sessions.get(response.session_id)
    assert session is not None and session.owner_user_id == "analyst"

    with pytest.raises(HTTPException) as cross_user:
        main.submit_turn(response.session_id, TurnRequest(question="昨天销售额"), request("admin"))
    assert cross_user.value.status_code == 404

    result = main.submit_turn(
        response.session_id, TurnRequest(question="未定义指标xxx"), owner_request
    )
    with pytest.raises(HTTPException) as debug_denied:
        main.get_query_debug(result.debug_ref or "", request("viewer"))
    assert debug_denied.value.status_code == 404


def test_feedback_is_private_idempotent_and_aggregated_without_text(monkeypatch) -> None:
    with SessionFactory.begin() as db:
        db.query(TurnFeedback).delete()

    owner_request = request("analyst")
    response = main.create_session(CreateSessionRequest(), owner_request)
    result = main.submit_turn(
        response.session_id, TurnRequest(question="昨天的销售额是多少？"), owner_request
    )
    session = sessions.get(response.session_id)
    assert session is not None
    assert session.turn_statuses and session.turn_statuses[result.turn_id] == "completed"

    payload = main.FeedbackRequest(rating="negative", category="result")
    assert main.submit_feedback(response.session_id, result.turn_id, payload, owner_request) == {
        "status": "saved"
    }
    assert main.submit_feedback(
        response.session_id,
        result.turn_id,
        main.FeedbackRequest(rating="positive", category="looks_good"),
        owner_request,
    ) == {"status": "saved"}

    with SessionFactory() as db:
        rows = db.scalars(select(TurnFeedback)).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.rating == "positive" and row.category == "looks_good"
    assert not ({"question", "answer", "sql", "result_values", "free_text"} & set(row.__dict__))
    assert main.feedback_summary(request("admin"))["total"] == 1
    assert main.feedback_summary(request("admin"))["counts"] == [
        {
            "dataset_id": "ecommerce_mock_v1",
            "rating": "positive",
            "category": "looks_good",
            "count": 1,
        }
    ]
    with pytest.raises(HTTPException) as denied:
        main.feedback_summary(owner_request)
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as invalid_category:
        main.submit_feedback(
            response.session_id,
            result.turn_id,
            main.FeedbackRequest(rating="positive", category="result"),
            owner_request,
        )
    assert invalid_category.value.status_code == 422


def test_feedback_rejects_unfinished_turn_and_body_self_assignment() -> None:
    request_analyst = request("analyst")
    response = main.create_session(CreateSessionRequest(), request_analyst)
    result = main.submit_turn(
        response.session_id,
        TurnRequest(question="销售额最高的前 10 个商品是哪些？"),
        request_analyst,
    )
    assert result.status == "clarification_required"
    with pytest.raises(HTTPException) as unfinished:
        main.submit_feedback(
            response.session_id,
            result.turn_id,
            main.FeedbackRequest(rating="negative", category="understanding"),
            request_analyst,
        )
    assert unfinished.value.status_code == 409
    with pytest.raises(ValidationError):
        main.FeedbackRequest.model_validate(
            {"rating": "positive", "category": "looks_good", "mock_user_id": "admin"}
        )
