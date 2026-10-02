/**
 * GitReview AI — TypeScript type definitions
 *
 * All types are derived from the actual FastAPI Pydantic schemas.
 * Field names and value sets must match the backend exactly.
 * Do not invent fields that do not exist in the backend response.
 *
 * Sources:
 *   backend/app/auth/schemas.py
 *   backend/app/repositories/schemas.py
 *   backend/app/pull_requests/schemas.py
 *   backend/app/feedback/schemas.py
 *   backend/app/analytics/schemas.py
 */

// ── Auth ──────────────────────────────────────────────────────────────────────

/** Response from GET /api/auth/login */
export interface LoginInitResponse {
  authorize_url: string;
  state: string;
}

/** User profile embedded in CallbackResponse and returned by /api/auth/me */
export interface UserProfile {
  id: string;
  github_username: string;
  avatar_url: string | null;
}

/** Response from GET /api/auth/callback */
export interface CallbackResponse {
  session_token: string;
  user: UserProfile;
}

/** Response from GET /api/auth/me */
export interface CurrentUserResponse {
  id: string;
  github_username: string;
  avatar_url: string | null;
  session_issued_at: string | null;
}

/** Response from POST /api/auth/logout */
export interface LogoutResponse {
  message: string;
}

// ── Repositories ──────────────────────────────────────────────────────────────

/** Single repository */
export interface RepositoryResponse {
  id: string;
  github_repo_id: number;
  owner: string;
  name: string;
  full_name: string;
  default_branch: string | null;
}

/** Access record for one user ↔ repository relationship */
export interface RepositoryAccessResponse {
  repository_id: string;
  github_permission_level: string | null;
  authorized_at: string;
  is_active: boolean;
}

/** One item in the authorized-repository list */
export interface AuthorizedRepositoryItem {
  repository: RepositoryResponse;
  access: RepositoryAccessResponse;
}

/** Response from GET /api/repositories */
export interface RepositoryListResponse {
  repositories: AuthorizedRepositoryItem[];
  total: number;
}

/** Response from POST /api/repositories/authorize */
export interface AuthorizeRepositoryResponse {
  repository: RepositoryResponse;
  access: RepositoryAccessResponse;
  message: string;
}

/** Response from DELETE /api/repositories/{repository_id}/access */
export interface RevokeAccessResponse {
  message: string;
  repository_id: string;
}

// ── Pull Requests ─────────────────────────────────────────────────────────────

/** Lightweight PR in list responses */
export interface PRSummaryResponse {
  pr_number: number;
  title: string;
  author_username: string;
  state: string; // "open" | "closed" | "merged"
  head_branch: string;
  base_branch: string;
  commit_sha: string;
  lines_added: number;
  lines_removed: number;
}

/** Response from GET /api/repositories/{id}/pulls */
export interface PRListResponse {
  repository_id: string;
  owner: string;
  name: string;
  pull_requests: PRSummaryResponse[];
  total: number;
}

/** Response from GET /api/repositories/{id}/pulls/{number} */
export interface PRDetailResponse {
  pr_number: number;
  title: string;
  author_username: string;
  state: string;
  head_branch: string;
  base_branch: string;
  commit_sha: string;
  lines_added: number;
  lines_removed: number;
  changed_files: string[];
  commit_messages: string[];
}

/** One AI-generated review-focus suggestion */
export interface ReviewSuggestionSchema {
  focus_area: string;
  category: string | null;
}

/** Reviewer recommendation — present only when the module did not abstain */
export interface ReviewerRecommendationSchema {
  id: string;
  username: string;
  reason: string;
  confidence_score: number;
}

/** One adaptive checklist item */
export interface ChecklistItemSchema {
  id: string;
  category: string;
  confidence_score: number;
  trigger_source: string; // "deterministic" | "ai" | "both"
  completed?: boolean;
}

