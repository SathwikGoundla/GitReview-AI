/**
 * GitReview AI — Session management
 *
 * Handles storing, retrieving, and clearing the session token and user profile
 * in chrome.storage.local.
 *
 * Security rules (per LLD Part L and SRS Section 18):
 *   - Only the opaque session token is stored, never the GitHub OAuth access
 *     token or the Gemini API key.
 *   - The session token is an opaque string; the raw value is never logged.
 *   - chrome.storage.local is used (not sessionStorage/localStorage): it
 *     persists across MV3 service-worker restarts, which is required because
 *     MV3 service workers are terminated and restarted at any time.
 *
 * Storage key: "gitreview_session"
 * Shape: StoredSession | null
 */

import type { StoredSession, UserProfile } from "../types";

const STORAGE_KEY = "gitreview_session";

/**
 * Persist the session token and user profile.
 * Called once after a successful OAuth callback.
 */
export async function saveSession(
  token: string,
  user: UserProfile
): Promise<void> {
  const session: StoredSession = { token, user };
  await chrome.storage.local.set({ [STORAGE_KEY]: session });
}

/**
 * Retrieve the stored session, or null if the user is not authenticated.
 * Called on every service-worker wake and popup load.
 */
export async function getSession(): Promise<StoredSession | null> {
  const result = await chrome.storage.local.get(STORAGE_KEY);
  const session = result[STORAGE_KEY] as StoredSession | undefined;
  return session ?? null;
}

/**
 * Clear the stored session.
 * Called on logout or when the backend returns 401 (session expired/revoked).
 */
export async function clearSession(): Promise<void> {
  await chrome.storage.local.remove(STORAGE_KEY);
}

/**
 * Return the raw session token string, or null.
 * Convenience wrapper used by the API client.
 */
export async function getSessionToken(): Promise<string | null> {
  const session = await getSession();
  return session?.token ?? null;
}

/**
 * Return true if a session token is currently stored.
 * Does NOT validate the token against the backend.
 */
export async function isAuthenticated(): Promise<boolean> {
  const token = await getSessionToken();
  return token !== null;
}
