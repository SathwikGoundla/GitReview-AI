/**
 * GitReview AI — Checklist component
 *
 * Renders the checklist_items from the backend analysis response.
 * Per LLD Part K: items come from deterministic rules, AI judgment, or both.
 *
 * Checklist item completion (FR-6.4):
 *   The backend stores completion per-reviewer via checklist_item_completions.
 *   The current API does not expose a PATCH endpoint for completion state,
 *   so completion is tracked as LOCAL-ONLY UI state in this session.
 *   This is clearly labeled as a known limitation in PROJECT_STATE.md.
 *   The backend schema supports it; the API endpoint is deferred to a future step.
 *
 * Category display names map the backend's CHECK constraint enum values to
 * human-readable labels.
 */

import React, { useState } from "react";
import type { ChecklistItemSchema } from "../types";

interface ChecklistProps {
  items: ChecklistItemSchema[];
  isFallback: boolean;
}

const CATEGORY_LABELS: Record<string, string> = {
  security: "Security Validation",
  performance: "Performance",
  exception_handling: "Exception Handling",
  null_handling: "Null Handling",
  logging: "Logging",
  testing: "Test Coverage",
  documentation: "Documentation",
  dependencies: "Dependencies",
  database_changes: "Database Changes",
};

const TRIGGER_SOURCE_LABELS: Record<string, string> = {
  deterministic: "rule",
  ai: "AI",
  both: "rule+AI",
};

export const Checklist: React.FC<ChecklistProps> = ({ items, isFallback }) => {
  const [checked, setChecked] = useState<Record<string, boolean>>({});

  const toggleItem = (category: string) => {
    setChecked((prev) => ({ ...prev, [category]: !prev[category] }));
  };

  const completedCount = Object.values(checked).filter(Boolean).length;

  if (items.length === 0) {
    return (
      <div
        style={{
          fontSize: "12px",
          color: "#6b7280",
          fontStyle: "italic",
          fontFamily:
            "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif",
        }}
      >
        No checklist items for this PR.
      </div>
    );
  }

  return (
    <div
      style={{
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "8px",
        }}
      >
        <span style={{ fontSize: "12px", color: "#6b7280" }}>
          {completedCount}/{items.length} checked
        </span>
        {isFallback && (
          <span
            style={{
              fontSize: "10px",
              color: "#9ca3af",
              backgroundColor: "#f3f4f6",
              padding: "1px 6px",
              borderRadius: "9999px",
              border: "1px solid #e5e7eb",
            }}
          >
            baseline (AI unavailable)
          </span>
        )}
      </div>

      {/* Items */}
      <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
        {items.map((item) => {
          const label =
            CATEGORY_LABELS[item.category] ??
            item.category.replace(/_/g, " ");
          const isChecked = !!checked[item.category];
          const sourceLabel =
            TRIGGER_SOURCE_LABELS[item.trigger_source] ?? item.trigger_source;

          return (
            <label
              key={item.category}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: "8px",
                cursor: "pointer",
                padding: "6px 8px",
                borderRadius: "6px",
                backgroundColor: isChecked ? "#f0fdf4" : "#f9fafb",
                border: `1px solid ${isChecked ? "#86efac" : "#e5e7eb"}`,
                transition: "background-color 0.15s ease",
              }}
            >
              <input
                type="checkbox"
                checked={isChecked}
                onChange={() => toggleItem(item.category)}
                style={{ marginTop: "1px", cursor: "pointer", flexShrink: 0 }}
              />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    fontSize: "12px",
                    fontWeight: 500,
                    color: isChecked ? "#166534" : "#111827",
                    textDecoration: isChecked ? "line-through" : "none",
                    wordBreak: "break-word",
                  }}
                >
                  {label}
                </div>
                <div
                  style={{
                    fontSize: "10px",
                    color: "#9ca3af",
                    marginTop: "1px",
                    display: "flex",
                    gap: "6px",
                  }}
                >
                  <span>{sourceLabel}</span>
                  <span>·</span>
                  <span>{item.confidence_score.toFixed(0)}% confidence</span>
                </div>
              </div>
            </label>
          );
        })}
      </div>

      {/* Completion note — local state caveat */}
      <div
        style={{
          marginTop: "8px",
          fontSize: "10px",
          color: "#9ca3af",
          fontStyle: "italic",
        }}
      >
        Checkbox state is local to this session only.
      </div>
    </div>
  );
};
