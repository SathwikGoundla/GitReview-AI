/**
 * GitReview AI — ConfidenceBar component
 *
 * Displays the backend's confidence score (0–100) as a percentage bar.
 * Bands per LLD Part I:
 *   >= 80  → high confidence (green)
 *   50–79  → moderate confidence (yellow)
 *   < 50   → low confidence (red)
 *
 * The score is computed by ConfidenceCalculator on the backend.
 * The frontend NEVER recalculates or adjusts this value.
 */

import React from "react";

interface ConfidenceBarProps {
  score: number; // 0–100 from backend risk_confidence field
  label?: string;
}

function getBandColor(score: number): string {
  if (score >= 80) return "#10b981"; // green — high
  if (score >= 50) return "#f59e0b"; // amber — moderate
  return "#ef4444"; // red — low
}

function getBandLabel(score: number): string {
  if (score >= 80) return "High";
  if (score >= 50) return "Moderate";
  return "Low";
}

export const ConfidenceBar: React.FC<ConfidenceBarProps> = ({
  score,
  label = "Confidence",
}) => {
  const clamped = Math.max(0, Math.min(100, score));
  const color = getBandColor(clamped);
  const bandLabel = getBandLabel(clamped);

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
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "4px",
        }}
      >
        <span style={{ fontSize: "12px", color: "#6b7280", fontWeight: 500 }}>
          {label}
        </span>
        <span
          style={{
            fontSize: "12px",
            fontWeight: 600,
            color: color,
          }}
        >
          {clamped.toFixed(0)}% — {bandLabel}
        </span>
      </div>
      <div
        style={{
          height: "6px",
          backgroundColor: "#e5e7eb",
          borderRadius: "3px",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${clamped}%`,
            backgroundColor: color,
            borderRadius: "3px",
            transition: "width 0.3s ease",
          }}
        />
      </div>
    </div>
  );
};
