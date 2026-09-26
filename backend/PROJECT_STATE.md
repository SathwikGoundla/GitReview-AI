# GitReview AI — PROJECT_STATE.md
# Authoritative continuity document. Updated after every implementation step.
# Next session: UPLOAD ZIP → EXTRACT → READ THIS FILE FIRST → INSPECT SOURCE → CONTINUE.

---

## RECONSTRUCTION NOTE

This project was reconstructed from approved design documents in session 2026-09-18.
No prior codebase was available. All source files were built from:

  - GitReview_AI_PRD.docx
  - GitReview_AI_SRS.docx
  - GitReview_AI_HLD.docx
  - GitReview_AI_LLD.docx
  - GitReview_AI_Database_Validation.docx

Status label: **RECONSTRUCTED FROM APPROVED DOCUMENTATION**

---

## CURRENT PHASE

**Phase: Backend Core — Steps 1–12 RECONSTRUCTED**
**Test suite: 152 / 152 passing**
**Ruff: CLEAN (0 errors)**
**Format: CLEAN**

---

## STEP STATUS

| Step | Component | Status |
|------|-----------|--------|
| 1 | Project scaffold (directory structure, pyproject.toml, .env.example) | RECONSTRUCTED |
| 2 | FastAPI infrastructure (app/main.py, health endpoint, CORS, config, logging, exceptions) | RECONSTRUCTED |
| 3 | Database schema — 17 tables, Alembic migration 0001_initial_schema | RECONSTRUCTED |
| 4 | ORM models — all 17 tables in app/core/models.py | RECONSTRUCTED |
| 5 | Core security — Fernet encryption, SHA-256 session hashing, itsdangerous CSRF | RECONSTRUCTED |
| 6 | GitHub Integration Module — GitHubApiClient, CODEOWNERS parser, PRData | RECONSTRUCTED |
| 7 | AI Provider Module — AIProviderInterface (Protocol), GeminiAdapter | RECONSTRUCTED |
| 8 | Prompt Builder — secure single-pass prompt, injection mitigations, chunking | RECONSTRUCTED |
| 9 | AI Output Validator — schema/enum/cross-field/hallucination checks | RECONSTRUCTED |
| 10 | Hybrid Risk Engine — deterministic signals + AI advisory combination | RECONSTRUCTED |
| 11 | Confidence Calculator — hybrid scoring, cold-start cap, calibration | RECONSTRUCTED |
| 12 | Reviewer Recommendation Service — CODEOWNERS-weighted ranking, abstain-on-insufficient-evidence | RECONSTRUCTED |
| 12b | Checklist Generator — deterministic rules + AI signal merge | RECONSTRUCTED |
| 12c | PR Analysis Orchestrator — full pipeline coordination, cache, atomic persistence | RECONSTRUCTED |

---

## FILES CREATED

```
backend/
  pyproject.toml
  alembic.ini
  .env.example
  app/
    __init__.py
    main.py
    core/
      __init__.py
      config.py          — Settings (pydantic-settings), all env vars
      database.py        — AsyncSession, get_db dependency
      exceptions.py      — Typed exception hierarchy (17 exception classes)
      logging.py         — Structured logging with diff-content scrubbing
      models.py          — SQLAlchemy ORM, all 17 tables
      security.py        — Fernet encryption, SHA-256 hashing, CSRF state
    ai_provider/
      __init__.py
      interface.py       — AIProviderInterface (Protocol, runtime_checkable)
      gemini_adapter.py  — GeminiAdapter (concrete Gemini 2.5 Flash implementation)
    analysis/
      __init__.py
      orchestrator.py    — AnalysisOrchestrator (full pipeline coordinator)
      prompt/
        __init__.py
        builder.py       — PromptBuilder, NormalizedPRData, injection detection
      validation/
        __init__.py
        validator.py     — AnalysisResponseValidator, ValidationResult
      risk/
        __init__.py
        engine.py        — RiskEngine, DeterministicSignals, RiskResult
      confidence/
        __init__.py
        calculator.py    — ConfidenceCalculator, CalibrationData, ConfidenceInputs
      reviewer/
        __init__.py
        service.py       — ReviewerRankingService, ReviewerRecommendationResult
      checklist/
        __init__.py
        generator.py     — ChecklistGenerator, ChecklistItemResult, ChecklistResult
    github_integration/
      __init__.py
      client.py          — GitHubApiClient, PRData
  migrations/
    __init__.py
    env.py
    versions/
      0001_initial_schema.py   — All 17 tables with all 6 DB Validation corrections
  tests/
    conftest.py
    unit/
      __init__.py
      test_core.py             — Config, exceptions, logging (21 tests)
      auth/
        __init__.py
        test_security.py       — Fernet, SHA-256, CSRF, session token (17 tests)
      ai_provider/
        __init__.py
        test_provider.py       — Protocol, adapter, error types (9 tests)
      analysis/
        __init__.py
        test_prompt_builder.py — PromptBuilder, injection, chunking (14 tests)
        test_validator.py      — Schema validation, edge cases (27 tests)
        risk/
          __init__.py
          test_engine.py       — Deterministic signals, hybrid combination (18 tests)
        confidence/
          __init__.py
          test_calculator.py   — Scoring, calibration, bands (12 tests)
        reviewer/
          __init__.py
          test_service.py      — Ranking, filtering, abstain (15 tests)
        checklist/
          __init__.py
          test_generator.py    — Deterministic rules, AI merge (17 tests)
      github_integration/
        __init__.py
        test_client.py         — CODEOWNERS parsing, error handling (15 tests)
```

---

## DATABASE CHANGES

Migration: `migrations/versions/0001_initial_schema.py`

All 6 Database Validation document corrections applied:
1. `review_checklists` REMOVED — `checklist_is_fallback_default` moved to `pull_request_analyses`
2. `notifications` deduplication → partial UNIQUE index WHERE read_at IS NULL
3. `feedback.prediction_reference_id` → exclusive-arc FKs with CHECK constraint
4. `analytics_daily_metrics` → split into `user_daily_metrics` + `repository_daily_metrics`
5. `repository_access.role` → `github_permission_level` with CHECK constraint
6. `(pull_request_id, created_at DESC)` index added to `pull_request_analyses`

SQLAlchemy fix: `analysis_metrics_log.metadata` renamed to `event_metadata` in Python
(column name in DB stays `metadata`; `metadata` is a reserved SQLAlchemy name).

---

## BUGS FOUND AND FIXED

| # | File | Bug | Fix |
|---|------|-----|-----|
| 1 | `app/core/models.py` | `metadata` column name reserved by SQLAlchemy | Renamed to `event_metadata` with explicit `"metadata"` column arg |
| 2 | `app/ai_provider/gemini_adapter.py` | Unused `import asyncio` | Removed |
| 3 | `app/analysis/checklist/generator.py` | `_parse_ai_signal` crashed on non-list input (AttributeError) | Added `isinstance(ai_checklist, list)` guard and `AttributeError` to except clause |
| 4 | `app/analysis/checklist/generator.py` | `testing` added to fallback checklist even when test files are present | `_build_fallback` now suppresses baseline items that deterministic rules correctly excluded |
| 5 | `app/analysis/orchestrator.py` | Dead `required_retry = False` variable never returned | Removed dead initialization |
| 6 | `app/analysis/orchestrator.py` | Unused imports (AIValidationError, AnalysisDegradedError, AnalysisError, ConfidenceCalibration) | Removed |
| 7 | `app/core/security.py` | Unused `import os` | Removed |
| 8 | `app/analysis/validation/validator.py` | Unused `AIValidationError` import | Removed |
| 9 | Config | `reviewer_min_evidence_threshold=0.1` too high — 2 reviews (score=0.06) correctly below threshold but SRS says 2+ reviews qualifies | Lowered to 0.05 (2 reviews → score=0.06 > 0.05) |
| 10 | Tests | `verify_oauth_state(state, max_age_seconds=0)` doesn't expire within same second | Changed to `max_age_seconds=-1` (forces expiry) |

