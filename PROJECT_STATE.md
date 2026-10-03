# GitReview AI — Project State

> Single source of truth for current project status. `backend/PROJECT_STATE.md` is a legacy historical log and is not kept current.
> Last verified: 2026-10-03, on top of baseline commit `a43774d262a723134f8990aca0dd4be0fc4848f3`.
> The commit SHA that contains this file cannot be written into the file itself; the final SHA and the clean ZIP are reported in the verification report and `git log`.

## Project Identity
- Project: GitReview AI — AI-Powered Pull Request Review Assistance
- Architecture: modular-monolith FastAPI backend, Supabase PostgreSQL, GitHub OAuth, Google Gemini, Manifest V3 Chrome Extension (React + TypeScript + Vite), GitHub Actions composite action.
- Branch convention: `master`.

## Implementation Status
| Area | Status |
|------|--------|
| Backend API (auth, repositories, PRs, analysis, feedback, analytics, Actions endpoint) | Implemented, tested (mocked services + in-memory DB) |
| AI pipeline (Gemini adapter, prompt builder, validator, risk, confidence, reviewer, checklist) | Implemented, tested with mocks |
| Chrome Extension (popup, analysis view, feedback, checklist completion, dashboard, analytics, repository management) | Implemented, tested (Vitest, mocked fetch/chrome) |
| GitHub Actions integration (`.github/actions/gitreview-ai`) | Implemented, tested at the definition/contract level |
| Production preflight, PR size limits, extension production-build enforcement | Implemented, tested |
| Deployment | **Not done** |
| Live end-to-end validation (real GitHub, Gemini, Supabase) | **Not done** |
| GitHub Marketplace publication | Not done |

## Gemini Model
- Default and configured model: `gemini-2.5-flash` (`GEMINI_MODEL` in `backend/app/core/config.py` and `backend/.env.example`).
- The recorded analysis `model_name` (persisted and returned) now comes from `settings.gemini_model`; cached results report the model stored on that row. Previously a second hardcoded constant was used.
- An earlier note claimed a deprecation and a switch to `gemini-3.8-flash`. No source file supports that and it has been removed. Model availability against Google's current documentation has NOT been verified here; check it before deployment.

## API Inventory (verified against the live OpenAPI schema: 16 endpoints)
- `GET /health`
- Auth: `GET /api/auth/login`, `GET /api/auth/callback`, `GET /api/auth/me`, `POST /api/auth/logout`
- Repositories: `GET /api/repositories`, `POST /api/repositories/authorize`, `DELETE /api/repositories/{repository_id}/access`
- Pull requests: `GET /api/repositories/{repository_id}/pulls`, `GET /api/repositories/{repository_id}/pulls/{pull_number}`, `POST /api/repositories/{repository_id}/pulls/{pull_number}/analyze`
- Feedback / checklist: `POST /api/analyses/{analysis_id}/feedback`, `PATCH /api/analyses/{analysis_id}/checklist/{item_id}`
- Analytics: `GET /api/analytics/me`, `GET /api/analytics/repositories/{repository_id}`
- Actions: `POST /api/actions/analyze`

## Database
- PostgreSQL/Supabase, migration `0001_initial_schema`, 17 tables. No schema or migration changes in this round.

## Step 21A — Pre-Deployment Audit: Complete
- Fixed an emoji encoding regression in the Actions service, E402/F401 problems in the E2E tests, and the missing `typecheck` script in `extension/package.json`.

## Step 21B — Production Hardening: Complete (code and tests only; not deployed)
- **Preflight** (`python -m app.core.preflight`, run from `backend/`): required secrets present, no placeholders or weak values (short, repeated-character, whole-value weak words; a long value merely containing "secret" is accepted), **`ENCRYPTION_KEY` validated as a real Fernet key** (separate from generic secret validation), no wildcard or localhost CORS in production, no placeholder extension ID, valid exact `chrome-extension://<id>` accepted. Secret values are never printed.
- **PR size limits:** `MAX_PR_LINES` (default 3000, lines added + removed) and `MAX_PR_BYTES` (default 1048576, UTF-8 size of diff text). Exact boundary accepted, one over rejected, HTTP 413, error code `PR_TOO_LARGE`, raised before any AI call or persistence. The Actions step fails visibly and posts no comment.
- **List settings:** `ALLOWED_ORIGINS` and `SENSITIVE_PATH_PATTERNS` now accept a comma-separated string or a JSON array (`NoDecode` + explicit parser); invalid JSON fails validation. Previously the comma form documented in `.env.example` crashed `Settings` under pydantic-settings 2.15.0.
- **Extension production build:** requires `VITE_BACKEND_URL`; the build fails without it. The dev-only `http://localhost:8000` fallback string remains in the bundle but is unreachable in production builds.
- **Test isolation:** `backend/tests/conftest.py` forces test values for database URLs and credentials (previously `setdefault`). Verified: with a hostile `DATABASE_URL` in the shell, tests still see the forced localhost test URL. E2E tests use in-memory SQLite with `get_db` overridden.
- **Repository hygiene:** `.gitignore` repaired (it contained UTF-16 bytes); `extension/dist` untracked (generated output); scratch file `extension/test_zip.js` removed; `aiosqlite` and `sqlalchemy[asyncio]` declared in `pyproject.toml`.

