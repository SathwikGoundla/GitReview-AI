/**
 * GitReview AI — Background Service Worker (Manifest V3)
 *
 * The service worker is the central client-side coordinator (LLD Part L).
 * It is the ONLY extension component that:
 *   - Holds the session reference
 *   - Makes backend API calls
 *   - Manages OAuth state
 *
 * MV3 constraint: service workers are non-persistent. They are terminated by
 * Chrome after a period of inactivity and restarted on demand. Therefore:
 *   - No in-memory state is relied upon between events
 *   - All persistent state (session token, OAuth state) is in chrome.storage.local
 *   - The service worker rehydrates from storage on every wake
 *
 * OAuth flow (per auth router comments):
 *   1. Popup calls GET /api/auth/login → gets { authorize_url, state }
 *   2. Service worker opens authorize_url in a new tab
 *   3. GitHub redirects to backend callback: GET /api/auth/callback?code=&state=
 *   4. The callback tab URL is intercepted via chrome.tabs.onUpdated
 *   5. Service worker extracts code and state, calls the backend callback endpoint
 *      with X-OAuth-State header (the original state from step 1)
 *   6. Backend returns { session_token, user }
 *   7. Session is stored in chrome.storage.local
 *   8. Popup is notified via AUTH_STATE_CHANGED message
 *
 * Note: The OAuth callback is handled by the backend at the configured
 * GITHUB_REDIRECT_URI. In development this is http://localhost:8000/api/auth/callback.
 * The tab will load this URL; chrome.tabs.onUpdated fires, and the service
 * worker intercepts it before the backend page renders (or immediately after).
 */

import {
  clearSession,
  getSession,
  saveSession,
} from "../auth/session";
import {
  apiHandleCallback,
  apiInitiateLogin,
  apiLogout,
  BASE_URL,
} from "../api/client";
import type { ExtensionMessage, GitHubPRContext } from "../types";

// ── OAuth state storage key ────────────────────────────────────────────────────
// The signed state from the login response must survive service-worker restarts.
const OAUTH_STATE_KEY = "gitreview_oauth_state";

// Track the OAuth tab id so we can close it after success
let oauthTabId: number | null = null;

// ── Message listener ──────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener(
  (
    message: ExtensionMessage,
    _sender,
    sendResponse: (response: unknown) => void
  ) => {
    // All async handlers must call sendResponse before returning
    handleMessage(message, sendResponse);
    // Return true to keep the message channel open for async responses
    return true;
  }
);

async function handleMessage(
  message: ExtensionMessage,
  sendResponse: (response: unknown) => void
): Promise<void> {
  try {
    switch (message.type) {
      case "GET_SESSION": {
        const session = await getSession();
        sendResponse({ type: "SESSION_RESULT", payload: session });
        break;
      }
      default:
        sendResponse({ type: "ERROR", payload: { message: "Unknown message type." } });
    }
  } catch (err) {
    sendResponse({
      type: "ERROR",
      payload: { message: err instanceof Error ? err.message : "Unknown error." },
    });
  }
}

// ── OAuth tab interception ────────────────────────────────────────────────────

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== "loading") return;
  const url = tab.url ?? "";

  // Detect when GitHub redirects back to our backend callback URL
  if (!url.startsWith(BASE_URL + "/api/auth/callback")) return;
  if (tabId !== oauthTabId) return;

  let parsedUrl: URL;
  try {
    parsedUrl = new URL(url);
  } catch {
    return;
  }

  const code = parsedUrl.searchParams.get("code");
  const returnedState = parsedUrl.searchParams.get("state");

  if (!code || !returnedState) return;

  // Retrieve the original state we stored before opening the OAuth tab
  const storedResult = await chrome.storage.local.get(OAUTH_STATE_KEY);
  const originalState = storedResult[OAUTH_STATE_KEY] as string | undefined;

  if (!originalState) {
    // State missing — cannot verify CSRF; abort
    await chrome.storage.local.remove(OAUTH_STATE_KEY);
    oauthTabId = null;
    // Close the OAuth tab
    chrome.tabs.remove(tabId).catch(() => undefined);
    broadcastAuthStateChanged(false);
    return;
  }

  try {
    const result = await apiHandleCallback(code, returnedState, originalState);
    await saveSession(result.session_token, result.user);
    broadcastAuthStateChanged(true);
  } catch {
    broadcastAuthStateChanged(false);
  } finally {
    await chrome.storage.local.remove(OAUTH_STATE_KEY);
    oauthTabId = null;
    // Close the OAuth tab after a short delay so the user sees the redirect
    setTimeout(() => {
      chrome.tabs.remove(tabId).catch(() => undefined);
    }, 500);
  }
});

// ── Exported functions for popup use via chrome.runtime.sendMessage ───────────
// The popup calls these via the service worker indirectly by sending messages,
// but for simplicity in the popup we also expose a direct-call approach via
// chrome.runtime.getBackgroundPage() — however MV3 no longer supports that.
// Instead the popup makes its own fetch() calls using the API client directly,
// using the session token it retrieves from the service worker.

// These functions are called from the popup via direct API client usage.
// The service worker only needs to handle OAuth interception and session checks.

/** Initiate the GitHub OAuth flow by opening a new tab */
export async function initiateOAuth(): Promise<void> {
  const { authorize_url, state } = await apiInitiateLogin();
  // Store the signed state in chrome.storage.local before opening the tab
  // so it survives a potential service-worker restart during the OAuth flow
  await chrome.storage.local.set({ [OAUTH_STATE_KEY]: state });

  // Open the authorization URL in a new tab
  const tab = await chrome.tabs.create({ url: authorize_url, active: true });
  oauthTabId = tab.id ?? null;
}

/** Logout: revoke session on backend, clear local storage */
export async function logoutUser(): Promise<void> {
  try {
    await apiLogout();
  } catch {
    // Backend logout is best-effort; always clear local session
  } finally {
    await clearSession();
    broadcastAuthStateChanged(false);
  }
}

/** Broadcast an auth state change to all extension views */
function broadcastAuthStateChanged(isAuthenticated: boolean): void {
  const message: ExtensionMessage = {
    type: "AUTH_STATE_CHANGED",
    payload: { isAuthenticated },
  };
  chrome.runtime.sendMessage(message).catch(() => {
    // No listeners open — normal when popup is closed
  });
}

// ── Context menu / install listener ──────────────────────────────────────────

chrome.runtime.onInstalled.addListener(() => {
  // No additional setup needed for MVP
});

// ── Export helpers used by popup ──────────────────────────────────────────────
// Popup imports these directly because MV3 allows ES module service workers.
// The popup cannot import from the service worker file directly, but it uses
// the same auth/session.ts and api/client.ts modules independently.
export { OAUTH_STATE_KEY };

// Export for GitHub PR context — the service worker stores the last known
// PR context so the popup can read it without a content script message
export async function storeCurrentPRContext(context: GitHubPRContext): Promise<void> {
  await chrome.storage.local.set({ gitreview_pr_context: context });
}

export async function getCurrentPRContext(): Promise<GitHubPRContext | null> {
  const result = await chrome.storage.local.get("gitreview_pr_context");
  return (result["gitreview_pr_context"] as GitHubPRContext) ?? null;
}
