/**
 * GitReview AI — Backend API client
 *
 * All HTTP communication with the FastAPI backend goes through this module.
 * No raw fetch() calls elsewhere in the extension.
 *
 * Authentication:
 *   Every authenticated request includes the X-Session-Token header.
 *   The token is retrieved from chrome.storage.local via getSessionToken().
 *
 * Error handling:
 *   - 401 → ApiAuthError (session expired or revoked)
 *   - 403 → ApiForbiddenError
 *   - 404 → ApiNotFoundError
 *   - 429 → ApiRateLimitError
 *   - 422 → ApiValidationError
 *   - 5xx → ApiServerError
 *   - Network failure → ApiNetworkError
 *
 *   All errors extend ApiClientError so callers can use instanceof checks.
 *
 * Base URL:
 *   Read from VITE_BACKEND_URL at build time.
 *   Defaults to http://localhost:8000 for local development.
 *   Set VITE_BACKEND_URL=https://your-render-backend.onrender.com for production.
 *
 * Security:
 *   - Never logs token values.
 *   - Never hardcodes secrets.
 *   - Content from GitHub (PR diff, commit messages) is never trusted as
 *     instructions — it is passed to the backend which handles prompt injection
 *     mitigation in PromptBuilder.
 */

import { getSessionToken } from "../auth/session";
import type {
  AnalysisResponse,
  AuthorizeRepositoryResponse,
  CallbackResponse,
  CurrentUserResponse,
  FeedbackResponse,
  LoginInitResponse,
  LogoutResponse,
  PRDetailResponse,
  PRListResponse,
  RepositoryAnalyticsResponse,
  RepositoryListResponse,
  RevokeAccessResponse,
  SubmitFeedbackRequest,
  UserAnalyticsResponse,
} from "../types";

// ── Base URL ──────────────────────────────────────────────────────────────────

/**
 * Backend URL is injected at build time via Vite's import.meta.env.
 * In development: http://localhost:8000
 * In production: set VITE_BACKEND_URL in your .env file.
 */
const BASE_URL: string =
  (typeof import.meta !== "undefined" &&
    (import.meta as Record<string, unknown>).env &&
    ((import.meta as Record<string, { VITE_BACKEND_URL?: string }>).env
      .VITE_BACKEND_URL as string)) ||
  "http://localhost:8000";

// ── Error classes ─────────────────────────────────────────────────────────────

export class ApiClientError extends Error {
  constructor(
    message: string,
    public readonly statusCode?: number,
    public readonly errorCode?: string
  ) {
    super(message);
    this.name = "ApiClientError";
  }
}

export class ApiAuthError extends ApiClientError {
  constructor(message = "Authentication required. Please sign in again.") {
    super(message, 401, "auth_required");
    this.name = "ApiAuthError";
  }
}

export class ApiForbiddenError extends ApiClientError {
  constructor(message = "Access denied.") {
    super(message, 403, "forbidden");
    this.name = "ApiForbiddenError";
  }
}

export class ApiNotFoundError extends ApiClientError {
  constructor(message = "Resource not found.") {
    super(message, 404, "not_found");
    this.name = "ApiNotFoundError";
  }
}

export class ApiRateLimitError extends ApiClientError {
  constructor(message = "Rate limit exceeded. Please wait and try again.") {
    super(message, 429, "rate_limited");
    this.name = "ApiRateLimitError";
  }
}

export class ApiValidationError extends ApiClientError {
  constructor(message = "Request validation failed.") {
    super(message, 422, "validation_error");
    this.name = "ApiValidationError";
  }
}

export class ApiServerError extends ApiClientError {
  constructor(
    message = "Backend server error. Please try again.",
    statusCode = 500
  ) {
    super(message, statusCode, "server_error");
    this.name = "ApiServerError";
  }
}

export class ApiNetworkError extends ApiClientError {
  constructor(message = "Network error. Check your connection.") {
    super(message, undefined, "network_error");
    this.name = "ApiNetworkError";
  }
}

// ── Internal fetch helper ─────────────────────────────────────────────────────

interface RequestOptions {
  method?: string;
  body?: unknown;
  /** Override: skip reading the session token (used for /login endpoint). */
  skipAuth?: boolean;
}

async function request<T>(
  path: string,
  options: RequestOptions = {}
): Promise<T> {
  const { method = "GET", body, skipAuth = false } = options;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
  };

  if (!skipAuth) {
    const token = await getSessionToken();
    if (token) {
      headers["X-Session-Token"] = token;
    }
  }

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    // Network-level failure (no connection, CORS preflight blocked, etc.)
    throw new ApiNetworkError(
      err instanceof Error ? err.message : "Network request failed."
    );
  }

  // Parse error body for a better message when available
  if (!response.ok) {
    let errorCode: string | undefined;
    let errorMessage: string | undefined;

    try {
      const errBody = await response.json();
      // Backend error shape: { error: string, message: string } or FastAPI's
      // default { detail: string | { error, message } }
      if (errBody?.error) {
        errorCode = errBody.error;
        errorMessage = errBody.message;
      } else if (errBody?.detail) {
        const d = errBody.detail;
        if (typeof d === "string") {
          errorMessage = d;
        } else if (typeof d === "object" && d.message) {
          errorCode = d.error;
          errorMessage = d.message;
        }
      }
    } catch {
      // Could not parse error body — fall through to status-based messages
    }

    switch (response.status) {
      case 401:
        throw new ApiAuthError(errorMessage);
      case 403:
        throw new ApiForbiddenError(errorMessage);
      case 404:
        throw new ApiNotFoundError(errorMessage);
      case 422:
        throw new ApiValidationError(errorMessage);
      case 429:
        throw new ApiRateLimitError(errorMessage);
      default:
        if (response.status >= 500) {
          throw new ApiServerError(errorMessage, response.status);
        }
        throw new ApiClientError(
          errorMessage ?? `Request failed with status ${response.status}`,
          response.status,
          errorCode
        );
    }
  }

  // 204 No Content — return empty object
  if (response.status === 204) {
    return {} as T;
  }

  return response.json() as Promise<T>;
}