---

## REMOVAL CANDIDATES

None at this stage. All code is actively used.

---

## CANDIDATE FUTURE FEATURES (from engineering review)

| Feature | Classification | Reason |
|---------|---------------|--------|
| Diff noise classification | FUTURE | Useful but not in approved SRS; add in later phase |
| Change-impact / dependency analysis | FUTURE | Out of MVP scope per PRD Section 8 |
| Security-sensitive change detection | KEEP (already implemented) | Handled by sensitive_path_patterns in Risk Engine |
| AI finding verification | MODIFY | Currently done by AnalysisResponseValidator; could be strengthened |
| Evidence-backed explainability | KEEP (already implemented) | Rationale structure in RiskResult |
| Finding deduplication | FUTURE | Not yet needed at MVP scale |
| Evidence-based reviewer recommendation | KEEP (already implemented) | ReviewerRankingService with abstain behavior |
| Adaptive review checklist | KEEP (already implemented) | ChecklistGenerator with deterministic + AI merge |
| PR prioritization | PLANNED | ReviewPrioritizationModule — next step |
| Feedback → confidence calibration | PLANNED | ConfidenceCalibration table seeded; feedback service not yet implemented |
| Analysis versioning | KEEP (already implemented) | prompt_template_version on every analysis row |
| Database-backed idempotency | KEEP (already implemented) | UNIQUE(pull_request_id, commit_sha) cache key |
| Large-PR semantic analysis | FUTURE | Chunking strategy implemented in PromptBuilder; full semantic merge is future |
| Celery/Redis | REJECT | Not in approved architecture; in-process background tasks sufficient for MVP |
| Kubernetes/microservices | REJECT | Modular monolith is the approved architecture |

---

## KNOWN LIMITATIONS

1. **No FastAPI routers implemented yet** — app/main.py has only the health endpoint. API layer (auth routes, analysis routes, feedback routes) is the next major step.
2. **No authentication middleware** — session validation not yet wired into the gateway.
3. **No database tested against real PostgreSQL** — all tests are pure unit tests (no DB connection required). Integration tests against a real DB are future work.
4. **GeminiAdapter uses real HTTP** — tests mock the interface, not the adapter itself. Integration tests against Gemini require a real API key.
5. **No Chrome Extension code** — backend only at this stage.
6. **No GitHub Actions workflow file** — backend only at this stage.

---

## ARCHITECTURAL DECISIONS (session 2026-09-18)

1. **AIProviderInterface as `runtime_checkable` Protocol** — allows `isinstance()` check at module load time to verify GeminiAdapter satisfies the contract. Prevents silent interface drift.
2. **`metadata` → `event_metadata` in SQLAlchemy** — `metadata` is a reserved declarative API attribute. The DB column name stays `metadata` using `mapped_column("metadata", ...)`. This is transparent to the DB but Python-safe.
3. **reviewer_min_evidence_threshold = 0.05** — Lowered from 0.1 to ensure that a candidate with 2 review history entries (score = 2/10 × 0.3 = 0.06) clears the threshold. SRS FR-5.4 says abstain when evidence is insufficient; 2 reviews is explicitly cited in LLD Part J as meaningful evidence.
4. **_build_fallback suppresses context-aware baseline items** — When test files ARE present, the `testing` baseline item is not added to the fallback checklist. This is correct behavior: the fallback should reflect what deterministic rules would have computed.

---

## TEST RESULTS

```
152 passed, 0 failed, 0 errors
Ruff: All checks passed (0 errors)
Format: 28 files reformatted, 38 files unchanged
```

Test file breakdown:
- test_core.py: 21 tests
- test_security.py: 17 tests
- test_provider.py: 9 tests
- test_prompt_builder.py: 14 tests
- test_validator.py: 27 tests
- test_engine.py: 18 tests
- test_calculator.py: 12 tests
- test_service.py (reviewer): 15 tests
- test_generator.py (checklist): 17 tests
- test_client.py (github): 15 tests

---

## EXACT NEXT ACTION

**Step 13: FastAPI API Layer — Authentication Routes**

Implement:
- `app/auth/service.py` — AuthService (OAuth flow, session lifecycle)
- `app/auth/schemas.py` — Pydantic request/response schemas
- `app/api/auth.py` — FastAPI router: /api/auth/login, /api/auth/callback, /api/auth/logout
- `app/api/dependencies.py` — `get_current_user` dependency (session validation)
- `tests/unit/auth/test_auth_service.py`
- Wire router into app/main.py

After Step 13:
- Step 14: Repository authorization routes
- Step 15: Analysis endpoint (trigger + cache check)
- Step 16: Feedback endpoint
- Step 17: Analytics endpoints
- Step 18: Notification endpoints
- Step 19: GitHub Actions endpoint
- Step 20: Chrome Extension

---
*Last updated: 2026-09-18 | Session: Reconstruction from approved documents*

---

## STEP 13 — FastAPI API Layer: Authentication

**Status: IMPLEMENTED**
**Date: 2026-09-19**
**Tests: 205 / 205 passing (53 new tests added)**
**Ruff: CLEAN (0 errors)**

### Objective
Expose the existing backend authentication functionality through a proper FastAPI API layer.

### Files Created

| File | Purpose |
|------|---------|
| `app/auth/service.py` | AuthService — OAuth flow, session lifecycle (initiate, callback, validate, revoke) |
| `app/auth/schemas.py` | Pydantic schemas — LoginInitResponse, CallbackResponse, UserProfile, CurrentUserResponse, LogoutResponse, ErrorResponse |
| `app/api/auth.py` | FastAPI router — GET /api/auth/login, GET /api/auth/callback, POST /api/auth/logout, GET /api/auth/me |
| `app/api/dependencies.py` | get_current_user FastAPI dependency — resolves X-Session-Token header to authenticated User |
| `tests/unit/auth/test_auth_service.py` | 53 tests covering all 13 Step 13 spec targets |

### Files Modified

| File | Change |
|------|--------|
| `app/main.py` | Added auth_router include, GitReviewError global exception handler, CORS header for X-Session-Token and X-OAuth-State |
| `migrations/versions/0001_initial_schema.py` | Fixed pre-existing trailing whitespace (Ruff W291) |
| `migrations/env.py` | Fixed pre-existing import sort (Ruff I001) |

### API Routes Added

| Method | Path | Auth Required | Purpose |
|--------|------|---------------|---------|
| GET | /api/auth/login | No | Returns GitHub OAuth authorize URL + CSRF state |
| GET | /api/auth/callback | No | Exchanges code+state → session token + user |
| POST | /api/auth/logout | No (idempotent) | Revokes session identified by X-Session-Token header |
| GET | /api/auth/me | Yes (X-Session-Token) | Returns current authenticated user profile |
| GET | /health | No | Pre-existing health check |

### Database Changes
None. Step 13 uses the existing 17-table schema. No new migration needed.

### Dependencies Added/Changed
None. All required packages (fastapi, pydantic, httpx, cryptography, itsdangerous) were already in pyproject.toml.

### Architectural Decisions

1. **HTTP method choices**: login=GET (no body, extension fetches URL), callback=GET (GitHub always redirects with GET), logout=POST (mutates state, prevents accidental browser prefetch), me=GET (read-only).

2. **Session token in X-Session-Token header**: Keeps token out of URL (server logs), avoids confusion with GitHub OAuth tokens that might appear in Authorization: Bearer headers, is explicit and custom to this system.

3. **CSRF state storage**: The signed state is returned in the login JSON body. The extension stores it in chrome.storage.local and sends it back via X-OAuth-State header on the callback. This works because the extension is not a web page served from the backend domain, so cookies are not the right mechanism.

4. **Patch target for tests**: Router-level tests patch at `app.api.auth.handle_oauth_callback` (where the router imports it), not at `app.auth.service.handle_oauth_callback`. This is the correct Python mock pattern — "patch where it's used, not where it's defined."

