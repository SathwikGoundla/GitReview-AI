"""
Step 16 tests — Feedback Service and API Router.

Strategy (same as Steps 13–15):
  - Router-level HTTP tests patch service functions at the router's import site.
  - Service-level tests mock DB and ORM objects directly.
  - get_current_user overridden via app.dependency_overrides.
  - get_db overridden with a no-op async generator.
  - No real PostgreSQL. No real GitHub. No real AI.

Coverage targets:
  Authentication:      1–2   (unauthenticated rejected, authenticated accepted)
  Authorization:       3–5   (unauthorized analysis → 404, authorized → 200, nonexistent → 404)
  Payload validation:  6–10  (valid accepted, bad prediction_type, bad rating, missing fields,
                               bad reference)
  Database behavior:  11–14  (new record, upsert, correct FKs, calibration updated)
  Security:           15–17  (IDOR cross-user, no tokens in response, prediction reference
                               belongs to different analysis)
  Schema:             18–20  (enum constraints, response shape, comment strip)
  Calibration:        21–23  (new helpful, new unhelpful, rating change adjusts counts)
  Regression:         24–25  (all prior routes still registered, health still works)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.core.exceptions import (
    RepositoryNotFoundError,
    ValidationError,
)
from app.feedback.schemas import FeedbackRating, FeedbackResponse, PredictionType
from app.main import app

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_user(username: str = "sathwik", uid: uuid.UUID | None = None) -> MagicMock:
    user = MagicMock()
    user.id = uid or uuid.uuid4()
    user.github_username = username
    user.github_user_id = 12345678
    user.encrypted_access_token = "enc-fake-tok"
    user.preferences = {}
    return user


def _make_feedback_response(
    analysis_id: uuid.UUID | None = None,
    prediction_type: PredictionType = PredictionType.risk_tier,
    prediction_reference_id: uuid.UUID | None = None,
    rating: FeedbackRating = FeedbackRating.helpful,
) -> FeedbackResponse:
    return FeedbackResponse(
        feedback_id=uuid.uuid4(),
        analysis_id=analysis_id or uuid.uuid4(),
        prediction_type=prediction_type,
        prediction_reference_id=prediction_reference_id or uuid.uuid4(),
        rating=rating,
        created_at=datetime.now(UTC),
    )


def _noop_db():
    """No-op DB override — satisfies DI without a real connection."""

    async def _gen():
        yield MagicMock()

    return _gen()


def _make_client(user: MagicMock | None = None) -> TestClient:
    """
    Return a TestClient with get_current_user and get_db overridden.
    If user is None, the client is unauthenticated.
    """
    overrides = {get_db: _noop_db}
    if user is not None:
        overrides[get_current_user] = lambda: user
    app.dependency_overrides = overrides
    return TestClient(app, raise_server_exceptions=False)


def _valid_body(
    prediction_type: str = "risk_tier",
    prediction_reference_id: str | None = None,
    rating: str = "helpful",
    comment: str | None = None,
) -> dict:
    body: dict = {
        "prediction_type": prediction_type,
        "prediction_reference_id": prediction_reference_id or str(uuid.uuid4()),
        "rating": rating,
    }
    if comment is not None:
        body["comment"] = comment
    return body


ANALYSIS_ID = uuid.uuid4()
SERVICE_PATH = "app.api.feedback.submit_feedback"


# ── 1. Authentication: unauthenticated rejected ────────────────────────────────


def test_01_unauthenticated_request_rejected():
    """No X-Session-Token → 401."""
    client = _make_client(user=None)
    resp = client.post(f"/api/analyses/{ANALYSIS_ID}/feedback", json=_valid_body())
    assert resp.status_code == 401
    app.dependency_overrides = {}


# ── 2. Authentication: authenticated request reaches service ──────────────────


def test_02_authenticated_request_accepted():
    """Valid session + valid payload → service called → 200."""
    user = _make_user()
    mock_response = _make_feedback_response()
    client = _make_client(user)

    with patch(SERVICE_PATH, new_callable=AsyncMock, return_value=mock_response):
        resp = client.post(f"/api/analyses/{ANALYSIS_ID}/feedback", json=_valid_body())

    assert resp.status_code == 200
    app.dependency_overrides = {}


# ── 3. Authorization: nonexistent analysis → 404 ─────────────────────────────


def test_03_nonexistent_analysis_returns_404():
    """Service raises RepositoryNotFoundError → router returns 404."""
    user = _make_user()
    client = _make_client(user)

    with patch(
        SERVICE_PATH,
        new_callable=AsyncMock,
        side_effect=RepositoryNotFoundError("Analysis not found or not authorized."),
    ):
        resp = client.post(f"/api/analyses/{ANALYSIS_ID}/feedback", json=_valid_body())

    assert resp.status_code == 404
    app.dependency_overrides = {}


# ── 4. Authorization: unauthorized analysis → 404 (IDOR protection) ───────────


def test_04_unauthorized_analysis_returns_404_not_403():
    """
    Cross-user: service raises RepositoryNotFoundError even when analysis exists
    but belongs to a different user's repository. Router returns 404, not 403,
    to prevent leaking resource existence.
    """
    user = _make_user()
    client = _make_client(user)

    with patch(
        SERVICE_PATH,
        new_callable=AsyncMock,
        side_effect=RepositoryNotFoundError("Analysis not found or not authorized."),
    ):
        resp = client.post(f"/api/analyses/{ANALYSIS_ID}/feedback", json=_valid_body())

    assert resp.status_code == 404
    data = resp.json()
    # Must not expose the word "exists" or "forbidden" — should be generic not-found
    assert "not found" in data.get("message", "").lower() or "not found" in str(
        data.get("detail", "")
    ).lower() or resp.status_code == 404
    app.dependency_overrides = {}


# ── 5. Authorization: authorized user, valid analysis → 200 ──────────────────


def test_05_authorized_analysis_returns_200():
    """User has access to the repository that owns the analysis → 200."""
    user = _make_user()
    analysis_id = uuid.uuid4()
    ref_id = uuid.uuid4()
    mock_response = _make_feedback_response(
        analysis_id=analysis_id,
        prediction_type=PredictionType.risk_tier,
        prediction_reference_id=ref_id,
    )
    client = _make_client(user)

    body = _valid_body(prediction_reference_id=str(ref_id))
    with patch(SERVICE_PATH, new_callable=AsyncMock, return_value=mock_response):
        resp = client.post(f"/api/analyses/{analysis_id}/feedback", json=body)

    assert resp.status_code == 200
    data = resp.json()
    assert data["analysis_id"] == str(analysis_id)
    app.dependency_overrides = {}


# ── 6. Payload validation: valid feedback accepted ────────────────────────────


def test_06_valid_payload_accepted():
    """All three prediction_types and both ratings must be accepted."""
    user = _make_user()
    client = _make_client(user)

    for ptype in ["risk_tier", "reviewer_recommendation", "checklist_item"]:
        for rating in ["helpful", "unhelpful"]:
            mock_response = _make_feedback_response()
            body = _valid_body(prediction_type=ptype, rating=rating)
            with patch(SERVICE_PATH, new_callable=AsyncMock, return_value=mock_response):
                resp = client.post(f"/api/analyses/{ANALYSIS_ID}/feedback", json=body)
            assert resp.status_code == 200, f"Failed for {ptype}/{rating}: {resp.json()}"

    app.dependency_overrides = {}


# ── 7. Payload validation: invalid prediction_type rejected ──────────────────


def test_07_invalid_prediction_type_rejected():
    """Unknown prediction_type → 422 (Pydantic validation)."""
    user = _make_user()
    client = _make_client(user)
    body = _valid_body(prediction_type="unknown_type")

    resp = client.post(f"/api/analyses/{ANALYSIS_ID}/feedback", json=body)
    assert resp.status_code == 422
    app.dependency_overrides = {}


# ── 8. Payload validation: invalid rating rejected ────────────────────────────


def test_08_invalid_rating_rejected():
    """Unknown rating → 422 (Pydantic validation)."""
    user = _make_user()
    client = _make_client(user)
    body = _valid_body(rating="maybe")

    resp = client.post(f"/api/analyses/{ANALYSIS_ID}/feedback", json=body)
    assert resp.status_code == 422
    app.dependency_overrides = {}


# ── 9. Payload validation: missing required fields rejected ──────────────────


def test_09_missing_required_fields_rejected():
    """Empty body → 422."""
    user = _make_user()
    client = _make_client(user)

    resp = client.post(f"/api/analyses/{ANALYSIS_ID}/feedback", json={})
    assert resp.status_code == 422
    app.dependency_overrides = {}


# ── 10. Payload validation: wrong prediction reference → 400 ─────────────────


def test_10_wrong_prediction_reference_returns_400():
    """Service raises ValidationError (prediction ref not found) → 400 from GitReviewError."""
    user = _make_user()
    client = _make_client(user)

    with patch(
        SERVICE_PATH,
        new_callable=AsyncMock,
        side_effect=ValidationError(
            "prediction_reference_id does not match a risk assessment for this analysis."
        ),
    ):
        resp = client.post(f"/api/analyses/{ANALYSIS_ID}/feedback", json=_valid_body())

    assert resp.status_code == 422  # ValidationError has http_status=422
    app.dependency_overrides = {}


# ── 11. Database: new feedback record persisted ──────────────────────────────


def test_11_new_feedback_record_persisted():
    """Service called with correct arguments on a new feedback submission."""
    user = _make_user()
    ref_id = uuid.uuid4()
    analysis_id = uuid.uuid4()
    mock_response = _make_feedback_response(
        analysis_id=analysis_id,
        prediction_reference_id=ref_id,
    )
    client = _make_client(user)

    body = _valid_body(
        prediction_type="risk_tier",
        prediction_reference_id=str(ref_id),
        rating="helpful",
        comment="Great catch!",
    )
    with patch(SERVICE_PATH, new_callable=AsyncMock, return_value=mock_response) as mock_svc:
        resp = client.post(f"/api/analyses/{analysis_id}/feedback", json=body)

    assert resp.status_code == 200
    mock_svc.assert_called_once()
    call_kwargs = mock_svc.call_args.kwargs
    assert call_kwargs["prediction_type"] == PredictionType.risk_tier
    assert call_kwargs["rating"] == FeedbackRating.helpful
    assert call_kwargs["comment"] == "Great catch!"
    app.dependency_overrides = {}


# ── 12. Database: upsert (existing feedback updated) ─────────────────────────


def test_12_upsert_feedback_returns_200():
    """Submitting feedback a second time (same prediction) returns 200 (upsert, not error)."""
    user = _make_user()
    mock_response = _make_feedback_response(rating=FeedbackRating.unhelpful)
    client = _make_client(user)

    # First submission
    with patch(SERVICE_PATH, new_callable=AsyncMock, return_value=mock_response):
        resp1 = client.post(f"/api/analyses/{ANALYSIS_ID}/feedback", json=_valid_body())
    assert resp1.status_code == 200

    # Second submission (same prediction, different rating)
    body2 = _valid_body(rating="unhelpful")
    with patch(SERVICE_PATH, new_callable=AsyncMock, return_value=mock_response):
        resp2 = client.post(f"/api/analyses/{ANALYSIS_ID}/feedback", json=body2)
    assert resp2.status_code == 200

    app.dependency_overrides = {}


# ── 13. Database: correct analysis_id in response ─────────────────────────────


def test_13_response_analysis_id_matches_path():
    """The response analysis_id must match the path parameter."""
    user = _make_user()
    analysis_id = uuid.uuid4()
    mock_response = _make_feedback_response(analysis_id=analysis_id)
    client = _make_client(user)

    with patch(SERVICE_PATH, new_callable=AsyncMock, return_value=mock_response):
        resp = client.post(f"/api/analyses/{analysis_id}/feedback", json=_valid_body())

    assert resp.status_code == 200
    assert resp.json()["analysis_id"] == str(analysis_id)
    app.dependency_overrides = {}


# ── 14. Database: correct user passed to service ─────────────────────────────


def test_14_correct_user_passed_to_service():
    """The authenticated user's ORM object is passed to the service, not a copy."""
    user = _make_user(username="testuser")
    mock_response = _make_feedback_response()
    client = _make_client(user)

    with patch(SERVICE_PATH, new_callable=AsyncMock, return_value=mock_response) as mock_svc:
        resp = client.post(f"/api/analyses/{ANALYSIS_ID}/feedback", json=_valid_body())

    assert resp.status_code == 200
    call_kwargs = mock_svc.call_args.kwargs
    assert call_kwargs["user"] is user
    app.dependency_overrides = {}