/** Full analysis result from POST /api/repositories/{id}/pulls/{number}/analyze */
export interface AnalysisResponse {
  analysis_id: string;
  pull_request_id: string;
  commit_sha: string;
  status: string; // "completed" | "degraded" | "failed"
  summary: string | null;
  risk_tier: string; // "low" | "medium" | "high" | "critical"
  risk_source: string; // "deterministic_only" | "hybrid"
  risk_rationale: Record<string, unknown>;
  risk_confidence: number; // 0–100
  /**
   * UUID of the persisted risk_assessments row.
   * Pass this as prediction_reference_id when submitting risk_tier feedback:
   *   POST /api/analyses/{analysis_id}/feedback
   *   { prediction_type: "risk_tier", prediction_reference_id: risk_assessment_id }
   * Null only when the analysis failed before persisting a risk assessment.
   */
  risk_assessment_id: string | null;
  review_suggestions: ReviewSuggestionSchema[];
  reviewer_recommendation: ReviewerRecommendationSchema | null;
  checklist_items: ChecklistItemSchema[];
  checklist_is_fallback: boolean;
  triggered_by: string;
  model_name: string;
  prompt_template_version: string;
  created_at: string;
}

// ── Checklist Completion ──────────────────────────────────────────────────────

export interface ChecklistCompletionRequest {
  completed: boolean;
}

export interface ChecklistCompletionResponse {
  item_id: string;
  completed: boolean;
}

// ── Feedback ──────────────────────────────────────────────────────────────────

/** Allowed prediction types — matches backend PredictionType enum */
export type PredictionType =
  | "risk_tier"
  | "reviewer_recommendation"
  | "checklist_item";

/** Allowed feedback ratings — matches backend FeedbackRating enum */
export type FeedbackRating = "helpful" | "unhelpful";

/** Request body for POST /api/analyses/{analysis_id}/feedback */
export interface SubmitFeedbackRequest {
  prediction_type: PredictionType;
  prediction_reference_id: string;
  rating: FeedbackRating;
  comment?: string;
}

/** Response from POST /api/analyses/{analysis_id}/feedback */
export interface FeedbackResponse {
  feedback_id: string;
  analysis_id: string;
  prediction_type: PredictionType;
  prediction_reference_id: string;
  rating: FeedbackRating;
  created_at: string;
}

// ── Analytics ─────────────────────────────────────────────────────────────────

/** Risk distribution counts */
export interface RiskDistribution {
  low: number;
  medium: number;
  high: number;
  critical: number;
}

/** Feedback summary */
export interface FeedbackSummary {
  helpful: number;
  unhelpful: number;
  total: number;
  helpful_percentage: number | null;
}

/** Reviewer recommendation stats */
export interface ReviewerStats {
  recommendations_made: number;
  abstentions: number;
}

/** Response from GET /api/analytics/me */
export interface UserAnalyticsResponse {
  total_analyses: number;
  completed_analyses: number;
  degraded_analyses: number;
  failed_analyses: number;
  unique_prs_analyzed: number;
  risk_distribution: RiskDistribution;
  avg_confidence: number | null;
  feedback_given: FeedbackSummary;
  reviewer_stats: ReviewerStats;
  authorized_repository_count: number;
  first_analysis_at: string | null;
  latest_analysis_at: string | null;
}

/** Response from GET /api/analytics/repositories/{id} */
export interface RepositoryAnalyticsResponse {
  repository_id: string;
  full_name: string;
  github_repo_id: number;
  total_analyses: number;
  completed_analyses: number;
  degraded_analyses: number;
  failed_analyses: number;
  unique_prs_analyzed: number;
  risk_distribution: RiskDistribution;
  avg_confidence: number | null;
  feedback_received: FeedbackSummary;
  reviewer_stats: ReviewerStats;
  authorized_user_count: number;
  first_analysis_at: string | null;
  latest_analysis_at: string | null;
}

// ── Extension-internal types ──────────────────────────────────────────────────

/** GitHub PR context extracted from the page URL */
export interface GitHubPRContext {
  owner: string;
  repo: string;
  pullNumber: number;
}

/** Internal message types for chrome.runtime messaging */
export type ExtensionMessageType =
  | "GET_SESSION"
  | "SESSION_RESULT"
  | "GET_PR_CONTEXT"
  | "PR_CONTEXT_RESULT"
  | "AUTH_STATE_CHANGED"
  | "ERROR";

/** Typed message envelope */
export interface ExtensionMessage {
  type: ExtensionMessageType;
  payload?: unknown;
}

/** Session state stored in chrome.storage.local */
export interface StoredSession {
  token: string;
  user: UserProfile;
}

/** API error shape — backend returns this on 4xx/5xx */
export interface ApiError {
  error: string;
  message: string;
  detail?: string;
}