## Step 21C — Dependency Correction: Complete
- **Dependency fix:** `pydantic-settings` requirement in `backend/pyproject.toml` bumped from `>=2.3.0` to `>=2.7.0` because the symbol `NoDecode` (used for `ALLOWED_ORIGINS` and `SENSITIVE_PATH_PATTERNS`) was introduced in version `2.7.0`.

## Verified Results (this round)
| Check | Command / location | Result |
|-------|--------------------|--------|
| Backend baseline (before changes) | `pytest -q` in `backend/` | 500 passed |
| Backend final | `pytest -q` in `backend/` | **519 passed**, 1 warning (pytest-asyncio config deprecation notice) |
| E2E | `pytest tests/e2e` | 21 passed |
| Preflight unit tests | `tests/unit/core/test_preflight.py` | 20 passed |
| Config list parsing tests | `tests/unit/core/test_config_lists.py` | 10 passed |
| Size-limit + model-name tests | `tests/unit/analysis/test_size_limits.py` | 5 passed |
| Actions (unit + E2E) | `tests/unit/actions_integration` + `tests/e2e/test_actions_flow_e2e.py` | 97 passed |
| Preflight CLI scenarios | real `python -m app.core.preflight`, isolated child env, fake values | 16/16 scenarios behaved as expected |
| Ruff | `ruff check .` / `ruff format --check .` in `backend/` | pass / pass (baseline HEAD had 19 `ruff check` errors; all fixed without suppressing rules) |
| Extension tests | `npm test` | 106 passed (6 files) |
| Extension typecheck | `npm run typecheck` | pass |
| Extension dev build | `vite build --mode development` | pass |
| Prod build without `VITE_BACKEND_URL` | `vite build --mode production` | fails as required |
| Prod build with fake URL | `VITE_BACKEND_URL=https://fake-backend.invalid` | pass; no real URL embedded |
| Bandit | `bandit -r app -ll` | no medium/high findings |
| Secret-pattern scan | 164 files, git-tracked + untracked-unignored | no real secrets; 6 intentional fake test fixtures excluded (see below) |

Secret-scan exclusions (fake test fixtures only): `backend/tests/e2e/test_actions_flow_e2e.py`, `backend/tests/e2e/test_full_workflow_e2e.py`, `backend/tests/unit/actions_integration/test_actions_integration.py`, `extension/src/__tests__/session.test.ts`. The scanner was not disabled. The e2e files hard-code a test-only Fernet key; never reuse it outside tests.

## Known Limitations
- Not deployed; no live validation against real GitHub, Gemini, or Supabase. All AI/GitHub behaviour is tested with mocks.
- Passing tests and preflight do not establish production readiness. No performance target (e.g. the 8-second analysis goal) has been measured.
- Extension not tested in a real Chrome browser against a deployed backend.
- Checklist-item feedback is accepted by the backend but has no UI control; the UI collects feedback for the risk tier and reviewer recommendation only.
- Confidence values are heuristic indicators, not statistically calibrated probabilities. Risk scoring has not been validated against labeled defect data.
- Gemini model availability not re-checked against current Google documentation.
- `backend/PROJECT_STATE.md` is retained as a legacy log (bannered); its contents are outdated.
- pytest-asyncio emits a configuration deprecation warning (`asyncio_default_fixture_loop_scope` unset).
- A module-level `client = TestClient(app)` remains in `test_actions_flow_e2e.py` (left in place; not part of this change).

## Decisions
- Aggregation is done in SQL at read time rather than nightly batch tables (MVP scale).
- Actions comment idempotency is handled by the workflow script updating a marker comment (`<!-- gitreview-ai-bot -->`).
- `backend/PROJECT_STATE.md` kept as a legacy log instead of deleted: nothing references it, but it holds step history. Root `PROJECT_STATE.md` is authoritative.
- Generated extension output (`extension/dist`, `extension/release`) is git-ignored and excluded from the source ZIP.

## Next Step
- Deploy the backend (Render) and Supabase with real secrets, run `python -m app.core.preflight` against the real production environment, then perform a controlled live end-to-end validation (real GitHub OAuth app, real Gemini key, a test repository) and measure latency before any production claim.