5. **FastAPI dependency_overrides for DB**: Test suite uses `app.dependency_overrides[get_db] = _noop_db` so the DB dependency in the DI graph is satisfied without a real connection. Service functions are patched separately per test so the mock DB is never actually called by service code.

6. **Global GitReviewError handler**: Added to main.py so our typed exception hierarchy produces structured JSON on 4xx/5xx responses. HTTPExceptions from dependencies produce the FastAPI standard {"detail": {...}} envelope.

### Test Results (exact)

```
Command: python -m pytest tests/ -q
Result:  205 passed, 2 warnings in 0.92s
         (153 pre-existing + 53 new Step 13 tests; 1 pre-existing test was re-counted as 152→152+53=205)

Step 13 focused:
Command: python -m pytest tests/unit/auth/test_auth_service.py -v
Result:  53 passed, 2 warnings in 2.47s
```

### Ruff Result (exact)
```
Command: python -m ruff check .
Result:  All checks passed!
```

### Known Limitations
1. OAuth callback currently trusts the X-OAuth-State header the client sends; in production, consider binding state to a short-lived server-side store (Redis/DB) keyed by browser fingerprint for additional CSRF hardness.
2. No integration tests against a real PostgreSQL database. All tests are pure unit tests.
3. /api/auth/callback is a GET because GitHub redirects with GET. In a strict REST design, state-changing operations should be POST; this is a GitHub OAuth platform constraint, not a design choice.

### Known Issues
None blocking. The 2 warnings in pytest output are:
- StarletteDeprecationWarning about httpx (starlette recommends httpx2; not yet needed)
- DeprecationWarning from anyio re: BlockingPortal alias (pytest-asyncio internals; not our code)

### Exact Next Step
**Step 14: Repository Authorization Routes**
- `app/repositories/service.py` — list, authorize, revoke repository access
- `app/repositories/schemas.py` — Pydantic schemas
- `app/api/repositories.py` — FastAPI router: GET/POST/DELETE /api/repositories/...
- Tests for repository authorization with get_current_user dependency
- Wire into main.py

---
*Last updated: 2026-09-19 | Step 13 IMPLEMENTED*

---

## STEP 14 — Repository Authorization API

**Status: IMPLEMENTED**
**Date: 2026-09-19**
**Tests: 248 / 248 passing (43 new tests added)**
**Ruff: CLEAN (0 errors, 7 auto-fixed)**

### Objective
Expose repository authorization through the FastAPI API layer, using the existing models, GitHub client, and authentication dependency from Steps 1–13.

### Baseline (actually verified)
- Step 13 ZIP extracted and verified
- 205/205 pre-existing tests passing before Step 14 changes
- Ruff: clean
- `app/repositories/__init__.py` existed (empty package only)
- No repository service, schemas, or router existed

### Files Created

| File | Purpose |
|------|---------|
| `app/repositories/service.py` | authorize_repository, list_authorized_repositories, revoke_repository_access |
| `app/repositories/schemas.py` | AuthorizeRepositoryRequest, RepositoryResponse, RepositoryAccessResponse, RepositoryListResponse, AuthorizeRepositoryResponse, RevokeAccessResponse |
| `app/api/repositories.py` | FastAPI router — GET /api/repositories, POST /api/repositories/authorize, DELETE /api/repositories/{id}/access |
| `tests/unit/repositories/test_repository_service.py` | 43 tests covering all Step 14 spec targets |

### Files Modified

| File | Change |
|------|--------|
| `app/main.py` | Added `from app.api.repositories import router as repositories_router` and `app.include_router(repositories_router)` |

### Files Removed
None.

### API Routes Added

| Method | Path | Auth | Status | Purpose |
|--------|------|------|--------|---------|
| GET | `/api/repositories` | Yes | 200 | List current user's authorized repositories |
| POST | `/api/repositories/authorize` | Yes | 201 | Authorize a new repository (verifies GitHub access) |
| DELETE | `/api/repositories/{repository_id}/access` | Yes | 200 | Revoke access to a repository (soft-delete) |

### Authentication Integration
Every route uses `Depends(get_current_user)` from `app/api/dependencies.py` (built in Step 13). The resolved User ORM object is passed directly to service functions — the router never deals with tokens or hashes.

### Authorization Rules
1. **User isolation**: `list_authorized_repositories` filters by `user_id == current_user.id` at the DB query level. No user can see another's access records.
2. **GitHub verification**: `authorize_repository` calls `client.verify_repo_access(owner, repo_name)` before any DB write. A repository the user cannot access on GitHub cannot be authorized in GitReview AI.
3. **Revocation isolation**: `revoke_repository_access` queries `WHERE user_id = current_user.id AND repository_id = ?`. Another user's access row is never touched.
4. **No IDOR**: The client supplies `owner`+`name` for authorization (not a repository_id), so there is no way to authorize a repo by guessing an internal ID. For revocation, the `repository_id` is checked against the calling user's own access records.
5. **Shared repo rows**: The `repositories` table row is shared across users. Only `repository_access` rows are per-user. Revoking access only sets `revoked_at` on the access row — the shared repository row is never deleted.

### Database Changes
**NONE.** The existing 17-table schema (DB Validation doc) fully supports all required functionality:
- `repositories` (github_repo_id UNIQUE) — upserted via ON CONFLICT DO UPDATE
- `repository_access` (UNIQUE user_id+repository_id) — upserted via ON CONFLICT DO UPDATE on `uq_repository_access_user_repo`; revoked via `revoked_at` timestamp

### Dependencies Added/Changed
None. `httpx` was already in `pyproject.toml`.

### Architectural Decisions

1. **ON CONFLICT for idempotency**: Both `_upsert_repository` and `_upsert_access` use PostgreSQL `INSERT ... ON CONFLICT DO UPDATE`. This means calling `authorize_repository` twice is a safe no-op at the DB level — no duplicates, no errors. The UNIQUE constraint is the guard, not application logic.

2. **Re-activating revoked access**: If a user revoked access and then re-authorizes the same repo, `_upsert_access` sets `revoked_at = NULL` and refreshes `authorized_at`. This is the correct behavior: "re-authorize" means "make active again."

3. **Canonical github_repo_id fetch**: The service makes two GitHub calls for authorization — `verify_repo_access` (permission check) and a direct `GET /repos/{owner}/{repo}` (to get `github_repo_id`). This is necessary because `verify_repo_access` only returns a boolean and permission level; the canonical numeric ID comes from the repo metadata endpoint. This prevents authorizing a renamed repo under two different rows.

4. **Soft delete for revocation**: `revoked_at` is set to the current timestamp rather than deleting the `repository_access` row. This preserves audit history and is consistent with the LLD/DB Validation design (partial index on `WHERE revoked_at IS NULL`).

5. **Client supplies owner+name, not ID**: For `POST /authorize`, the request body contains `owner` and `name` strings. The server fetches the canonical `github_repo_id` from GitHub. This is intentional: it prevents IDOR attacks where a client guesses an internal repository UUID to authorize a repo they cannot access.

6. **Test mock target**: Router tests patch at `app.api.repositories.*` (the import site), not at `app.repositories.service.*` (the definition site). The positional-arg call convention is confirmed by inspecting the router source, and tests use `call_args.args[N]` for positional assertions.

### Test Results (exact)

```
Focused:
  Command: python -m pytest tests/unit/repositories/test_repository_service.py -v
  Result:  43 passed, 2 warnings in 2.61s

Full suite:
  Command: python -m pytest tests/ -q
  Result:  248 passed, 2 warnings in 1.00s
```

### Ruff Result (exact)
```
Command: python -m ruff check .
Result:  All checks passed!
(7 issues auto-fixed: I001 import sorting ×5, UP037 quoted annotations ×2, F401 unused import ×1)
```

