/**
 * Tests for api/client.ts — API client error mapping and request construction.
 *
 * We mock globalThis.fetch to avoid real network calls.
 * Each test exercises a specific error path or success path so we can be
 * confident the client correctly maps HTTP status codes to typed errors.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  apiGetCurrentUser,
  apiAnalyzePullRequest,
  apiListRepositories,
  apiSubmitFeedback,
  ApiAuthError,
  ApiNotFoundError,
  ApiRateLimitError,
  ApiServerError,
  ApiNetworkError,
  ApiValidationError,
} from "../api/client";

// ── Fetch mock helpers ────────────────────────────────────────────────────────

function mockFetchResponse(
  status: number,
  body: unknown,
  ok = status >= 200 && status < 300
) {
  return vi.fn().mockResolvedValue({
    ok,
    status,
    json: async () => body,
  });
}

function mockFetchNetworkError(message = "Failed to fetch") {
  return vi.fn().mockRejectedValue(new TypeError(message));
}

// Store original fetch
const originalFetch = globalThis.fetch;

beforeEach(() => {
  // Ensure chrome storage mock returns no session (no X-Session-Token header)
  // Tests that need a token will set it up explicitly
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

// ── Auth error (401) ──────────────────────────────────────────────────────────

describe("API client — 401 handling", () => {
  it("throws ApiAuthError on 401", async () => {
    globalThis.fetch = mockFetchResponse(401, {
      error: "invalid_session",
      message: "Session expired.",
    });

    await expect(apiGetCurrentUser()).rejects.toThrow(ApiAuthError);
  });

  it("ApiAuthError has statusCode 401", async () => {
    globalThis.fetch = mockFetchResponse(401, {
      error: "invalid_session",
      message: "Session expired.",
    });

    try {
      await apiGetCurrentUser();
    } catch (err) {
      expect(err).toBeInstanceOf(ApiAuthError);
      expect((err as ApiAuthError).statusCode).toBe(401);
    }
  });
});

// ── Not found (404) ───────────────────────────────────────────────────────────

describe("API client — 404 handling", () => {
  it("throws ApiNotFoundError on 404", async () => {
    globalThis.fetch = mockFetchResponse(404, {
      detail: { error: "repository_not_found", message: "Not found." },
    });

    await expect(
      apiAnalyzePullRequest("some-repo-id", 42)
    ).rejects.toThrow(ApiNotFoundError);
  });

  it("ApiNotFoundError has statusCode 404", async () => {
    globalThis.fetch = mockFetchResponse(404, { error: "not_found", message: "Not found." });

    try {
      await apiListRepositories();
    } catch (err) {
      expect(err).toBeInstanceOf(ApiNotFoundError);
      expect((err as ApiNotFoundError).statusCode).toBe(404);
    }
  });
});

// ── Rate limit (429) ──────────────────────────────────────────────────────────

describe("API client — 429 handling", () => {
  it("throws ApiRateLimitError on 429", async () => {
    globalThis.fetch = mockFetchResponse(429, {
      error: "rate_limited",
      message: "Too many requests.",
    });

    await expect(apiGetCurrentUser()).rejects.toThrow(ApiRateLimitError);
  });
});

// ── Validation error (422) ───────────────────────────────────────────────────

describe("API client — 422 handling", () => {
  it("throws ApiValidationError on 422", async () => {
    globalThis.fetch = mockFetchResponse(422, {
      detail: [{ loc: ["body", "rating"], msg: "field required" }],
    });

    await expect(
      apiSubmitFeedback("analysis-id", {
        prediction_type: "risk_tier",
        prediction_reference_id: "ref-id",
        rating: "helpful",
      })
    ).rejects.toThrow(ApiValidationError);
  });
});

// ── Server error (5xx) ───────────────────────────────────────────────────────

describe("API client — 5xx handling", () => {
  it("throws ApiServerError on 500", async () => {
    globalThis.fetch = mockFetchResponse(500, {
      error: "internal_error",
      message: "Server error.",
    });

    await expect(apiGetCurrentUser()).rejects.toThrow(ApiServerError);
  });

  it("throws ApiServerError on 502", async () => {
    globalThis.fetch = mockFetchResponse(502, {
      error: "bad_gateway",
      message: "Bad gateway.",
    });

    await expect(apiGetCurrentUser()).rejects.toThrow(ApiServerError);
  });

  it("ApiServerError has the correct statusCode", async () => {
    globalThis.fetch = mockFetchResponse(503, { error: "unavailable", message: "Down." });

    try {
      await apiGetCurrentUser();
    } catch (err) {
      expect(err).toBeInstanceOf(ApiServerError);
      expect((err as ApiServerError).statusCode).toBe(503);
    }
  });
});

// ── Network error ─────────────────────────────────────────────────────────────

describe("API client — network error handling", () => {
  it("throws ApiNetworkError on fetch rejection", async () => {
    globalThis.fetch = mockFetchNetworkError("Failed to fetch");
    await expect(apiGetCurrentUser()).rejects.toThrow(ApiNetworkError);
  });

  it("ApiNetworkError has no statusCode", async () => {
    globalThis.fetch = mockFetchNetworkError();

    try {
      await apiGetCurrentUser();
    } catch (err) {
      expect(err).toBeInstanceOf(ApiNetworkError);
      expect((err as ApiNetworkError).statusCode).toBeUndefined();
    }
  });

  it("ApiNetworkError preserves the underlying error message", async () => {
    globalThis.fetch = mockFetchNetworkError("net::ERR_CONNECTION_REFUSED");

    try {
      await apiGetCurrentUser();
    } catch (err) {
      expect((err as ApiNetworkError).message).toBe(
        "net::ERR_CONNECTION_REFUSED"
      );
    }
  });
});

// ── Success paths ─────────────────────────────────────────────────────────────

describe("API client — success responses", () => {
  it("returns parsed JSON on 200", async () => {
    const mockUser = {
      id: "abc-123",
      github_username: "sathwik",
      avatar_url: null,
      session_issued_at: null,
    };
    globalThis.fetch = mockFetchResponse(200, mockUser);

    const result = await apiGetCurrentUser();
    expect(result.github_username).toBe("sathwik");
    expect(result.id).toBe("abc-123");
  });

  it("returns repository list on success", async () => {
    const mockRepos = {
      repositories: [],
      total: 0,
    };
    globalThis.fetch = mockFetchResponse(200, mockRepos);

    const result = await apiListRepositories();
    expect(result.total).toBe(0);
    expect(result.repositories).toHaveLength(0);
  });

  it("sends X-Session-Token header when session is stored", async () => {
    // Set up session in chrome storage mock
    await chrome.storage.local.set({
      gitreview_session: { token: "my-token", user: { id: "1", github_username: "u", avatar_url: null } },
    });

    let capturedHeaders: Record<string, string> = {};
    globalThis.fetch = vi.fn().mockImplementation((_url: string, init: RequestInit) => {
      capturedHeaders = Object.fromEntries(
        new Headers(init.headers as HeadersInit).entries()
      );
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({ id: "1", github_username: "u", avatar_url: null, session_issued_at: null }),
      });
    });

    await apiGetCurrentUser();
    expect(capturedHeaders["x-session-token"]).toBe("my-token");
  });

  it("does NOT send X-Session-Token when skipAuth is true (login endpoint)", async () => {
    // The login endpoint is the only one with skipAuth=true
    let capturedHeaders: Record<string, string> = {};
    globalThis.fetch = vi.fn().mockImplementation((_url: string, init: RequestInit) => {
      capturedHeaders = Object.fromEntries(
        new Headers(init.headers as HeadersInit).entries()
      );
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({ authorize_url: "https://github.com/...", state: "signed-state" }),
      });
    });

    // apiInitiateLogin uses skipAuth:true
    const { apiInitiateLogin } = await import("../api/client");
    await apiInitiateLogin();
    expect(capturedHeaders["x-session-token"]).toBeUndefined();
  });
});

// ── Error class inheritance ───────────────────────────────────────────────────

describe("Error class hierarchy", () => {
  it("ApiAuthError is an instance of ApiClientError", async () => {
    const { ApiClientError } = await import("../api/client");
    const err = new ApiAuthError();
    expect(err).toBeInstanceOf(ApiClientError);
  });

  it("ApiNotFoundError is an instance of ApiClientError", async () => {
    const { ApiClientError } = await import("../api/client");
    const err = new ApiNotFoundError();
    expect(err).toBeInstanceOf(ApiClientError);
  });

  it("ApiServerError is an instance of ApiClientError", async () => {
    const { ApiClientError } = await import("../api/client");
    const err = new ApiServerError();
    expect(err).toBeInstanceOf(ApiClientError);
  });

  it("ApiNetworkError is an instance of ApiClientError", async () => {
    const { ApiClientError } = await import("../api/client");
    const err = new ApiNetworkError();
    expect(err).toBeInstanceOf(ApiClientError);
  });
});
