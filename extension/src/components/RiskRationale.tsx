/**
 * GitReview AI — RiskRationale component
 *
 * Renders the structured risk_rationale object returned by the backend.
 * The rationale is a JSONB field (risk_assessments.rationale) with shape:
 *   { factors: Array<{ factor: string, source: string, detail?: string }> }
 *
 * We render whatever the backend provides without modification.
 * If the shape does not match expectations, we fall back to a safe display.
 */

import React, { useState } from "react";

interface RationaleFactorShape {
  factor?: string;
  source?: string;
  detail?: string;
  [key: string]: unknown;
}

interface RiskRationaleProps {
  rationale: Record<string, unknown>;
  riskSource: string; // "deterministic_only" | "hybrid"
}

export const RiskRationale: React.FC<RiskRationaleProps> = ({
  rationale,
  riskSource,
}) => {
  const [expanded, setExpanded] = useState(false);

  const factors = Array.isArray(rationale?.factors)
    ? (rationale.factors as RationaleFactorShape[])
    : [];

  const sourceLabel =
    riskSource === "hybrid"
      ? "AI + Deterministic"
      : "Deterministic rules only";

  return (
    <div style={{ fontSize: "12px", color: "#374151" }}>
      <button
        onClick={() => setExpanded((v) => !v)}
        style={{
          background: "none",
          border: "none",
          cursor: "pointer",
          color: "#3b82f6",
          fontSize: "12px",
          padding: 0,
          fontFamily: "inherit",
          display: "flex",
          alignItems: "center",
          gap: "4px",
        }}
        aria-expanded={expanded}
      >
        <span>{expanded ? "▾" : "▸"}</span>
        <span>Why this rating? ({sourceLabel})</span>
      </button>

      {expanded && (
        <div
          style={{
            marginTop: "8px",
            padding: "8px",
            backgroundColor: "#f9fafb",
            borderRadius: "6px",
            border: "1px solid #e5e7eb",
          }}
        >
          {factors.length === 0 ? (
            <div style={{ color: "#6b7280", fontStyle: "italic" }}>
              No detailed factors available.
            </div>
          ) : (
            <ul
              style={{
                margin: 0,
                paddingLeft: "16px",
                display: "flex",
                flexDirection: "column",
                gap: "4px",
              }}
            >
              {factors.map((f, i) => (
                <li key={i} style={{ color: "#374151" }}>
                  <span style={{ fontWeight: 500 }}>
                    {f.factor ?? "Factor"}
                  </span>
                  {f.source && (
                    <span
                      style={{
                        color: "#6b7280",
                        fontSize: "11px",
                        marginLeft: "4px",
                      }}
                    >
                      [{f.source}]
                    </span>
                  )}
                  {f.detail && (
                    <span style={{ color: "#6b7280" }}>: {f.detail}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
};