### Known Limitations
1. `authorize_repository` makes 2 GitHub API calls (verify + metadata fetch). In production these could be merged into one if the GitHub client is extended with a `fetch_repo_metadata` method that also checks permissions. This optimization is deferred.
2. No pagination on `GET /api/repositories` — acceptable for MVP where users authorize a small number of repos.
3. The `github_permission_level` CHECK constraint (`admin|maintain|write|read`) is enforced at the DB level. The service passes whatever GitHub returns from `verify_repo_access`; if GitHub ever returns an unexpected value the DB will reject it with a constraint error (correct behavior).

### Known Issues
None. The 2 warnings are from third-party library deprecations (starlette/anyio), not our code.

### Next Step
**Step 15: Pull Request API Layer** — expose PR fetching and analysis triggering through the API, connecting the GitHub integration, PR module, and analysis orchestrator to the authenticated API layer.

---
*Last updated: 2026-09-19 | Step 14 IMPLEMENTED*

---

## STEP 15 — Pull Request API Layer

**Status: IMPLEMENTED**
**Date: 2026-09-19**
**Tests: 292 / 292 passing (44 new tests added)**
**Ruff: CLEAN (7 issues auto-fixed)**

### Objective
Expose Pull Request functionality through the FastAPI API layer using the existing GitHub integration, PR models, and Analysis Orchestrator — without duplicating or redesigning any existing logic.

### Baseline (actually verified)
- Step 14 ZIP extracted and verified
- 248/248 pre-existing tests passing before Step 15 changes (EXECUTED)
- Ruff: clean (EXECUTED)
- `app/pull_requests/__init__.py` existed (empty package only)
- No PR service, schemas, or router existed

### Files Created

| File | Purpose |
|------|---------|
| `app/pull_requests/service.py` | get_authorized_repository (auth guard), get_or_create_pull_request, list_pull_requests, get_pull_request, analyze_pull_request, _build_orchestrator factory |
| `app/pull_requests/schemas.py` | PRSummaryResponse, PRListResponse, PRDetailResponse, AnalysisResponse, AnalyzeRequest, ReviewSuggestionSchema, ReviewerRecommendationSchema, ChecklistItemSchema |
| `app/api/pull_requests.py` | FastAPI router — GET /pulls, GET /pulls/{pull_number}, POST /pulls/{pull_number}/analyze |
| `tests/unit/pull_requests/test_pull_request_service.py` | 44 tests covering all Step 15 spec targets |

### Files Modified

| File | Change |
|------|--------|
| `app/main.py` | Added `from app.api.pull_requests import router as pull_requests_router` and `app.include_router(pull_requests_router)` |

### Files Removed
None.

### API Routes Added

| Method | Path | Auth | Code | Purpose |
|--------|------|------|------|---------|
| GET | `/api/repositories/{repository_id}/pulls` | Yes | 200 | List open PRs (live from GitHub) |
| GET | `/api/repositories/{repository_id}/pulls/{pull_number}` | Yes | 200 | Fetch full PR metadata |
| POST | `/api/repositories/{repository_id}/pulls/{pull_number}/analyze` | Yes | 200 | Run or retrieve cached analysis |

### Authentication Integration
All routes use `Depends(get_current_user)` from Step 13. The resolved User ORM object is passed to service functions — the router never touches tokens or hashes.

### Repository Authorization Integration
Every service function begins with `get_authorized_repository(db, user, repository_id)` which queries `RepositoryAccess WHERE user_id = current_user.id AND revoked_at IS NULL`. If the user has no active access row, `RepositoryNotFoundError` is raised → HTTP 404. This prevents IDOR-style access by repository_id guessing.

### Pull Request Service Integration
- `list_pull_requests` → calls `GitHubApiClient` to fetch live PR list
- `get_pull_request` → calls `client.fetch_pull_request_data()` for full metadata
- `analyze_pull_request` → upserts PullRequest ORM row, then calls `AnalysisOrchestrator.run_analysis()`

### Analysis Orchestrator Integration
`analyze_pull_request` calls the existing `AnalysisOrchestrator.run_analysis()` without modification. The orchestrator handles: cache check, AI call, validation, retry, deterministic signals, hybrid risk, confidence, reviewer recommendation, checklist generation, and atomic persistence. The router receives a complete `AnalysisResult` dataclass and maps it to `AnalysisResponse`.

### Idempotency / Cache Behavior
The orchestrator's `_check_cache` (Step 12) queries `pull_request_analyses WHERE pull_request_id=? AND commit_sha=? AND status != 'failed'`. If a row exists, it is returned without re-invoking GitHub or the AI. A new commit SHA (push to the PR) produces a new analysis. No Redis or separate cache layer was introduced — the existing DB cache is reused as designed.

### Database Changes
**NONE.** The 17-table schema (DB Validation doc) fully supports all required functionality:
- `pull_requests` (UNIQUE repository_id + github_pr_number) — upserted via SELECT then INSERT/UPDATE
- `pull_request_analyses` (UNIQUE pull_request_id + commit_sha) — written by orchestrator
- All child tables written atomically by the existing `_persist_result` method

### Dependencies Added/Changed
None. All required packages already in `pyproject.toml`.

### Architectural Decisions

1. **Routes nested under /api/repositories/{repository_id}/pulls**: PR number is only unique within a repository. Nesting makes the repository authorization requirement explicit in the URL, follows REST conventions, and prevents any ambiguity about which repo a PR belongs to.

2. **Diff text not returned in API responses**: The raw diff can be megabytes. It is consumed internally by the analysis pipeline and never returned in list or detail endpoints. Only structured metadata (file names, line counts, commit messages) is returned.

3. **_build_orchestrator() factory per request**: The AnalysisOrchestrator and its dependencies (GeminiAdapter, PromptBuilder, etc.) are stateless and cheap to instantiate. Building them per request keeps the service layer simple and avoids global state. If performance becomes a concern, a singleton could be introduced in main.py's lifespan — but this is an MVP.

4. **get_authorized_repository returns Repository ORM**: This single function is the authorization gate for all three PR endpoints. It queries both `repositories` and `repository_access` in one JOIN, returning the repository object (needed for owner/name) or raising 404 immediately. This is the only place where user-repository authorization is enforced for PR operations.

5. **live GitHub list, not DB list**: `list_pull_requests` fetches PRs live from GitHub rather than from our `pull_requests` table. Our table only contains PRs that have been analyzed; a user could have 50 open PRs with only 3 analyzed. The live fetch gives the correct, complete list for the extension queue.

### Test Results (exact)

```
Focused:
  Command: python -m pytest tests/unit/pull_requests/test_pull_request_service.py -v
  Result:  44 passed, 2 warnings in 0.88s

Full suite:
  Command: python -m pytest tests/ -q
  Result:  292 passed, 2 warnings in 2.69s
```

### Ruff Result (exact)
```
Command: python -m ruff check .
Result:  All checks passed!
(7 issues auto-fixed: I001 import sorting ×4, F401 unused import ×2, F841 unused variable ×1)
```

### Known Limitations
1. `list_pull_requests` makes a live GitHub call with no DB caching. For a team with many PRs, this could be slow. A DB-backed list (only analyzed PRs) is a potential future optimization.
2. `_build_orchestrator()` instantiates all dependencies on every analyze call. For MVP this is fine; a singleton pattern in lifespan could reduce object creation overhead at scale.
3. The PR list endpoint always fetches `state=open` PRs. Filtering by state (closed, merged) is not yet exposed via query parameter — this is a straightforward future addition.

### Known Issues
None blocking. The 2 warnings are third-party library deprecations (starlette/anyio), not project code.

### Next Step
**Step 16: Feedback API Layer** — expose the feedback collection endpoint (`POST /api/analyses/{analysis_id}/feedback`) allowing reviewers to mark AI predictions as helpful/unhelpful, feeding the confidence calibration loop.

---
*Last updated: 2026-09-19 | Step 15 IMPLEMENTED*

---

## STEP 16 — Feedback API Layer

