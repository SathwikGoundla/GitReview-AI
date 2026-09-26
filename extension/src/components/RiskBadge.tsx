/**
 * GitReview AI — RiskBadge component
 *
 * Displays the risk tier from the backend as a colour-coded badge.
 * Risk tiers come from the backend's risk_assessments.risk_tier CHECK constraint:
 *   "low" | "medium" | "high" | "critical"
 * No additional tiers are invented here.
 */

import React from "react";

interface RiskBadgeProps {
  tier: string;
  size?: "sm" | "lg";
}

const TIER_CONFIG: Record<
  string,
  { label: string; bg: string; text: string; border: string }
> = {
  low: {
    label: "LOW",
    bg: "#d1fae5",
    text: "#065f46",
    border: "#6ee7b7",
  },
  medium: {
    label: "MEDIUM",
    bg: "#fef9c3",
    text: "#713f12",
    border: "#fde047",
  },
  high: {
    label: "HIGH",
    bg: "#fee2e2",
    text: "#7f1d1d",
    border: "#fca5a5",
  },
  critical: {
    label: "CRITICAL",
    bg: "#fce7f3",
    text: "#831843",
    border: "#f9a8d4",
  },
};

const DEFAULT_CONFIG = {
  label: "UNKNOWN",
  bg: "#f3f4f6",
  text: "#374151",
  border: "#d1d5db",
};

export const RiskBadge: React.FC<RiskBadgeProps> = ({
  tier,
  size = "sm",
}) => {
  const config = TIER_CONFIG[tier.toLowerCase()] ?? DEFAULT_CONFIG;
  const isLarge = size === "lg";

  return (
    <span
      style={{
        display: "inline-block",
        padding: isLarge ? "4px 12px" : "2px 8px",
        borderRadius: "9999px",
        border: `1px solid ${config.border}`,
        backgroundColor: config.bg,
        color: config.text,
        fontSize: isLarge ? "13px" : "11px",
        fontWeight: 600,
        letterSpacing: "0.05em",
        lineHeight: 1.4,
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif",
      }}
    >
      {config.label}
    </span>
  );
};
