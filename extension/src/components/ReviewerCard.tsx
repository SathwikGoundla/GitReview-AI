/**
 * GitReview AI — ReviewerCard component
 *
 * Displays the reviewer_recommendation from the backend.
 * Per SRS FR-5.4: if the backend abstained (reviewer_recommendation is null),
 * we display "Insufficient repository history" — not a guess.
 *
 * The confidence_score shown here comes from reviewer_recommendations.confidence_score
 * (computed by ConfidenceCalculator, NOT the AI's raw self-report).
 */

import React from "react";
import { ConfidenceBar } from "./ConfidenceBar";
import type { ReviewerRecommendationSchema } from "../types";

interface ReviewerCardProps {
  recommendation: ReviewerRecommendationSchema | null;
}

export const ReviewerCard: React.FC<ReviewerCardProps> = ({
  recommendation,
}) => {
  if (!recommendation) {
    return (
      <div
        style={{
          padding: "8px 10px",
          borderRadius: "6px",
          border: "1px solid #e5e7eb",
          backgroundColor: "#f9fafb",
          fontSize: "12px",
          color: "#6b7280",
          fontStyle: "italic",
          fontFamily:
            "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif",
        }}
      >
        No reviewer suggestion — insufficient repository history for this
        file set.
      </div>
    );
  }

  return (
    <div
      style={{
        padding: "10px",
        borderRadius: "6px",
        border: "1px solid #e5e7eb",
        backgroundColor: "#f9fafb",
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif",
        display: "flex",
        flexDirection: "column",
        gap: "8px",
      }}
    >
      {/* Username + avatar */}
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <img
          src={`https://avatars.githubusercontent.com/${encodeURIComponent(recommendation.username)}?s=32`}
          alt={recommendation.username}
          width={24}
          height={24}
          style={{ borderRadius: "50%", border: "1px solid #d1d5db" }}
          onError={(e) => {
            (e.target as HTMLImageElement).style.display = "none";
          }}
        />
        <a
          href={`https://github.com/${encodeURIComponent(recommendation.username)}`}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            color: "#1d4ed8",
            fontWeight: 600,
            fontSize: "13px",
            textDecoration: "none",
          }}
        >
          @{recommendation.username}
        </a>
      </div>

      {/* Reason */}
      <div style={{ fontSize: "12px", color: "#374151" }}>
        {recommendation.reason}
      </div>

      {/* Confidence */}
      <ConfidenceBar
        score={recommendation.confidence_score}
        label="Reviewer confidence"
      />
    </div>
  );
};