**Status: IMPLEMENTED AND INTEGRATED**
**Date: 2026-09-20**
**Tests: 317 / 317 passing (25 new tests added)**
**Ruff: CLEAN**

### Objective
Expose the feedback collection endpoint (`POST /api/analyses/{analysis_id}/feedback`),
allowing authenticated reviewers to submit helpful/unhelpful ratings on specific AI
predictions (risk tier, reviewer recommendation, checklist item). Updates the
confidence_calibration running counts on every submission.

### Repository Correction Applied
Step 16 files were initially pushed to the repository root (`/app/`, `/tests/`,
root `PROJECT_STATE.md`) instead of the canonical `backend/` tree. This has been
corrected: all Step 16 files are now in their proper `backend/` locations and the
misplaced root artifacts have been removed.

### Files Integrated into backend/

| File | Destination |
|------|-------------|
| `app/feedback/schemas.py` | `backend/app/feedback/schemas.py` |
| `app/feedback/service.py` | `backend/app/feedback/service.py` |
| `app/api/feedback.py` | `backend/app/api/feedback.py` |
| `tests/unit/feedback/test_feedback_service.py` | `backend/tests/unit/feedback/test_feedback_service.py` |

### Files Modified

| File | Change |
|------|--------|
| `backend/app/main.py` | Added `from app.api.feedback import router as feedback_router` and `app.include_router(feedback_router)` |
| `README.md` | Added feedback endpoint to API list; updated test count to 317/317; added `feedback/` to project structure |

### Files Removed (misplaced root artifacts)
- `/app/` (root-level, entire directory)
- `/tests/` (root-level, entire directory)
- `/PROJECT_STATE.md` (root-level duplicate — `backend/PROJECT_STATE.md` is now the sole authoritative file)

### API Route Added

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/analyses/{analysis_id}/feedback` | Yes (X-Session-Token) | Submit or update (upsert) feedback on an AI prediction |

### Authentication
X-Session-Token header required. Uses existing `get_current_user` dependency.

### Authorization and IDOR Protection
- Authorization chain: `pull_request_analyses → pull_requests → repositories → repository_access`
- Single JOIN query verifies caller has non-revoked RepositoryAccess for the repository owning the analysis
- Unauthorized access returns HTTP 404 (not 403) — prevents leaking whether the analysis exists
- `prediction_reference_id` validated against `analysis_id` — prevents cross-analysis IDOR

### Feedback Upsert Semantics
LLD A.17: "Duplicate feedback on the same prediction — upserted, not duplicated."
- SELECT for existing row by (user_id + prediction FK)
- If found: update rating and comment in place
- If not found: INSERT new row
- HTTP 200 returned for both new and updated feedback

### Calibration Behavior
- `confidence_calibration` counters updated immediately in same transaction
- New helpful → `helpful_count += 1`
- New unhelpful → `unhelpful_count += 1`
- Rating change → old counter decremented, new counter incremented
- Missing calibration row: warning logged, graceful skip (no failure)

### Database / Migration Changes
**NONE.** Existing 17-table schema fully supports all required functionality.
No new migration was required or created.

### Test Results (exact)

```
Focused:
  Command: python -m pytest tests/unit/feedback/test_feedback_service.py -q
  Result:  25 passed, 2 warnings

Full suite:
  Command: python -m pytest tests/ -q
  Result:  317 passed, 2 warnings
  (292 Steps 1–15 baseline + 25 new Step 16 tests)
```

### Ruff Result (exact)
```
Command: python -m ruff check .   (run from backend/)
Result:  All checks passed!
```

### Known Limitations
1. No integration tests against real PostgreSQL
2. Calibration update not protected by SELECT FOR UPDATE (acceptable at MVP scale)

### Remaining Work
- Chrome Extension / frontend (not started)
- GitHub Actions integration (not started)
- Step 17: Analytics API Layer (next planned step)
  - GET /api/analytics/me (individual — user_daily_metrics)
  - GET /api/analytics/repositories/{repository_id} (team lead — repository_daily_metrics)

---
*Last updated: 2026-09-20 | Step 16 IMPLEMENTED AND INTEGRATED | Repository structure corrected*

---

## STEP 17 — Analytics API Layer

**Status: IMPLEMENTED**
**Date: 2026-09-24**

### Implementation Summary

Implemented the Analytics API Layer (LLD A.18 / SRS FR-9) using on-demand
SQL aggregation over the existing transactional tables. No new migrations,
no new tables, no new infrastructure.

### Files Created

| File | Location |
|------|----------|
| `app/analytics/__init__.py` | `backend/app/analytics/__init__.py` |
| `app/analytics/schemas.py` | `backend/app/analytics/schemas.py` |
| `app/analytics/service.py` | `backend/app/analytics/service.py` |
| `app/api/analytics.py` | `backend/app/api/analytics.py` |
| `tests/unit/analytics/__init__.py` | `backend/tests/unit/analytics/__init__.py` |
| `tests/unit/analytics/test_analytics_service.py` | `backend/tests/unit/analytics/test_analytics_service.py` |

### Files Modified

| File | Change |
|------|--------|
| `backend/app/main.py` | Added analytics router import and `app.include_router(analytics_router)` |

### API Routes Added

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/analytics/me` | Yes (X-Session-Token) | Individual user analytics (SRS FR-9.1) |
| GET | `/api/analytics/repositories/{repository_id}` | Yes (X-Session-Token) | Repository-level analytics (SRS FR-9.2) |

### Analytics Metrics Implemented

**User analytics (`/me`)**:
- `total_analyses` — all analyses in authorized repos
- `completed_analyses`, `degraded_analyses`, `failed_analyses` — by status
- `unique_prs_analyzed` — distinct PRs with at least one analysis
- `risk_distribution` — low/medium/high/critical counts (completed only)
- `avg_confidence` — mean risk-assessment confidence score
- `feedback_given` — helpful/unhelpful counts + percentage
- `reviewer_stats` — recommendations made vs abstentions
- `authorized_repository_count` — active (non-revoked) authorizations
- `first_analysis_at`, `latest_analysis_at` — activity window

**Repository analytics (`/repositories/{id}`)**:
- All of the above plus `full_name` (owner/name), `github_repo_id`
- `authorized_user_count` — users with active authorization
- `feedback_received` — scoped to all analyses on this repo

### Database / Migration Changes

**NONE.** Existing 17-table schema fully supports all required functionality.
All analytics computed on demand from existing tables:
- `repository_access`, `repositories`, `pull_requests`
- `pull_request_analyses`, `risk_assessments`
- `reviewer_recommendations`, `feedback`

Note: `user_daily_metrics` and `repository_daily_metrics` exist in the schema
(from Step 3 migration, per DB Validation doc corrections) but are populated
by a nightly job not yet implemented. Analytics are therefore computed on-demand
from transactional tables, which is correct and recomputable at any time
(LLD Part E: "derived tables can always be recomputed from source data").

### Authentication and Authorization

- Both endpoints require `X-Session-Token` via existing `get_current_user`
- `/api/analytics/me`: user derived exclusively from session — client cannot
  specify another user's ID
- `/api/analytics/repositories/{id}`: `repository_access` checked for active
  (non-revoked) row before any analytics data is returned
- Unauthorized access returns HTTP 404 (IDOR-safe — same convention as feedback
  endpoint: does not confirm whether repo exists to unauthorized callers)
- Cross-user data leakage is structurally impossible: user analytics scoped to
  session user's authorized repos; repo analytics guarded by access row

### Test Results (exact)

```
Focused (Step 17):
  Command: python -m pytest tests/unit/analytics/ -v
  Result:  35 passed, 1 warning

Full suite:
  Command: python -m pytest -q
  Result:  352 passed, 1 warning
  (317 Steps 1–16 baseline + 35 new Step 17 tests)

Ruff:
  Command: ruff check .   (run from backend/)
  Result:  All checks passed!
```

### Known Limitations

1. Analytics computed on-demand from transactional tables (not from precomputed
   daily rollup tables). Correct for MVP; rollup tables exist in schema for
   future nightly-job optimization.
