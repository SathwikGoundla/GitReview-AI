import React from "react";
import type { RiskDistribution, FeedbackSummary, ReviewerStats } from "../types";

export interface AnalyticsData {
  total_analyses: number;
  completed_analyses: number;
  degraded_analyses: number;
  failed_analyses: number;
  unique_prs_analyzed: number;
  risk_distribution: RiskDistribution;
  avg_confidence: number | null;
  feedback: FeedbackSummary;
  reviewer_stats: ReviewerStats;
  first_analysis_at: string | null;
  latest_analysis_at: string | null;
}

export const AnalyticsView: React.FC<{ data: AnalyticsData; title: string }> = ({
  data,
  title,
}) => {
  const SECTION_TITLE: React.CSSProperties = {
    fontSize: "11px",
    fontWeight: 600,
    color: "#6b7280",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    marginBottom: "8px",
  };

  const CARD_STYLE: React.CSSProperties = {
    backgroundColor: "#f9fafb",
    padding: "8px",
    borderRadius: "6px",
    border: "1px solid #e5e7eb",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    minWidth: "60px",
  };

  const CARD_VALUE: React.CSSProperties = {
    fontSize: "16px",
    fontWeight: 700,
    color: "#111827",
  };

  const CARD_LABEL: React.CSSProperties = {
    fontSize: "10px",
    color: "#6b7280",
    marginTop: "4px",
    textAlign: "center",
  };

  if (data.total_analyses === 0) {
    return (
      <div style={{ padding: "16px", textAlign: "center", color: "#6b7280" }}>
        <div style={{ fontSize: "24px", marginBottom: "8px" }}>📊</div>
        <div style={{ fontSize: "13px" }}>No analyses yet.</div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      <div>
        <div style={SECTION_TITLE}>{title}</div>
        <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
          <div style={CARD_STYLE}>
            <span style={CARD_VALUE}>{data.total_analyses}</span>
            <span style={CARD_LABEL}>Total</span>
          </div>
          <div style={CARD_STYLE}>
            <span style={CARD_VALUE}>{data.unique_prs_analyzed}</span>
            <span style={CARD_LABEL}>Unique PRs</span>
          </div>
          <div style={CARD_STYLE}>
            <span style={CARD_VALUE}>
              {data.avg_confidence ? Math.round(data.avg_confidence) + "%" : "N/A"}
            </span>
            <span style={CARD_LABEL}>Avg. Conf</span>
          </div>
          <div style={CARD_STYLE}>
            <span style={CARD_VALUE}>
              {data.feedback.helpful_percentage !== null
                ? Math.round(data.feedback.helpful_percentage * 100) + "%"
                : "N/A"}
            </span>
            <span style={CARD_LABEL}>Helpful</span>
          </div>
        </div>
      </div>

      <div>
        <div style={SECTION_TITLE}>Risk Distribution</div>
        <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
          <div style={{ ...CARD_STYLE, borderColor: "#d1d5db" }}>
            <span style={CARD_VALUE}>{data.risk_distribution.low}</span>
            <span style={CARD_LABEL}>Low</span>
          </div>
          <div style={{ ...CARD_STYLE, borderColor: "#fde68a", backgroundColor: "#fffbeb" }}>
            <span style={CARD_VALUE}>{data.risk_distribution.medium}</span>
            <span style={CARD_LABEL}>Medium</span>
          </div>
          <div style={{ ...CARD_STYLE, borderColor: "#fca5a5", backgroundColor: "#fef2f2" }}>
            <span style={CARD_VALUE}>{data.risk_distribution.high}</span>
            <span style={CARD_LABEL}>High</span>
          </div>
          <div style={{ ...CARD_STYLE, borderColor: "#f87171", backgroundColor: "#fee2e2", color: "#991b1b" }}>
            <span style={CARD_VALUE}>{data.risk_distribution.critical}</span>
            <span style={CARD_LABEL}>Critical</span>
          </div>
        </div>
      </div>

      <div>
        <div style={SECTION_TITLE}>Reviewer Recommendations</div>
        <div style={{ display: "flex", gap: "8px" }}>
          <div style={CARD_STYLE}>
            <span style={CARD_VALUE}>{data.reviewer_stats.recommendations_made}</span>
            <span style={CARD_LABEL}>Made</span>
          </div>
          <div style={CARD_STYLE}>
            <span style={CARD_VALUE}>{data.reviewer_stats.abstentions}</span>
            <span style={CARD_LABEL}>Abstained</span>
          </div>
        </div>
      </div>
    </div>
  );
};
