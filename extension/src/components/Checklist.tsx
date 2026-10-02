/**
 * GitReview AI — Checklist component
 *
 * Renders the checklist_items from the backend analysis response.
 * Per LLD Part K: items come from deterministic rules, AI judgment, or both.
 *
 * Checklist item completion (FR-6.4):
 *   The backend stores completion per-reviewer via checklist_item_completions.
 *   Completion is tracked locally and synchronized with the backend.
 *
 * Category display names map the backend's CHECK constraint enum values to
 * human-readable labels.
 */

import React, { useState, useEffect } from "react";
import type { ChecklistItemSchema } from "../types";
import { apiUpdateChecklistCompletion, ApiClientError } from "../api/client";

interface ChecklistProps {
  items: ChecklistItemSchema[];
  isFallback: boolean;
  analysisId: string;
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

export const Checklist: React.FC<ChecklistProps> = ({ items, isFallback, analysisId }) => {
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  // Initialize from props if available
  useEffect(() => {
    const initial: Record<string, boolean> = {};
    items.forEach(item => {
      // Cast to any to check for completed property if backend adds it in the future
      initial[item.category] = !!item.completed;
    });
    setChecked(initial);
  }, [items]);

  const toggleItem = async (item: ChecklistItemSchema) => {
    const isCurrentlyChecked = !!checked[item.category];
    const nextState = !isCurrentlyChecked;

    // Optimistic update
    setChecked((prev) => ({ ...prev, [item.category]: nextState }));
    setLoading((prev) => ({ ...prev, [item.category]: true }));
    setError(null);

    try {
      if (item.id) {
        await apiUpdateChecklistCompletion(analysisId, item.id, nextState);
      } else {
        console.warn("Item has no ID, cannot persist state");
      }
    } catch (err) {
      // Revert optimistic update
      setChecked((prev) => ({ ...prev, [item.category]: isCurrentlyChecked }));
      
      const msg = err instanceof ApiClientError ? err.message : "Failed to update checklist item.";
      setError(msg);
    } finally {
      setLoading((prev) => ({ ...prev, [item.category]: false }));
    }
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

      {error && (
        <div style={{
          marginBottom: "8px",
          padding: "6px",
          backgroundColor: "#fef2f2",
          border: "1px solid #fecaca",
          borderRadius: "4px",
          color: "#dc2626",
          fontSize: "11px"
        }}>
          {error}
        </div>
      )}

      {/* Items */}
      <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
        {items.map((item) => {
          const label =
            CATEGORY_LABELS[item.category] ??
            item.category.replace(/_/g, " ");
          const isChecked = !!checked[item.category];
          const isLoading = !!loading[item.category];
          const sourceLabel =
            TRIGGER_SOURCE_LABELS[item.trigger_source] ?? item.trigger_source;

          return (
            <label
              key={item.category}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: "8px",
                cursor: isLoading ? "not-allowed" : "pointer",
                padding: "6px 8px",
                borderRadius: "6px",
                backgroundColor: isChecked ? "#f0fdf4" : "#f9fafb",
                border: `1px solid ${isChecked ? "#86efac" : "#e5e7eb"}`,
                transition: "background-color 0.15s ease",
                opacity: isLoading ? 0.7 : 1,
              }}
            >
              <input
                type="checkbox"
                checked={isChecked}
                disabled={isLoading}
                onChange={() => toggleItem(item)}
                style={{ marginTop: "1px", cursor: isLoading ? "not-allowed" : "pointer", flexShrink: 0 }}
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
    </div>
  );
};