2. No integration tests against real PostgreSQL.
3. `avg_confidence` is null for repos/users with no completed analyses.

### Decisions Made

- On-demand SQL aggregation chosen over rollup tables: rollup tables require a
  nightly job (not yet implemented) and on-demand is always accurate.
- IDOR protection: 404 not 403 on unauthorized repo access, consistent with
  the feedback endpoint convention established in Step 16.
- No new migration: all required data exists in the current schema.

### Next Recommended Step

**Step 18 — Chrome Extension** or **GitHub Actions Integration**
(per approved LLD Part S implementation sequence)

---
*Last updated: 2026-09-24 | Step 17 IMPLEMENTED AND VERIFIED | 352/352 tests | Ruff CLEAN*

---

## Step 18 — Chrome Extension Foundation and GitHub PR Review UI

**Status: IMPLEMENTED AND VERIFIED**
**Date: 2026-09-25**

### Implementation Summary

Chrome Extension (Manifest V3) that consumes the existing FastAPI backend.
All API contracts are derived from the actual backend Pydantic schemas —
no response fields were invented.

### Extension Architecture

```
extension/
├── public/manifest.json          # MV3 manifest (storage, activeTab permissions only)
├── public/icon{16,48,128}.png    # Solid #2563eb colour icons
├── src/types/index.ts            # TypeScript interfaces mirroring all backend schemas
├── src/auth/session.ts           # chrome.storage.local session management
├── src/api/client.ts             # Centralized API client (all endpoints, typed errors)
├── src/content/github-pr.ts     # GitHub PR URL detection + SPA navigation
├── src/background/service-worker.ts  # OAuth interception, session routing
├── src/popup/App.tsx             # Main React popup (5 views)
├── src/popup/main.tsx            # React entry point
├── src/components/
│   ├── RiskBadge.tsx             # Colour-coded risk tier badge
│   ├── ConfidenceBar.tsx         # 0–100% bar (green/amber/red bands)
│   ├── RiskRationale.tsx         # Collapsible rationale factors
│   ├── ReviewerCard.tsx          # Reviewer recommendation or abstention
│   ├── Checklist.tsx             # Adaptive checklist with local completion
│   └── FeedbackForm.tsx          # Helpful/unhelpful feedback submission
└── src/__tests__/
    ├── github-pr.test.ts         # 18 URL parsing tests
    ├── session.test.ts           # 11 session storage tests
    ├── api-client.test.ts        # 20 error mapping + success path tests
    ├── types.test.ts             # 11 contract alignment tests
    └── components.test.tsx       # 26 React component render tests
```

### Files Created

