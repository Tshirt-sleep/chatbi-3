"""Fixed demo identities; public mode strips capabilities that imply administration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from types import MappingProxyType

from fastapi import HTTPException, Request

ECOMMERCE_DATASET_ID = "ecommerce_mock_v1"
SAAS_DATASET_ID = "saas_subscription_mock_v1"


@dataclass(frozen=True, slots=True)
class MockIdentity:
    user_id: str
    role: str
    dataset_ids: frozenset[str]
    can_view_debug: bool
    can_submit_feedback: bool
    can_view_feedback_summary: bool


MOCK_IDENTITIES = MappingProxyType(
    {
        "admin": MockIdentity(
            user_id="admin",
            role="admin",
            dataset_ids=frozenset({ECOMMERCE_DATASET_ID, SAAS_DATASET_ID}),
            can_view_debug=True,
            can_submit_feedback=True,
            can_view_feedback_summary=True,
        ),
        "analyst": MockIdentity(
            user_id="analyst",
            role="analyst",
            dataset_ids=frozenset({ECOMMERCE_DATASET_ID, SAAS_DATASET_ID}),
            can_view_debug=True,
            can_submit_feedback=True,
            can_view_feedback_summary=False,
        ),
        "viewer": MockIdentity(
            user_id="viewer",
            role="viewer",
            dataset_ids=frozenset({ECOMMERCE_DATASET_ID}),
            can_view_debug=False,
            can_submit_feedback=False,
            can_view_feedback_summary=False,
        ),
    }
)


def resolve_mock_identity(request: Request) -> MockIdentity:
    identity_id = (
        request.headers.get("X-Mock-User") or request.headers.get("x-mock-user", "")
    ).strip()
    identity = MOCK_IDENTITIES.get(identity_id)
    if identity is None:
        raise HTTPException(status_code=401, detail="A valid local Mock identity is required.")
    if os.getenv("CHATBI_PUBLIC_DEMO", "false").lower() == "true":
        # Publicly selectable roles are presentation-only. Never expose debug or
        # cross-user feedback aggregation as an administrative capability.
        return MockIdentity(
            user_id=identity.user_id,
            role=identity.role,
            dataset_ids=identity.dataset_ids,
            can_view_debug=False,
            can_submit_feedback=identity.can_submit_feedback,
            can_view_feedback_summary=False,
        )
    return identity


def require_dataset_scope(identity: MockIdentity, dataset_id: str) -> None:
    if dataset_id not in identity.dataset_ids:
        raise HTTPException(
            status_code=403, detail="This Mock identity cannot access that dataset."
        )