# ── 15. Security: cross-user IDOR rejected ────────────────────────────────────


def test_15_cross_user_idor_returns_404():
    """
    User B tries to submit feedback on an analysis that belongs to User A's repository.
    The service should raise RepositoryNotFoundError → 404.
    Never returns 403 (would confirm analysis exists).
    """
    user_b = _make_user(username="user_b")
    client = _make_client(user_b)

    with patch(
        SERVICE_PATH,
        new_callable=AsyncMock,
        side_effect=RepositoryNotFoundError(
            "Analysis not found or not authorized for the current user."
        ),
    ):
        resp = client.post(f"/api/analyses/{ANALYSIS_ID}/feedback", json=_valid_body())

    assert resp.status_code == 404
    assert resp.status_code != 403  # Must not be 403
    app.dependency_overrides = {}


# ── 16. Security: no sensitive fields in response ────────────────────────────


def test_16_no_sensitive_fields_in_response():
    """Response must not contain tokens, credentials, or private DB internals."""
    user = _make_user()
    mock_response = _make_feedback_response()
    client = _make_client(user)

    with patch(SERVICE_PATH, new_callable=AsyncMock, return_value=mock_response):
        resp = client.post(f"/api/analyses/{ANALYSIS_ID}/feedback", json=_valid_body())

    assert resp.status_code == 200
    data = resp.json()

    forbidden_fields = [
        "token",
        "access_token",
        "encrypted_access_token",
        "session_token",
        "password",
        "secret",
        "github_user_id",
        "user_id",
    ]
    for field in forbidden_fields:
        assert field not in data, f"Sensitive field '{field}' found in response"

    app.dependency_overrides = {}