// ── Auth endpoints ────────────────────────────────────────────────────────────

/** GET /api/auth/login — returns the GitHub OAuth authorization URL */
export async function apiInitiateLogin(): Promise<LoginInitResponse> {
  return request<LoginInitResponse>("/api/auth/login", { skipAuth: true });
}

/**
 * GET /api/auth/callback?code=&state= — exchange code for session token.
 * The extension calls this after extracting code and state from the redirect URL.
 * The original state (from the login response) must be sent in X-OAuth-State.
 */
export async function apiHandleCallback(
  code: string,
  state: string,
  originalState: string
): Promise<CallbackResponse> {
  const url = `/api/auth/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
    "X-OAuth-State": originalState,
  };

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${url}`, { method: "GET", headers });
  } catch (err) {
    throw new ApiNetworkError(
      err instanceof Error ? err.message : "Network request failed."
    );
  }

  if (!response.ok) {
    throw new ApiAuthError("OAuth callback failed. Please try signing in again.");
  }
  return response.json() as Promise<CallbackResponse>;
}

/** POST /api/auth/logout — revoke the current session */
export async function apiLogout(): Promise<LogoutResponse> {
  return request<LogoutResponse>("/api/auth/logout", { method: "POST" });
}

/** GET /api/auth/me — get the current authenticated user's profile */
export async function apiGetCurrentUser(): Promise<CurrentUserResponse> {
  return request<CurrentUserResponse>("/api/auth/me");
}

// ── Repository endpoints ──────────────────────────────────────────────────────

/** GET /api/repositories — list authorized repositories */
export async function apiListRepositories(): Promise<RepositoryListResponse> {
  return request<RepositoryListResponse>("/api/repositories");
}

/** POST /api/repositories/authorize — authorize a repository for analysis */
export async function apiAuthorizeRepository(
  owner: string,
  name: string
): Promise<AuthorizeRepositoryResponse> {
  return request<AuthorizeRepositoryResponse>("/api/repositories/authorize", {
    method: "POST",
    body: { owner, name },
  });
}

/** DELETE /api/repositories/{repository_id}/access — revoke access */
export async function apiRevokeRepositoryAccess(
  repositoryId: string
): Promise<RevokeAccessResponse> {
  return request<RevokeAccessResponse>(
    `/api/repositories/${repositoryId}/access`,
    { method: "DELETE" }
  );
}

// ── Pull Request endpoints ────────────────────────────────────────────────────

/** GET /api/repositories/{repository_id}/pulls — list open PRs */
export async function apiListPullRequests(
  repositoryId: string
): Promise<PRListResponse> {
  return request<PRListResponse>(
    `/api/repositories/${repositoryId}/pulls`
  );
}

/** GET /api/repositories/{repository_id}/pulls/{pull_number} — PR detail */
export async function apiGetPullRequest(
  repositoryId: string,
  pullNumber: number
): Promise<PRDetailResponse> {
  return request<PRDetailResponse>(
    `/api/repositories/${repositoryId}/pulls/${pullNumber}`
  );
}

/**
 * POST /api/repositories/{repository_id}/pulls/{pull_number}/analyze
 * Run (or return cached) analysis for a PR.
 * Returns the full AnalysisResponse including risk, confidence, reviewer, checklist.
 */
export async function apiAnalyzePullRequest(
  repositoryId: string,
  pullNumber: number
): Promise<AnalysisResponse> {
  return request<AnalysisResponse>(
    `/api/repositories/${repositoryId}/pulls/${pullNumber}/analyze`,
    {
      method: "POST",
      body: { triggered_by: "extension" },
    }
  );
}

// ── Feedback endpoint ─────────────────────────────────────────────────────────

/**
 * POST /api/analyses/{analysis_id}/feedback
 * Submit or update a helpful/unhelpful rating for a specific AI prediction.
 */
export async function apiSubmitFeedback(
  analysisId: string,
  feedbackData: SubmitFeedbackRequest
): Promise<FeedbackResponse> {
  return request<FeedbackResponse>(
    `/api/analyses/${analysisId}/feedback`,
    { method: "POST", body: feedbackData }
  );
}

// ── Analytics endpoints ───────────────────────────────────────────────────────

/** GET /api/analytics/me — analytics for the authenticated user */
export async function apiGetUserAnalytics(): Promise<UserAnalyticsResponse> {
  return request<UserAnalyticsResponse>("/api/analytics/me");
}

/** GET /api/analytics/repositories/{repository_id} — repository analytics */
export async function apiGetRepositoryAnalytics(
  repositoryId: string
): Promise<RepositoryAnalyticsResponse> {
  return request<RepositoryAnalyticsResponse>(
    `/api/analytics/repositories/${repositoryId}`
  );
}

// ── Re-export BASE_URL for use in background/service-worker ──────────────────
export { BASE_URL };