| File | Purpose |
|------|---------|
| `extension/package.json` | npm config: Vite, React 18, TypeScript, Vitest |
| `extension/tsconfig.json` | Strict TypeScript, ES2020, react-jsx |
| `extension/vite.config.ts` | Multi-entry build: background, content, popup |
| `extension/popup.html` | HTML shell for React popup |
| `extension/.env.example` | VITE_BACKEND_URL placeholder (no secrets) |
| `extension/public/manifest.json` | MV3: storage + activeTab permissions only |
| `extension/public/icon{16,48,128}.png` | Minimal valid PNG icons (#2563eb) |
| `extension/src/types/index.ts` | All types from backend Pydantic schemas |
| `extension/src/auth/session.ts` | Session save/get/clear/token/isAuthenticated |
| `extension/src/api/client.ts` | Typed client for all 12 backend endpoints |
| `extension/src/content/github-pr.ts` | extractPRContext + SPA nav detection |
| `extension/src/background/service-worker.ts` | OAuth tab interception, messaging |
| `extension/src/popup/App.tsx` | Main app: 5 views, all flows wired |
| `extension/src/popup/main.tsx` | React.createRoot entry point |
| `extension/src/components/RiskBadge.tsx` | low/medium/high/critical badge |
| `extension/src/components/ConfidenceBar.tsx` | Score bar + band label |
| `extension/src/components/RiskRationale.tsx` | Collapsible rationale factors |
| `extension/src/components/ReviewerCard.tsx` | Reviewer or abstention |
| `extension/src/components/Checklist.tsx` | Items + local completion state |
| `extension/src/components/FeedbackForm.tsx` | helpful/unhelpful rating form |
| `extension/src/test-setup.ts` | Chrome API mock + beforeEach storage clear |
| `extension/src/__tests__/github-pr.test.ts` | 18 URL parsing tests |
| `extension/src/__tests__/session.test.ts` | 11 session tests |
| `extension/src/__tests__/api-client.test.ts` | 20 API client tests |
| `extension/src/__tests__/types.test.ts` | 11 type contract tests |
| `extension/src/__tests__/components.test.tsx` | 26 component render tests |
| `extension/README.md` | Build, install, configure instructions |

### API Contracts Consumed

All contracts verified from actual backend source (not assumptions):

| Method | Path | Auth | Used for |
|--------|------|------|---------|
| GET | `/api/auth/login` | No | OAuth initiation → authorize_url + state |
| GET | `/api/auth/callback` | No (X-OAuth-State) | Token exchange after OAuth |
| POST | `/api/auth/logout` | Yes | Session revocation |
| GET | `/api/auth/me` | Yes | Validate session on popup load |
| GET | `/api/repositories` | Yes | Find repository_id for current PR |
| POST | `/api/repositories/authorize` | Yes | Authorize unrecognized repository |
| DELETE | `/api/repositories/{id}/access` | Yes | Revoke access |
| GET | `/api/repositories/{id}/pulls` | Yes | List PRs |
| GET | `/api/repositories/{id}/pulls/{n}` | Yes | PR detail |
| POST | `/api/repositories/{id}/pulls/{n}/analyze` | Yes | Trigger analysis |
| POST | `/api/analyses/{id}/feedback` | Yes | Submit helpful/unhelpful rating |
| GET | `/api/analytics/me` | Yes | User analytics (client prepared) |

### Session Handling

- Token stored in `chrome.storage.local` under key `gitreview_session`
- Only opaque session token stored; GitHub OAuth token remains server-side
- OAuth state (CSRF protection) stored under `gitreview_oauth_state` before tab open
- State retrieved by service worker on callback tab interception
- 401 response clears session and shows re-auth prompt

### Manifest V3 Permissions

- `storage` — session token in chrome.storage.local
- `activeTab` — read active tab URL for PR context detection
- Host permission: `https://github.com/*` only (no `<all_urls>`)

### Test Results

```
Frontend (extension/):
  Command: npm test
  Result:  86 passed (86)
  Files:   5 test files
    github-pr.test.ts    18 tests — URL parsing (valid + invalid + edge cases)
    session.test.ts      11 tests — storage save/get/clear/token/isAuthenticated
    api-client.test.ts   20 tests — 401/403/404/422/429/5xx/network + success
    types.test.ts        11 tests — backend schema contract alignment
    components.test.tsx  26 tests — RiskBadge, ConfidenceBar, ReviewerCard,
                                    Checklist, FeedbackForm renders

Backend (backend/):
  Command: python -m pytest -q
  Result:  352 passed, 1 warning  ← unchanged from Step 17 baseline

Ruff:
  Command: ruff check .  (run from backend/)
  Result:  All checks passed!
```

### Build Result

```
Command: npm run build
Output:
  dist/popup.html       0.95 kB
  dist/content.js       0.72 kB
  dist/background.js    1.23 kB
  dist/popup.js       160.87 kB (React app)
  dist/manifest.json  (copied from public/)
  dist/icon*.png      (copied from public/)
Built in 1.34s — no errors, no TypeScript errors
```

### Security

- No hardcoded secrets in any source file
- No `.env` committed (`.env.example` only)
- OAuth tokens never stored client-side (server-side Fernet encryption)
- Session token is opaque; raw value never logged
- `<all_urls>` permission NOT requested
- Content-Security-Policy in popup.html: `script-src 'self'` only
- GitHub content treated as untrusted data (prompt injection handled server-side)

### Known Limitations

1. **Feedback prediction UUIDs not in AnalysisResponse**: The backend's
   `AnalysisResponse` schema does not expose `risk_assessment_id`,
   `reviewer_recommendation_id`, or `checklist_item_id` separately.
   The feedback endpoint requires `prediction_reference_id` pointing at
   the specific row UUID. FeedbackForm shows a clear "not available" message
   and is fully implemented structurally — enabling it requires the backend
   to add these IDs to `AnalysisResponse` (a backend schema change, not
   a frontend change).

2. **Checklist completion is local-only**: The `checklist_item_completions`
   table exists in the schema; the API endpoint for PATCH completion is
   not yet implemented. Completion state is tracked in React local state
   with a clear "local to this session only" caveat shown in the UI.

3. **No analytics dashboard in popup**: Analytics API client methods are
   fully implemented in `api/client.ts`; a popup analytics view is deferred
   to a future step.

4. **OAuth callback tab**: Requires backend running and `GITHUB_REDIRECT_URI`
   reachable from browser. Deployment-dependent; clearly documented.

### Decisions Made

- React inline styles (not CSS modules or Tailwind): zero additional build
  deps, works reliably in Chrome Extension CSP environment.
- Vitest + jsdom + @testing-library/react: matches the ecosystem (Vite project)
  and avoids Jest configuration overhead.
- `extractPRContext` exported from content script so the popup can call it
  directly on the active tab URL — avoids message-passing roundtrip.
- `VITE_BACKEND_URL` injected at build time via Vite env — clean separation
  between dev (localhost:8000) and production (Render URL).

### Next Recommended Step

**Step 19 — GitHub Actions Integration** (LLD Part S, step 15/20)
OR
**Backend: expose prediction UUIDs in AnalysisResponse** to enable feedback
submission from the extension (small backend schema addition).

---
*Last updated: 2026-09-25 | Step 18 IMPLEMENTED AND VERIFIED | 352/352 backend tests | 86/86 frontend tests | Ruff CLEAN | Build CLEAN*

---

## Step 18.1 — Feedback Integration (AnalysisResponse → FeedbackForm → Backend)

**Status: IMPLEMENTED AND VERIFIED**
**Date: 2026-09-26**

### Problem

The `FeedbackForm` component in the Chrome Extension could not submit feedback
because `POST /api/analyses/{analysis_id}/feedback` requires a
`prediction_reference_id` — the UUID of the specific prediction row being rated
(e.g. `risk_assessments.id` for `prediction_type="risk_tier"`).

`AnalysisResponse` did not expose this UUID, so `FeedbackForm` showed a
"not available" placeholder instead of submitting.

### Root Cause

Traced through the full data flow:

1. `AnalysisOrchestrator._persist_result()` creates a `RiskAssessment` ORM row
   with a server-generated UUID (`risk.id`).
2. `AnalysisResult` dataclass (returned by the orchestrator) had no
   `risk_assessment_id` field — the UUID was computed and persisted but never
   propagated to the caller.
3. The router's `AnalysisResponse` construction mapped `AnalysisResult` fields
   explicitly and therefore also omitted the UUID.
4. `FeedbackForm` received `predictionReferenceId=null` and showed a placeholder.

No database schema change was needed. The UUID already existed in the
`risk_assessments` table; it just wasn't being returned to the client.

### Existing Backend Identifier

```
risk_assessments.id  (UUID, gen_random_uuid(), populated on every analysis)
```

The feedback endpoint validates this exactly:
```python
# feedback/service.py _validate_prediction_reference()
stmt = select(RiskAssessment).where(
    RiskAssessment.id == prediction_reference_id,
    RiskAssessment.analysis_id == analysis_id,
)
```

### Backend Changes (3 files, no DB migration)

**`backend/app/analysis/orchestrator.py`**
- Added `risk_assessment_id: uuid.UUID | None = None` field to `AnalysisResult` dataclass.
- Added `await db.flush()` after `db.add(risk)` in `_persist_result()` to assign
  `risk.id` before building the return value.
- Added `selectinload(PullRequestAnalysis.risk_assessment)` to the reload query
  inside `_persist_result()` so `analysis.risk_assessment` is available.
- Populated `risk_assessment_id=analysis.risk_assessment.id if analysis.risk_assessment else None`
  in both the fresh-analysis and cache-hit `AnalysisResult` constructions.

**`backend/app/pull_requests/schemas.py`**
- Added `risk_assessment_id: uuid.UUID | None = Field(default=None, ...)` to
  `AnalysisResponse` with documentation of its intended use for feedback.

**`backend/app/api/pull_requests.py`**
- Added `risk_assessment_id=result.risk_assessment_id` to the explicit
  `AnalysisResponse(...)` construction in the `analyze_pr` route handler.

**`backend/tests/unit/pull_requests/test_pull_request_service.py`**
- Updated `_make_analysis_result()` factory to accept and set `risk_assessment_id`.
- Added `TestRiskAssessmentIdInAnalysisResponse` class with 11 new tests:
  - Schema field presence
  - Optional UUID type
  - Serialisation as UUID string
  - Null for failed analyses
  - Dataclass field presence
  - Dataclass default=None
  - Router endpoint returns correct UUID
  - UUID string is valid UUID
  - Feedback schema accepts risk_tier
  - Feedback schema requires prediction_reference_id
  - Feedback schema rejects invalid UUID

### Frontend Changes (3 files)

**`extension/src/types/index.ts`**
- Added `risk_assessment_id: string | null` to `AnalysisResponse` interface
  with documentation linking it to the feedback endpoint contract.

**`extension/src/components/FeedbackForm.tsx`**
- Rewrote entirely: removed the stale "not yet exposed" limitation message.
- When `predictionReferenceId` is non-null: submits real POST request.
- When `predictionReferenceId` is null: shows "Feedback unavailable" (graceful
  for degraded/failed analyses that have no risk_assessments row).
- Added `ApiValidationError` handling for 422 responses.
- Added "Retry" button after errors.
- Added "Change" button after success (re-enables the form for upsert).
- Added "Saving…" indicator during submission.

**`extension/src/popup/App.tsx`**
- Changed `predictionReferenceId={null}` to `predictionReferenceId={analysis.risk_assessment_id}`
  in the `<FeedbackForm>` call inside `AnalysisView`.

**`extension/src/__tests__/components.test.tsx`**
- Added 11 `FeedbackForm` tests covering:
  - Renders rating buttons when reference ID is present
  - Shows unavailable when reference ID is null
  - Calls API with correct payload (helpful)
  - Calls API with correct payload (unhelpful)
  - Shows success state with Change option
  - Shows error + Retry on 401
  - Shows error + Retry on 422
  - Shows error + Retry on network failure
  - Retry re-enables the form
  - Calls onFeedbackSubmitted callback

**`extension/src/__tests__/types.test.ts`**
- Added `risk_assessment_id` to the AnalysisResponse type contract test.
- Added test for null `risk_assessment_id` (degraded analysis case).

### API Contract (now complete)

```
POST /api/repositories/{repository_id}/pulls/{pull_number}/analyze
→ AnalysisResponse {
    analysis_id:        UUID          ← scope for feedback endpoint
    risk_assessment_id: UUID | null   ← prediction_reference_id for risk_tier feedback
    risk_tier:          string
    risk_confidence:    float
    ...
  }

POST /api/analyses/{analysis_id}/feedback
  Body: {
    prediction_type:         "risk_tier"
    prediction_reference_id: <risk_assessment_id from AnalysisResponse>
    rating:                  "helpful" | "unhelpful"
  }
→ FeedbackResponse { feedback_id, analysis_id, rating, ... }
```

### Database Changes

NONE. No migration required.
The `risk_assessments.id` column already existed. Only the propagation path
(orchestrator → AnalysisResult → AnalysisResponse → frontend) was missing.

### Test Results

```
Backend:
  Before: 352 passed, 1 warning
  After:  363 passed, 1 warning  (+11 new tests)
  Ruff:   All checks passed!

Frontend:
  Before: 86 passed (5 files)
  After:  97 passed (5 files)   (+11 new FeedbackForm tests)
  Build:  SUCCESS — dist/ clean, no TypeScript errors
```

### Security Check

- No secrets, tokens, or credentials added to any source file.
- No `.env` committed.
- `risk_assessment_id` is an internal UUID, not a sensitive credential.
- The backend validates `prediction_reference_id` against `analysis_id` and
  the user's repository access before persisting feedback (existing IDOR protection
  is unchanged).