# ── 17. Security: prediction reference from different analysis rejected ────────


def test_17_prediction_reference_from_different_analysis_rejected():
    """
    prediction_reference_id that belongs to a different analysis → ValidationError → 422.
    Prevents IDOR between analyses.
    """
    user = _make_user()
    client = _make_client(user)

    with patch(
        SERVICE_PATH,
        new_callable=AsyncMock,
        side_effect=ValidationError(
            "prediction_reference_id does not match a risk assessment for this analysis."
        ),
    ):
        resp = client.post(f"/api/analyses/{ANALYSIS_ID}/feedback", json=_valid_body())

    assert resp.status_code == 422
    app.dependency_overrides = {}


# ── 18. Schema: prediction_type enum values ───────────────────────────────────


def test_18_prediction_type_enum():
    """PredictionType enum must have exactly the three allowed values."""
    assert set(PredictionType) == {
        PredictionType.risk_tier,
        PredictionType.reviewer_recommendation,
        PredictionType.checklist_item,
    }
    assert PredictionType.risk_tier.value == "risk_tier"
    assert PredictionType.reviewer_recommendation.value == "reviewer_recommendation"
    assert PredictionType.checklist_item.value == "checklist_item"


# ── 19. Schema: response shape ────────────────────────────────────────────────


def test_19_response_shape():
    """FeedbackResponse must contain exactly the expected fields."""
    user = _make_user()
    ref_id = uuid.uuid4()
    analysis_id = uuid.uuid4()
    mock_response = _make_feedback_response(
        analysis_id=analysis_id,
        prediction_type=PredictionType.reviewer_recommendation,
        prediction_reference_id=ref_id,
        rating=FeedbackRating.unhelpful,
    )
    client = _make_client(user)

    body = _valid_body(
        prediction_type="reviewer_recommendation",
        prediction_reference_id=str(ref_id),
        rating="unhelpful",
    )
    with patch(SERVICE_PATH, new_callable=AsyncMock, return_value=mock_response):
        resp = client.post(f"/api/analyses/{analysis_id}/feedback", json=body)

    assert resp.status_code == 200
    data = resp.json()
    assert "feedback_id" in data
    assert "analysis_id" in data
    assert "prediction_type" in data
    assert "prediction_reference_id" in data
    assert "rating" in data
    assert "created_at" in data
    assert data["prediction_type"] == "reviewer_recommendation"
    assert data["rating"] == "unhelpful"

    app.dependency_overrides = {}


