/**
 * GitReview AI — Popup Application
 *
 * This is the main React application rendered in the extension popup.
 *
 * Views:
 *   1. Loading — checking session on mount
 *   2. Unauthenticated — sign-in prompt
 *   3. Authenticated, no PR context — user is not on a GitHub PR page
 *   4. Authenticated, PR context available — show analysis or analyze button
 *   5. Analysis result — risk, confidence, rationale, reviewer, checklist
 *
 * Auth flow:
 *   "Sign in with GitHub" → calls GET /api/auth/login → opens tab with authorize_url
 *   The service worker intercepts the callback tab and stores the session.
 *   The popup listens for AUTH_STATE_CHANGED and refreshes.
 *
 * PR context:
 *   The popup asks Chrome for the active tab URL and extracts the PR context
 *   using the same extractPRContext() function as the content script.
 *   This avoids a content-script round-trip and works even if the content
 *   script has not run yet.
 *
 * Repository resolution:
 *   To analyze a PR we need the internal repository_id (UUID).
 *   We fetch the list of authorized repositories and find the matching one
 *   by owner and name. If not found, we prompt to authorize the repository.
 */

import React, { useCallback, useEffect, useState } from "react";
import {
  apiAnalyzePullRequest,
  apiAuthorizeRepository,
  apiGetCurrentUser,
  apiInitiateLogin,
  apiListRepositories,
  apiLogout,
  ApiAuthError,
  ApiNetworkError,
} from "../api/client";
import { clearSession, getSession, saveSession } from "../auth/session";
import { extractPRContext } from "../content/github-pr";
import { RiskBadge } from "../components/RiskBadge";
import { ConfidenceBar } from "../components/ConfidenceBar";
import { RiskRationale } from "../components/RiskRationale";
import { ReviewerCard } from "../components/ReviewerCard";
import { Checklist } from "../components/Checklist";
import { FeedbackForm } from "../components/FeedbackForm";
import type {
  AnalysisResponse,
  CurrentUserResponse,
  GitHubPRContext,
  ReviewSuggestionSchema,
} from "../types";

// ── Styles ────────────────────────────────────────────────────────────────────

const BASE_STYLE: React.CSSProperties = {
  width: "360px",
  minHeight: "200px",
  maxHeight: "600px",
  overflowY: "auto",
  fontFamily:
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif",
  fontSize: "13px",
  color: "#111827",
  backgroundColor: "#ffffff",
  boxSizing: "border-box",
};

const HEADER_STYLE: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  padding: "10px 14px",
  borderBottom: "1px solid #e5e7eb",
  backgroundColor: "#f9fafb",
  position: "sticky",
  top: 0,
  zIndex: 1,
};

const SECTION_STYLE: React.CSSProperties = {
  padding: "10px 14px",
  borderBottom: "1px solid #f3f4f6",
};

const SECTION_TITLE: React.CSSProperties = {
  fontSize: "11px",
  fontWeight: 600,
  color: "#6b7280",
  textTransform: "uppercase",
  letterSpacing: "0.05em",
  marginBottom: "8px",
};

const BUTTON_PRIMARY: React.CSSProperties = {
  backgroundColor: "#2563eb",
  color: "#ffffff",
  border: "none",
  borderRadius: "6px",
  padding: "8px 16px",
  fontSize: "13px",
  fontWeight: 600,
  cursor: "pointer",
  width: "100%",
  fontFamily: "inherit",
};

const BUTTON_SECONDARY: React.CSSProperties = {
  backgroundColor: "#f3f4f6",
  color: "#374151",
  border: "1px solid #d1d5db",
  borderRadius: "6px",
  padding: "6px 12px",
  fontSize: "12px",
  cursor: "pointer",
  fontFamily: "inherit",
};

// ── App component ──────────────────────────────────────────────────────────────

type AppView =
  | "loading"
  | "unauthenticated"
  | "no_pr"
  | "pr_detected"
  | "analyzing"
  | "result"
  | "error";

