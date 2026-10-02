"""
Step 18 tests — Checklist Completion API Router.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.analysis.checklist.schemas import ChecklistCompletionResponse
from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.core.exceptions import (
    RepositoryNotFoundError,
    ValidationError,
)
from app.main import app


def _make_user(username: str = "sathwik", uid: uuid.UUID | None = None) -> MagicMock:
    user = MagicMock()
    user.id = uid or uuid.uuid4()
    user.github_username = username
    user.github_user_id = 12345678
    user.encrypted_access_token = "enc-fake-tok"
    user.preferences = {}
    return user


def _noop_db():
    async def _gen():
        yield MagicMock()

    return _gen()


def _make_client(user: MagicMock | None = None) -> TestClient:
    overrides = {get_db: _noop_db}
    if user is not None:
        overrides[get_current_user] = lambda: user
    app.dependency_overrides = overrides
    return TestClient(app, raise_server_exceptions=False)


ANALYSIS_ID = uuid.uuid4()
ITEM_ID = uuid.uuid4()
SERVICE_PATH = "app.api.checklist.update_checklist_completion"


def test_01_unauthenticated_request_rejected():
    client = _make_client(user=None)
    resp = client.patch(
        f"/api/analyses/{ANALYSIS_ID}/checklist/{ITEM_ID}", json={"completed": True}
    )
    assert resp.status_code == 401
    app.dependency_overrides = {}


def test_02_authenticated_success_true():
    user = _make_user()
    mock_response = ChecklistCompletionResponse(item_id=str(ITEM_ID), completed=True)
    client = _make_client(user)

    with patch(SERVICE_PATH, new_callable=AsyncMock, return_value=mock_response) as mock_svc:
        resp = client.patch(
            f"/api/analyses/{ANALYSIS_ID}/checklist/{ITEM_ID}", json={"completed": True}
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["completed"] is True
    assert data["item_id"] == str(ITEM_ID)
    mock_svc.assert_called_once()
    app.dependency_overrides = {}


def test_03_authenticated_success_false():
    user = _make_user()
    mock_response = ChecklistCompletionResponse(item_id=str(ITEM_ID), completed=False)
    client = _make_client(user)

    with patch(SERVICE_PATH, new_callable=AsyncMock, return_value=mock_response):
        resp = client.patch(
            f"/api/analyses/{ANALYSIS_ID}/checklist/{ITEM_ID}", json={"completed": False}
        )

    assert resp.status_code == 200
    assert resp.json()["completed"] is False
    app.dependency_overrides = {}


def test_04_upsert_repeated_update():
    user = _make_user()
    client = _make_client(user)

    with patch(SERVICE_PATH, new_callable=AsyncMock) as mock_svc:
        mock_svc.return_value = ChecklistCompletionResponse(item_id=str(ITEM_ID), completed=True)
        resp1 = client.patch(
            f"/api/analyses/{ANALYSIS_ID}/checklist/{ITEM_ID}", json={"completed": True}
        )
        assert resp1.status_code == 200

        mock_svc.return_value = ChecklistCompletionResponse(item_id=str(ITEM_ID), completed=False)
        resp2 = client.patch(
            f"/api/analyses/{ANALYSIS_ID}/checklist/{ITEM_ID}", json={"completed": False}
        )
        assert resp2.status_code == 200

    assert mock_svc.call_count == 2
    app.dependency_overrides = {}


def test_05_analysis_not_found():
    user = _make_user()
    client = _make_client(user)

    with patch(
        SERVICE_PATH,
        new_callable=AsyncMock,
        side_effect=RepositoryNotFoundError("Analysis not found"),
    ):
        resp = client.patch(
            f"/api/analyses/{ANALYSIS_ID}/checklist/{ITEM_ID}", json={"completed": True}
        )

    assert resp.status_code == 404
    app.dependency_overrides = {}


def test_06_checklist_item_not_found():
    user = _make_user()
    client = _make_client(user)

    with patch(
        SERVICE_PATH,
        new_callable=AsyncMock,
        side_effect=ValidationError("Checklist item not found"),
    ):
        resp = client.patch(
            f"/api/analyses/{ANALYSIS_ID}/checklist/{ITEM_ID}", json={"completed": True}
        )

    assert resp.status_code == 422
    app.dependency_overrides = {}


def test_07_checklist_item_belongs_to_another_analysis():
    user = _make_user()
    client = _make_client(user)

    with patch(
        SERVICE_PATH,
        new_callable=AsyncMock,
        side_effect=ValidationError("Checklist item belongs to a different analysis"),
    ):
        resp = client.patch(
            f"/api/analyses/{ANALYSIS_ID}/checklist/{ITEM_ID}", json={"completed": True}
        )

    assert resp.status_code == 422
    app.dependency_overrides = {}


def test_08_unauthorized_repository_access():
    user = _make_user()
    client = _make_client(user)

    with patch(
        SERVICE_PATH,
        new_callable=AsyncMock,
        side_effect=RepositoryNotFoundError("Unauthorized"),
    ):
        resp = client.patch(
            f"/api/analyses/{ANALYSIS_ID}/checklist/{ITEM_ID}", json={"completed": True}
        )

    assert resp.status_code == 404
    app.dependency_overrides = {}


def test_09_invalid_body():
    user = _make_user()
    client = _make_client(user)

    # Missing 'completed' field
    resp = client.patch(f"/api/analyses/{ANALYSIS_ID}/checklist/{ITEM_ID}", json={})
    assert resp.status_code == 422

    # Invalid type
    resp = client.patch(
        f"/api/analyses/{ANALYSIS_ID}/checklist/{ITEM_ID}",
        json={"completed": "definitely_not_a_boolean"},
    )
    assert resp.status_code == 422

    app.dependency_overrides = {}