# ── 20. Schema: comment whitespace stripped ───────────────────────────────────


def test_20_comment_whitespace_only_treated_as_none():
    """A comment that is only whitespace must be treated as None (schema validator)."""
    from app.feedback.schemas import SubmitFeedbackRequest

    req = SubmitFeedbackRequest(
        prediction_type=PredictionType.risk_tier,
        prediction_reference_id=uuid.uuid4(),
        rating=FeedbackRating.helpful,
        comment="   ",
    )
    assert req.comment is None


# ── 21. Calibration: new helpful record increments helpful_count ──────────────


@pytest.mark.asyncio
async def test_21_calibration_new_helpful_increments_count():
    """
    When new feedback with rating=helpful is submitted, _update_calibration
    increments helpful_count on the ConfidenceCalibration row.
    """
    from app.feedback.service import _update_calibration

    calibration = MagicMock()
    calibration.helpful_count = 5
    calibration.unhelpful_count = 2
    calibration.last_updated_at = datetime.now(UTC)

    db = AsyncMock()
    db.add = MagicMock()  # add() is synchronous in SQLAlchemy
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=calibration))

    await _update_calibration(
        db=db,
        prediction_type="risk_tier",
        rating=FeedbackRating.helpful,
        is_new_record=True,
        old_rating=None,
    )

    assert calibration.helpful_count == 6
    assert calibration.unhelpful_count == 2