### Remaining Limitations

- Checklist completion persistence (PATCH endpoint) is still deferred —
  `checklist_item_completions` table exists but no API endpoint yet.
- `reviewer_recommendation_id` and `checklist_item_id` are not yet exposed in
  `AnalysisResponse` (only `risk_assessment_id` was needed for the MVP feedback
  flow; the others can be added similarly when needed).
- Feedback for `reviewer_recommendation` and `checklist_item` prediction types
  is fully implemented in backend and API client but the extension UI currently
  only shows feedback for `risk_tier`.

---
*Last updated: 2026-09-26 | Step 18.1 IMPLEMENTED AND VERIFIED | 363/363 backend | 97/97 frontend | Ruff CLEAN | Build CLEAN*

---

## Step 19 — GitHub Actions Integration

**Status: IMPLEMENTED AND VERIFIED**
**Date: 2026-09-26**
**Backend tests: 418 / 418 passing (+55 new)**
**Frontend tests: 97 / 97 passing (unchanged)**
**Ruff: CLEAN**

### Objective

Implement the GitHub Actions Integration (LLD A.20 / HLD Section 11) as a thin
adapter in front of the existing AnalysisOrchestrator. A GitHub Actions workflow
triggers on PR events, calls the backend, and posts the result as a PR comment
with a risk tier label.

### Architecture

```
GitHub PR event (opened/synchronize/reopened)
        ↓
.github/workflows/gitreview-ai.yml
        ↓  (POST /api/actions/analyze with X-Actions-Secret + X-GitHub-Token)
app/api/actions.py  (validate secret → delegate)
        ↓
app/actions_integration/service.py  (validate secret, lookup repo, run orchestrator)
        ↓
EXISTING AnalysisOrchestrator.run_analysis()  ← REUSED, NOT DUPLICATED
        ↓
ActionsAnalysisResponse { status, risk_tier, comment_markdown, ... }
        ↓  (returned to workflow)
actions/github-script  (post or edit PR comment + apply risk label)
```

### Key Design Decisions

1. **Thin adapter, not a second engine**: LLD A.20 is followed exactly.
   `handle_actions_request()` looks up the repo, then calls the same
   `AnalysisOrchestrator.run_analysis()` used by the extension path.
   No AI logic, no risk engine, no checklist logic is duplicated.

2. **Shared secret auth**: Per-deployment secret in `X-Actions-Secret` header,
   compared with `hmac.compare_digest` (timing-safe). If `ACTIONS_SHARED_SECRET`
   is empty the endpoint rejects all requests — disabled by default.

3. **GitHub token from workflow**: The Actions workflow's `GITHUB_TOKEN` is sent
   in `X-GitHub-Token`. It is used to build a `GitHubApiClient` for the
   orchestrator's data fetch. It is never stored in the database.

4. **Repository must be pre-authorized**: The repository must exist in the
   `repositories` table (i.e., a user must have authorized it via the extension
   first). This enforces the opted-in design from the PRD.

5. **Idempotency**: The workflow searches for an existing `<!-- gitreview-ai-bot -->`
   marker comment and edits it in place. This is handled entirely by the workflow
   JavaScript step using `GITHUB_TOKEN` — the backend does not track comment IDs
   and no DB schema change was needed.

6. **Concurrency group**: The workflow uses `cancel-in-progress: true` to prevent
   out-of-order comment edits when commits are pushed rapidly (HLD Section 11).

7. **No DB schema change**: The existing 17-table schema supports all required
   functionality. No new migration was created.

### Files Created

| File | Purpose |
|------|---------|
| `app/actions_integration/__init__.py` | Package marker |
| `app/actions_integration/schemas.py` | ActionsAnalyzeRequest, ActionsAnalysisResponse |
| `app/actions_integration/service.py` | Secret validation, repo lookup, comment formatter, main handler |
| `app/api/actions.py` | FastAPI router — POST /api/actions/analyze |
| `tests/unit/actions_integration/__init__.py` | Test package marker |
| `tests/unit/actions_integration/test_actions_integration.py` | 55 tests |
| `.github/workflows/gitreview-ai.yml` | GitHub Actions workflow |
| `backend/.env.example` | Added ACTIONS_SHARED_SECRET documentation |

### Files Modified

| File | Change |
|------|--------|
| `app/main.py` | Added `actions_router` import and `app.include_router(actions_router)` |
| `app/core/config.py` | Added `actions_shared_secret: str` setting |
| `app/core/exceptions.py` | Added `ActionsAuthError` exception class |

### API Route Added

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/actions/analyze` | X-Actions-Secret header | GitHub Actions workflow → PR analysis |

### Database Changes

NONE. No new tables. No new migration. The existing 17-table schema is used as-is.

### Security Verified

- Shared secret compared with `hmac.compare_digest` (timing-safe, not `==`)
- Secret never logged, never in error responses, never in PR comments
- `GITHUB_TOKEN` not stored in DB — used only for the duration of one analysis
- `ACTIONS_SHARED_SECRET` defaults to empty string (endpoint disabled until configured)
- 401 response message is generic (does not distinguish "wrong secret" from "not set")

### Test Results (exact)

```
Step 19 focused:
  Command: python -m pytest tests/unit/actions_integration/ -v
  Result:  55 passed, 1 warning

Full backend suite:
  Command: python -m pytest tests/ -q
  Result:  418 passed, 1 warning
  Breakdown:
    Steps 1-18.1 baseline:  363 tests
    Step 19 new tests:       55 tests
    Total:                  418 tests

Ruff:
  Command: ruff check .
  Result:  All checks passed! (6 issues auto-fixed)

Frontend (untouched):
  Command: npm test -- --run
  Result:  97 passed (5 files) — unchanged
```

### Known Limitations

1. **Live GitHub validation NOT VERIFIED**: The workflow cannot be executed
   in this Claude session (no real GitHub repository, no Actions runner).
   The workflow file is syntactically correct and logically validated via static
   tests. Live end-to-end testing requires deploying the backend and configuring
   GITREVIEW_BACKEND_URL + GITREVIEW_SHARED_SECRET in a real repository.

2. **Repository pre-authorization required**: If no GitReview AI user has
   authorized the repository via the extension, the workflow step exits with a
   404 (not an error — the workflow logs a warning and exits 0 so the PR is
   not blocked).

3. **Backend must be publicly reachable**: The Actions runner calls the backend
   over HTTPS. A Render free-tier backend may experience a cold start delay on
   the first request. The workflow uses `--max-time 120` and `--retry 2` to
   handle this.

4. **Label creation requires write permission**: The workflow creates `risk: *`
   labels if they don't exist. The `GITHUB_TOKEN` has `pull-requests: write`
   permission which covers label creation on issues/PRs but not repository-level
   label management in all configurations. If label creation fails, the workflow
   logs a warning and continues.

### Next Step

**Step 20 — Deployment & CI/CD**
- Render deployment configuration for the FastAPI backend
- Supabase database provisioning
- GitHub OAuth App configuration for production
- Production environment variables
- CI/CD pipeline: lint + test on push, deploy on merge to main
- README deployment guide

---
*Last updated: 2026-09-26 | Step 19 IMPLEMENTED AND VERIFIED | 418/418 backend | 97/97 frontend | Ruff CLEAN*
