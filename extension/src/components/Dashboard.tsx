import React, { useEffect, useState } from "react";
import { apiGetUserAnalytics, apiGetRepositoryAnalytics } from "../api/client";
import { AnalyticsView, AnalyticsData } from "./AnalyticsView";
import { RepositoryManager } from "./RepositoryManager";

export const Dashboard: React.FC = () => {
  const [userAnalytics, setUserAnalytics] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedRepoId, setSelectedRepoId] = useState<string | null>(null);
  const [selectedRepoName, setSelectedRepoName] = useState<string | null>(null);
  const [repoAnalytics, setRepoAnalytics] = useState<AnalyticsData | null>(null);
  const [repoLoading, setRepoLoading] = useState(false);
  const [repoError, setRepoError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    apiGetUserAnalytics()
      .then((res) => {
        if (mounted) {
          // Map to unified AnalyticsData
          setUserAnalytics({
            ...res,
            feedback: res.feedback_given,
          });
          setLoading(false);
        }
      })
      .catch((err) => {
        if (mounted) {
          setError(err.message || "Failed to load user analytics");
          setLoading(false);
        }
      });
    return () => {
      mounted = false;
    };
  }, []);

  const handleSelectRepository = async (repoId: string, repoName: string) => {
    setSelectedRepoId(repoId);
    setSelectedRepoName(repoName);
    setRepoLoading(true);
    setRepoError(null);
    try {
      const res = await apiGetRepositoryAnalytics(repoId);
      setRepoAnalytics({
        ...res,
        feedback: res.feedback_received,
      });
    } catch (err) {
      setRepoError(err instanceof Error ? err.message : "Failed to load repository analytics");
    } finally {
      setRepoLoading(false);
    }
  };

  const handleBack = () => {
    setSelectedRepoId(null);
    setSelectedRepoName(null);
    setRepoAnalytics(null);
  };

  if (selectedRepoId) {
    return (
      <div style={{ padding: "14px" }}>
        <button
          onClick={handleBack}
          style={{
            background: "none",
            border: "none",
            color: "#2563eb",
            cursor: "pointer",
            fontSize: "12px",
            padding: 0,
            marginBottom: "12px",
          }}
        >
          &larr; Back to Dashboard
        </button>
        {repoLoading && <div style={{ fontSize: "12px", color: "#6b7280" }}>Loading repository stats...</div>}
        {repoError && <div style={{ fontSize: "12px", color: "#ef4444" }}>{repoError}</div>}
        {repoAnalytics && <AnalyticsView data={repoAnalytics} title={`${selectedRepoName} Analytics`} />}
      </div>
    );
  }

  return (
    <div style={{ padding: "14px", display: "flex", flexDirection: "column", gap: "24px" }}>
      <div>
        {loading && <div style={{ fontSize: "12px", color: "#6b7280" }}>Loading your stats...</div>}
        {error && <div style={{ fontSize: "12px", color: "#ef4444" }}>{error}</div>}
        {userAnalytics && <AnalyticsView data={userAnalytics} title="Your Analytics" />}
      </div>
      
      <div style={{ borderTop: "1px solid #e5e7eb", paddingTop: "8px" }}>
        <RepositoryManager onSelectRepository={handleSelectRepository} />
      </div>
    </div>
  );
};
