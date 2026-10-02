/**
 * GitReview AI — FeedbackForm component
 *
 * Submits helpful/unhelpful feedback for a specific AI prediction.
 *
 * Backend contract:
 *   POST /api/analyses/{analysis_id}/feedback
 *   Headers: X-Session-Token
 *   Body: {
 *     prediction_type:        "risk_tier" | "reviewer_recommendation" | "checklist_item"
 *     prediction_reference_id: UUID of the specific prediction row
 *     rating:                 "helpful" | "unhelpful"
 *     comment?:               optional string
 *   }
 *
 * prediction_reference_id for risk_tier:
 *   AnalysisResponse.risk_assessment_id (added in Step 18.1)
 *   This is the UUID of the persisted risk_assessments row that the backend
 *   validates before persisting the feedback record.
 *
 * Upsert semantics (backend):
 *   Submitting feedback twice for the same prediction updates the existing
 *   record rather than creating a duplicate. The UI reflects this with a
 *   toggle: clicking the already-selected rating re-submits (idempotent).
 *
 * Error handling:
 *   401 → session expired message
 *   400 / 422 → validation error message (e.g. wrong prediction_reference_id)
 *   network → network error message
 *   All errors are shown inline; a "Retry" option re-enables the form.
 *
 * When predictionReferenceId is null (e.g. degraded analysis with no
 * risk_assessments row), the form renders as unavailable rather than
 * submitting a blank reference.
 */

import React, { useState } from "react";
import { apiSubmitFeedback, ApiAuthError, ApiValidationError } from "../api/client";
import type { FeedbackRating, PredictionType } from "../types";

interface FeedbackFormProps {
  analysisId: string;
  predictionType: PredictionType;
  /**
   * UUID of the specific prediction row being rated.
   * For risk_tier: AnalysisResponse.risk_assessment_id
   * Null for degraded/failed analyses where no prediction row was persisted.
   */
  predictionReferenceId: string | null;
  onFeedbackSubmitted?: (rating: FeedbackRating) => void;
}

type SubmitState = "idle" | "submitting" | "done" | "error";

export const FeedbackForm: React.FC<FeedbackFormProps> = ({
  analysisId,
  predictionType,
  predictionReferenceId,
  onFeedbackSubmitted,
}) => {
  const [submitState, setSubmitState] = useState<SubmitState>("idle");
  const [submittedRating, setSubmittedRating] = useState<FeedbackRating | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // When no prediction reference exists (degraded/failed analysis), show
  // an unavailable state instead of submitting a blank reference.
  if (!predictionReferenceId) {
    return (
      <div
        style={{
          fontSize: "11px",
          color: "#9ca3af",
          fontFamily:
            "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif",
          fontStyle: "italic",
        }}
      >
        Feedback unavailable for this analysis.
      </div>
    );
  }

  async function handleRating(rating: FeedbackRating) {
    if (submitState === "submitting") return;
    // Allow re-submission if in error state (retry) or idle
    if (submitState === "done" && submittedRating === rating) return; // already rated this

    setSubmitState("submitting");
    setErrorMessage(null);

    try {
      await apiSubmitFeedback(analysisId, {
        prediction_type: predictionType,
        prediction_reference_id: predictionReferenceId!,
        rating,
      });
      setSubmittedRating(rating);
      setSubmitState("done");
      onFeedbackSubmitted?.(rating);
    } catch (err) {
      if (err instanceof ApiAuthError) {
        setErrorMessage("Session expired. Please sign in again.");
      } else if (err instanceof ApiValidationError) {
        setErrorMessage("Feedback validation failed. The prediction reference may be invalid.");
      } else if (err instanceof Error) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage("Failed to submit feedback. Please try again.");
      }
      setSubmitState("error");
    }
  }

  function handleRetry() {
    setSubmitState("idle");
    setErrorMessage(null);
  }

  if (submitState === "done") {
    return (
      <div
        style={{
          fontSize: "11px",
          color: "#059669",
          fontFamily:
            "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif",
          display: "flex",
          alignItems: "center",
          gap: "6px",
        }}
      >
        <span>✓ Feedback recorded ({submittedRating})</span>
        <button
          onClick={() => setSubmitState("idle")}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            color: "#6b7280",
            fontSize: "10px",
            padding: 0,
            fontFamily: "inherit",
            textDecoration: "underline",
          }}
          aria-label="Change feedback"
        >
          Change
        </button>
      </div>
    );
  }

  const isSubmitting = submitState === "submitting";

  return (
    <div
      style={{
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
          fontSize: "11px",
          color: "#6b7280",
        }}
      >
        <span>Was this helpful?</span>
        <button
          onClick={() => handleRating("helpful")}
          disabled={isSubmitting}
          title="Mark as helpful"
          style={{
            background: "none",
            border: "1px solid #d1d5db",
            borderRadius: "4px",
            cursor: isSubmitting ? "not-allowed" : "pointer",
            padding: "2px 6px",
            fontSize: "13px",
            opacity: isSubmitting ? 0.5 : 1,
          }}
          aria-label="Mark as helpful"
        >
          👍
        </button>
        <button
          onClick={() => handleRating("unhelpful")}
          disabled={isSubmitting}
          title="Mark as unhelpful"
          style={{
            background: "none",
            border: "1px solid #d1d5db",
            borderRadius: "4px",
            cursor: isSubmitting ? "not-allowed" : "pointer",
            padding: "2px 6px",
            fontSize: "13px",
            opacity: isSubmitting ? 0.5 : 1,
          }}
          aria-label="Mark as unhelpful"
        >
          👎
        </button>
        {isSubmitting && (
          <span style={{ color: "#9ca3af", fontSize: "10px" }}>Saving…</span>
        )}
      </div>

      {submitState === "error" && errorMessage && (
        <div
          style={{
            marginTop: "4px",
            fontSize: "10px",
            color: "#ef4444",
            display: "flex",
            alignItems: "center",
            gap: "6px",
          }}
        >
          <span>{errorMessage}</span>
          <button
            onClick={handleRetry}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: "#3b82f6",
              fontSize: "10px",
              padding: 0,
              fontFamily: "inherit",
              textDecoration: "underline",
            }}
          >
            Retry
          </button>
        </div>
      )}
    </div>
  );
};
