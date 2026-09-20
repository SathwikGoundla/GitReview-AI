"""
GitReview AI — FastAPI Application Entrypoint

The backend is the SOLE holder of all secrets.
The Extension and GitHub Actions never access the DB or AI provider directly.
All access is mediated by this FastAPI service (HLD Section 12).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.auth import router as auth_router
from app.api.pull_requests import router as pull_requests_router
from app.api.repositories import router as repositories_router
from app.core.config import get_settings
from app.core.exceptions import GitReviewError
from app.core.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("GitReview AI backend starting. env=%s", settings.app_env)
    yield
    logger.info("GitReview AI backend shutting down.")


app = FastAPI(
    title="GitReview AI",
    description="AI-Powered Pull Request Review Assistance API",
    version="0.1.0",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Session-Token", "X-OAuth-State"],
)


# ── Global exception handler ───────────────────────────────────────────────────
# Converts our typed exception hierarchy into structured JSON responses
# so the client always receives { "error": "...", "message": "..." }.


@app.exception_handler(GitReviewError)
async def gitreview_error_handler(request: Request, exc: GitReviewError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "error": exc.error_code,
            "message": exc.message,
            "detail": exc.detail,
        },
    )


# ── Routers ────────────────────────────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(repositories_router)
app.include_router(pull_requests_router)


# ── Health ─────────────────────────────────────────────────────────────────────


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    """Lightweight health check endpoint."""
    return {"status": "ok", "env": settings.app_env}