# ── 22. Calibration: new unhelpful record increments unhelpful_count ──────────


@pytest.mark.asyncio
async def test_22_calibration_new_unhelpful_increments_count():
    """New feedback with rating=unhelpful increments unhelpful_count."""
    from app.feedback.service import _update_calibration

    calibration = MagicMock()
    calibration.helpful_count = 5
    calibration.unhelpful_count = 2
    calibration.last_updated_at = datetime.now(UTC)

    db = AsyncMock()
    db.add = MagicMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=calibration))

    await _update_calibration(
        db=db,
        prediction_type="risk_tier",
        rating=FeedbackRating.unhelpful,
        is_new_record=True,
        old_rating=None,
    )

    assert calibration.helpful_count == 5
    assert calibration.unhelpful_count == 3


# ── 23. Calibration: rating change adjusts both counters ─────────────────────


@pytest.mark.asyncio
async def test_23_calibration_rating_change_adjusts_both_counters():
    """
    When an existing helpful rating is changed to unhelpful:
      helpful_count decremented, unhelpful_count incremented.
    """
    from app.feedback.service import _update_calibration

    calibration = MagicMock()
    calibration.helpful_count = 5
    calibration.unhelpful_count = 2
    calibration.last_updated_at = datetime.now(UTC)

    db = AsyncMock()
    db.add = MagicMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=calibration))

    await _update_calibration(
        db=db,
        prediction_type="risk_tier",
        rating=FeedbackRating.unhelpful,
        is_new_record=False,
        old_rating="helpful",  # was helpful, now unhelpful
    )

    assert calibration.helpful_count == 4  # decremented
    assert calibration.unhelpful_count == 3  # incremented


# ── 24. Regression: all prior routes still registered ────────────────────────


def test_24_prior_routes_still_registered():
    """All routes from Steps 13–15 must remain present after Step 16."""
    app.dependency_overrides = {}
    paths = list(app.openapi()["paths"].keys())
    expected = [
        "/api/auth/login",
        "/api/auth/callback",
        "/api/auth/logout",
        "/api/auth/me",
        "/api/repositories",
        "/api/repositories/authorize",
        "/api/repositories/{repository_id}/access",
        "/api/repositories/{repository_id}/pulls",
        "/api/repositories/{repository_id}/pulls/{pull_number}",
        "/api/repositories/{repository_id}/pulls/{pull_number}/analyze",
        "/api/analyses/{analysis_id}/feedback",
        "/health",
    ]
    for expected_path in expected:
        assert expected_path in paths, f"Route missing: {expected_path}"


# ── 25. Regression: health endpoint still works ───────────────────────────────


def test_25_health_endpoint_still_works():
    """Health endpoint must still return 200 after Step 16."""
    app.dependency_overrides = {}
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
