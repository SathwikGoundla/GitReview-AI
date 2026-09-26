/**
 * GitReview AI — Content Script (runs on github.com PR pull request pages)
 * URL pattern matched: https://github.com/{owner}/{repo}/pull/{number}
 *
 * Responsibilities (per LLD Part L):
 *   1. Extract the PR context (owner, repo, pullNumber) from the URL.
 *   2. Notify the service worker when the user is on a PR page.
 *   3. Re-run on GitHub's client-side navigation (SPA nav) — GitHub does not
 *      do full page reloads between PRs in the same repo.
 *
 * Security:
 *   - Content scripts run in an isolated world; they cannot access the
 *     page's JavaScript context.
 *   - This script does NOT hold the session token.
 *   - It does NOT make direct backend requests; all network goes through
 *     the service worker.
 *   - DOM mutation is limited to sending messages; we never modify GitHub's
 *     native DOM elements (per SRS section 10.2 Validation Rules).
 *
 * GitHub PR URL pattern:
 *   https://github.com/{owner}/{repo}/pull/{number}
 *   https://github.com/{owner}/{repo}/pull/{number}/files
 *   https://github.com/{owner}/{repo}/pull/{number}/commits
 *
 * The pull number is always the 4th URL segment after the domain.
 */

import type { ExtensionMessage, GitHubPRContext } from "../types";

/**
 * Parse the current URL and extract GitHub PR context.
 * Returns null if the URL is not a GitHub PR page.
 *
 * Examples:
 *   /SathwikGoundla/GitReview-AI/pull/42        → { owner, repo, pullNumber: 42 }
 *   /SathwikGoundla/GitReview-AI/pull/42/files  → { owner, repo, pullNumber: 42 }
 *   /SathwikGoundla/GitReview-AI                → null
 *   /SathwikGoundla/GitReview-AI/issues/1       → null
 */
export function extractPRContext(url: string): GitHubPRContext | null {
  try {
    const parsed = new URL(url);
    // Must be on github.com
    if (!parsed.hostname.endsWith("github.com")) return null;

    // pathname: /{owner}/{repo}/pull/{number}[/...]
    const segments = parsed.pathname.split("/").filter(Boolean);
    // segments[0] = owner, segments[1] = repo, segments[2] = "pull", segments[3] = number
    if (segments.length < 4) return null;
    if (segments[2] !== "pull") return null;

    const pullNumber = parseInt(segments[3], 10);
    if (isNaN(pullNumber) || pullNumber <= 0) return null;

    return {
      owner: segments[0],
      repo: segments[1],
      pullNumber,
    };
  } catch {
    // URL parsing failed
    return null;
  }
}

/** Send the PR context to the service worker */
function notifyServiceWorker(context: GitHubPRContext): void {
  const message: ExtensionMessage = {
    type: "PR_CONTEXT_RESULT",
    payload: context,
  };
  chrome.runtime.sendMessage(message).catch(() => {
    // Service worker may not be awake yet; this is not an error condition
  });
}

/** Run detection on the current URL */
function detectAndNotify(): void {
  const context = extractPRContext(window.location.href);
  if (context) {
    notifyServiceWorker(context);
  }
}

// ── Initial detection ─────────────────────────────────────────────────────────
detectAndNotify();

// ── GitHub SPA navigation detection ──────────────────────────────────────────
// GitHub is a single-page app; navigating between PRs does not fire a full
// page reload. We observe URL changes via the History API pushState events.
// Note: popstate fires for back/forward navigation.

let lastUrl = window.location.href;

// MutationObserver on <title> is the most reliable way to detect GitHub's
// client-side navigation without monkey-patching history.pushState.
const titleObserver = new MutationObserver(() => {
  const currentUrl = window.location.href;
  if (currentUrl !== lastUrl) {
    lastUrl = currentUrl;
    detectAndNotify();
  }
});

const titleEl = document.querySelector("title");
if (titleEl) {
  titleObserver.observe(titleEl, { childList: true });
}

// Also listen for popstate (browser back/forward)
window.addEventListener("popstate", () => {
  const currentUrl = window.location.href;
  if (currentUrl !== lastUrl) {
    lastUrl = currentUrl;
    detectAndNotify();
  }
});