export const App: React.FC = () => {
  const [view, setView] = useState<AppView>("loading");
  const [user, setUser] = useState<CurrentUserResponse | null>(null);
  const [prContext, setPrContext] = useState<GitHubPRContext | null>(null);
  const [repositoryId, setRepositoryId] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isAuthorizing, setIsAuthorizing] = useState(false);
  const [activeSection, setActiveSection] = useState<
    "risk" | "reviewer" | "checklist"
  >("risk");

  // ── Bootstrap: check session and active tab ────────────────────────────────

  const bootstrap = useCallback(async () => {
    // 1. Check stored session
    const session = await getSession();
    if (!session) {
      setView("unauthenticated");
      return;
    }

    // 2. Validate session against backend
    try {
      const me = await apiGetCurrentUser();
      setUser(me);
    } catch (err) {
      if (err instanceof ApiAuthError) {
        // Session expired or revoked
        await clearSession();
        setView("unauthenticated");
        return;
      }
      if (err instanceof ApiNetworkError) {
        setErrorMessage(
          "Cannot reach the GitReview AI backend. Is it running?"
        );
        setView("error");
        return;
      }
      // Other error — treat as not-authenticated for safety
      await clearSession();
      setView("unauthenticated");
      return;
    }

    // 3. Check active tab for PR context
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    const activeTab = tabs[0];
    const ctx = activeTab?.url ? extractPRContext(activeTab.url) : null;

    if (!ctx) {
      setView("no_pr");
      return;
    }

    setPrContext(ctx);

    // 4. Try to find the repository in the user's authorized list
    try {
      const repoList = await apiListRepositories();
      const match = repoList.repositories.find(
        (item) =>
          item.repository.owner.toLowerCase() === ctx.owner.toLowerCase() &&
          item.repository.name.toLowerCase() === ctx.repo.toLowerCase()
      );
      if (match && match.access.is_active) {
        setRepositoryId(match.repository.id);
      }
    } catch {
      // Ignore — will show the authorize button
    }

    setView("pr_detected");
  }, []);

  useEffect(() => {
    bootstrap();
  }, [bootstrap]);

  // Listen for auth state changes from the service worker (post-OAuth)
  useEffect(() => {
    const handler = (msg: { type?: string }) => {
      if (msg?.type === "AUTH_STATE_CHANGED") {
        bootstrap();
      }
    };
    chrome.runtime.onMessage.addListener(handler);
    return () => chrome.runtime.onMessage.removeListener(handler);
  }, [bootstrap]);

  // ── Auth handlers ──────────────────────────────────────────────────────────

  async function handleSignIn() {
    try {
      const { authorize_url, state } = await apiInitiateLogin();
      // Store the signed state so the service worker can verify it on callback
      await chrome.storage.local.set({ gitreview_oauth_state: state });
      // Open the authorization URL in a new tab
      await chrome.tabs.create({ url: authorize_url, active: true });
    } catch (err) {
      setErrorMessage(
        err instanceof Error ? err.message : "Failed to start sign-in."
      );
      setView("error");
    }
  }

  async function handleSignOut() {
    try {
      await apiLogout();
    } catch {
      // Best-effort
    }
    await clearSession();
    setUser(null);
    setAnalysis(null);
    setView("unauthenticated");
  }

  // ── Repository authorization ───────────────────────────────────────────────

  async function handleAuthorizeRepository() {
    if (!prContext) return;
    setIsAuthorizing(true);
    try {
      const result = await apiAuthorizeRepository(prContext.owner, prContext.repo);
      setRepositoryId(result.repository.id);
    } catch (err) {
      setErrorMessage(
        err instanceof Error
          ? err.message
          : "Failed to authorize repository."
      );
    } finally {
      setIsAuthorizing(false);
    }
  }

  // ── Analysis ───────────────────────────────────────────────────────────────

  async function handleAnalyze() {
    if (!repositoryId || !prContext) return;
    setView("analyzing");
    setErrorMessage(null);
    try {
      const result = await apiAnalyzePullRequest(
        repositoryId,
        prContext.pullNumber
      );
      setAnalysis(result);
      setView("result");
    } catch (err) {
      if (err instanceof ApiAuthError) {
        await clearSession();
        setView("unauthenticated");
        return;
      }
      setErrorMessage(
        err instanceof Error ? err.message : "Analysis failed."
      );
      setView("pr_detected"); // Stay on PR view, show error inline
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div style={BASE_STYLE}>
      {/* Header */}
      <div style={HEADER_STYLE}>
        <div
          style={{ display: "flex", alignItems: "center", gap: "6px" }}
        >
          <span style={{ fontSize: "16px" }}>🔍</span>
          <span style={{ fontWeight: 700, fontSize: "14px", color: "#111827" }}>
            GitReview AI
          </span>
        </div>
        {user && (
          <div
            style={{ display: "flex", alignItems: "center", gap: "8px" }}
          >
            {user.avatar_url && (
              <img
                src={user.avatar_url}
                alt={user.github_username}
                width={20}
                height={20}
                style={{ borderRadius: "50%" }}
              />
            )}
            <span style={{ fontSize: "12px", color: "#6b7280" }}>
              {user.github_username}
            </span>
            <button
              onClick={handleSignOut}
              style={{ ...BUTTON_SECONDARY, padding: "2px 8px", fontSize: "11px" }}
            >
              Sign out
            </button>
          </div>
        )}
      </div>

      {/* Views */}

      {view === "loading" && (
        <div
          style={{
            padding: "40px",
            textAlign: "center",
            color: "#6b7280",
          }}
        >
          <div style={{ fontSize: "20px", marginBottom: "8px" }}>⏳</div>
          Loading…
        </div>
      )}

      {view === "unauthenticated" && (
        <div style={{ padding: "24px 16px", textAlign: "center" }}>
          <div style={{ fontSize: "32px", marginBottom: "12px" }}>🔐</div>
          <p
            style={{
              color: "#374151",
              marginBottom: "16px",
              lineHeight: 1.5,
            }}
          >
            Sign in with GitHub to get AI-powered Pull Request risk assessment,
            reviewer recommendations, and review checklists.
          </p>
          <button style={BUTTON_PRIMARY} onClick={handleSignIn}>
            Sign in with GitHub
          </button>
          {errorMessage && (
            <div
              style={{
                marginTop: "12px",
                fontSize: "12px",
                color: "#ef4444",
              }}
            >
              {errorMessage}
            </div>
          )}
        </div>
      )}

      {view === "no_pr" && (
        <div style={{ padding: "24px 16px", textAlign: "center" }}>
          <div style={{ fontSize: "32px", marginBottom: "12px" }}>📋</div>
          <p style={{ color: "#6b7280", lineHeight: 1.5 }}>
            Open a GitHub Pull Request to see the AI review analysis.
          </p>
          <div
            style={{
              marginTop: "12px",
              fontSize: "11px",
              color: "#9ca3af",
              fontFamily: "monospace",
            }}
          >
            github.com/{"{owner}/{repo}"}/pull/{"{number}"}
          </div>
        </div>
      )}

      {view === "pr_detected" && prContext && (
        <div>
          {/* PR info */}
          <div style={SECTION_STYLE}>
            <div style={{ marginBottom: "4px" }}>
              <span style={{ fontSize: "11px", color: "#6b7280" }}>
                Pull Request
              </span>
            </div>
            <div style={{ fontWeight: 600, fontSize: "14px" }}>
              {prContext.owner}/{prContext.repo} #{prContext.pullNumber}
            </div>
          </div>

          {/* Authorize or analyze */}
          <div style={{ padding: "14px 14px" }}>
            {!repositoryId ? (
              <div>
                <p
                  style={{
                    fontSize: "12px",
                    color: "#374151",
                    marginBottom: "12px",
                  }}
                >
                  This repository is not yet authorized for analysis.
                </p>
                <button
                  style={BUTTON_PRIMARY}
                  onClick={handleAuthorizeRepository}
                  disabled={isAuthorizing}
                >
                  {isAuthorizing
                    ? "Authorizing…"
                    : `Authorize ${prContext.owner}/${prContext.repo}`}
                </button>
              </div>
            ) : (
              <button
                style={BUTTON_PRIMARY}
                onClick={handleAnalyze}
              >
                Analyze Pull Request #{prContext.pullNumber}
              </button>
            )}
            {errorMessage && (
              <div
                style={{
                  marginTop: "10px",
                  fontSize: "12px",
                  color: "#ef4444",
                  backgroundColor: "#fef2f2",
                  padding: "8px",
                  borderRadius: "6px",
                  border: "1px solid #fecaca",
                }}
              >
                {errorMessage}
              </div>
            )}
          </div>
        </div>
      )}

      {view === "analyzing" && (
        <div style={{ padding: "40px 16px", textAlign: "center" }}>
          <div style={{ fontSize: "24px", marginBottom: "12px" }}>🤖</div>
          <div style={{ color: "#374151", fontWeight: 500 }}>
            Analyzing PR…
          </div>
          <div
            style={{
              marginTop: "8px",
              fontSize: "12px",
              color: "#9ca3af",
            }}
          >
            This may take up to 8 seconds.
          </div>
        </div>
      )}

      {view === "error" && (
        <div style={{ padding: "24px 16px" }}>
          <div
            style={{
              padding: "12px",
              backgroundColor: "#fef2f2",
              borderRadius: "8px",
              border: "1px solid #fecaca",
            }}
          >
            <div
              style={{
                fontWeight: 600,
                color: "#991b1b",
                marginBottom: "4px",
              }}
            >
              Error
            </div>
            <div style={{ fontSize: "12px", color: "#374151" }}>
              {errorMessage ?? "An unexpected error occurred."}
            </div>
          </div>
          <button
            style={{ ...BUTTON_SECONDARY, marginTop: "12px", width: "100%" }}
            onClick={bootstrap}
          >
            Retry
          </button>
        </div>
      )}

      {view === "result" && analysis && (
        <AnalysisView
          analysis={analysis}
          prContext={prContext}
          activeSection={activeSection}
          onSectionChange={setActiveSection}
          onReAnalyze={handleAnalyze}
        />
      )}
    </div>
  );
};

// ── AnalysisView sub-component ────────────────────────────────────────────────

interface AnalysisViewProps {
  analysis: AnalysisResponse;
  prContext: GitHubPRContext | null;
  activeSection: "risk" | "reviewer" | "checklist";
  onSectionChange: (s: "risk" | "reviewer" | "checklist") => void;
  onReAnalyze: () => void;
}

const AnalysisView: React.FC<AnalysisViewProps> = ({
  analysis,
  prContext,
  activeSection,
  onSectionChange,
  onReAnalyze,
}) => {
  const tabStyle = (active: boolean): React.CSSProperties => ({
    flex: 1,
    padding: "6px 4px",
    fontSize: "11px",
    fontWeight: active ? 600 : 400,
    color: active ? "#1d4ed8" : "#6b7280",
    backgroundColor: active ? "#eff6ff" : "transparent",
    border: "none",
    borderBottom: active ? "2px solid #2563eb" : "2px solid transparent",
    cursor: "pointer",
    fontFamily: "inherit",
  });

  return (
    <div>
      {/* PR identifier */}
      <div style={{ ...SECTION_STYLE, paddingBottom: "6px" }}>
        <div
          style={{
            fontSize: "11px",
            color: "#6b7280",
            marginBottom: "4px",
          }}
        >
          {prContext
            ? `${prContext.owner}/${prContext.repo} #${prContext.pullNumber}`
            : "Pull Request"}
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <RiskBadge tier={analysis.risk_tier} size="lg" />
            {analysis.status === "degraded" && (
              <span
                style={{
                  fontSize: "10px",
                  color: "#d97706",
                  backgroundColor: "#fffbeb",
                  padding: "1px 5px",
                  borderRadius: "9999px",
                  border: "1px solid #fde68a",
                }}
              >
                degraded (deterministic only)
              </span>
            )}
          </div>
          <button
            onClick={onReAnalyze}
            style={{ ...BUTTON_SECONDARY, fontSize: "11px", padding: "3px 8px" }}
            title="Re-run analysis"
          >
            ↻ Re-analyze
          </button>
        </div>
      </div>

      {/* Summary */}
      {analysis.summary && (
        <div style={{ ...SECTION_STYLE, paddingTop: "8px", paddingBottom: "8px" }}>
          <div style={SECTION_TITLE}>Summary</div>
          <div
            style={{
              fontSize: "12px",
              color: "#374151",
              lineHeight: 1.5,
            }}
          >
            {analysis.summary}
          </div>
        </div>
      )}

      {/* Tab navigation */}
      <div
        style={{
          display: "flex",
          borderBottom: "1px solid #e5e7eb",
          backgroundColor: "#f9fafb",
        }}
      >
        <button style={tabStyle(activeSection === "risk")} onClick={() => onSectionChange("risk")}>
          Risk
        </button>
        <button
          style={tabStyle(activeSection === "reviewer")}
          onClick={() => onSectionChange("reviewer")}
        >
          Reviewer
        </button>
        <button
          style={tabStyle(activeSection === "checklist")}
          onClick={() => onSectionChange("checklist")}
        >
          Checklist ({analysis.checklist_items.length})
        </button>
      </div>

      {/* Risk tab */}
      {activeSection === "risk" && (
        <div style={{ padding: "10px 14px", display: "flex", flexDirection: "column", gap: "10px" }}>
          {/* Confidence */}
          <ConfidenceBar score={analysis.risk_confidence} label="Risk confidence" />

          {/* Rationale */}
          <RiskRationale
            rationale={analysis.risk_rationale}
            riskSource={analysis.risk_source}
          />

          {/* Review suggestions */}
          {analysis.review_suggestions.length > 0 && (
            <div>
              <div style={SECTION_TITLE}>Focus areas</div>
              <ul
                style={{
                  margin: 0,
                  paddingLeft: "16px",
                  display: "flex",
                  flexDirection: "column",
                  gap: "3px",
                }}
              >
                {analysis.review_suggestions.map(
                  (s: ReviewSuggestionSchema, i: number) => (
                    <li
                      key={i}
                      style={{ fontSize: "12px", color: "#374151" }}
                    >
                      {s.focus_area}
                      {s.category && (
                        <span
                          style={{ fontSize: "10px", color: "#9ca3af", marginLeft: "4px" }}
                        >
                          [{s.category}]
                        </span>
                      )}
                    </li>
                  )
                )}
              </ul>
            </div>
          )}

          {/* Feedback for risk tier — uses risk_assessment_id added in Step 18.1 */}
          <div style={{ borderTop: "1px solid #f3f4f6", paddingTop: "8px" }}>
            <FeedbackForm
              analysisId={analysis.analysis_id}
              predictionType="risk_tier"
              predictionReferenceId={analysis.risk_assessment_id}
            />
          </div>
        </div>
      )}

      {/* Reviewer tab */}
      {activeSection === "reviewer" && (
        <div style={{ padding: "10px 14px" }}>
          <ReviewerCard recommendation={analysis.reviewer_recommendation} />
        </div>
      )}

      {/* Checklist tab */}
      {activeSection === "checklist" && (
        <div style={{ padding: "10px 14px" }}>
          <Checklist
            items={analysis.checklist_items}
            isFallback={analysis.checklist_is_fallback}
          />
        </div>
      )}

      {/* Footer meta */}
      <div
        style={{
          padding: "6px 14px",
          borderTop: "1px solid #f3f4f6",
          fontSize: "10px",
          color: "#9ca3af",
          display: "flex",
          justifyContent: "space-between",
        }}
      >
        <span>{analysis.model_name}</span>
        <span>{new Date(analysis.created_at).toLocaleTimeString()}</span>
      </div>
    </div>
  );
};
