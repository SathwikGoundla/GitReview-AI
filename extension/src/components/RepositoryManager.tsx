import React, { useEffect, useState } from "react";
import { apiListRepositories, apiRevokeRepositoryAccess } from "../api/client";
import type { AuthorizedRepositoryItem } from "../types";

export const RepositoryManager: React.FC<{
  onSelectRepository: (repoId: string, repoName: string) => void;
}> = ({ onSelectRepository }) => {
  const [repositories, setRepositories] = useState<AuthorizedRepositoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    apiListRepositories()
      .then((res) => {
        if (mounted) {
          setRepositories(res.repositories);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (mounted) {
          setError(err.message || "Failed to load repositories");
          setLoading(false);
        }
      });
    return () => {
      mounted = false;
    };
  }, []);

  const handleRevoke = async (repoId: string, repoName: string) => {
    if (!window.confirm(`Are you sure you want to revoke access to ${repoName}?`)) {
      return;
    }
    setRevokingId(repoId);
    try {
      await apiRevokeRepositoryAccess(repoId);
      setRepositories((prev) => prev.filter((r) => r.repository.id !== repoId));
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to revoke access.");
    } finally {
      setRevokingId(null);
    }
  };

  const SECTION_TITLE: React.CSSProperties = {
    fontSize: "11px",
    fontWeight: 600,
    color: "#6b7280",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    marginBottom: "8px",
  };

  if (loading) {
    return <div style={{ fontSize: "12px", color: "#6b7280" }}>Loading repositories...</div>;
  }

  if (error) {
    return <div style={{ fontSize: "12px", color: "#ef4444" }}>{error}</div>;
  }

  if (repositories.length === 0) {
    return (
      <div style={{ padding: "8px 0" }}>
        <div style={SECTION_TITLE}>Authorized Repositories</div>
        <div style={{ fontSize: "12px", color: "#6b7280" }}>No authorized repositories yet.</div>
      </div>
    );
  }

  return (
    <div style={{ padding: "8px 0" }}>
      <div style={SECTION_TITLE}>Authorized Repositories</div>
      <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
        {repositories.map((item) => (
          <div
            key={item.repository.id}
            style={{
              padding: "10px",
              border: "1px solid #e5e7eb",
              borderRadius: "6px",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <div>
              <div style={{ fontSize: "13px", fontWeight: 600, color: "#111827" }}>
                {item.repository.full_name}
              </div>
              <div style={{ fontSize: "11px", color: "#6b7280", marginTop: "2px" }}>
                Authorized: {new Date(item.access.authorized_at).toLocaleDateString()}
              </div>
            </div>
            <div style={{ display: "flex", gap: "6px" }}>
              <button
                onClick={() => onSelectRepository(item.repository.id, item.repository.full_name)}
                style={{
                  backgroundColor: "#f3f4f6",
                  color: "#374151",
                  border: "1px solid #d1d5db",
                  borderRadius: "4px",
                  padding: "4px 8px",
                  fontSize: "11px",
                  cursor: "pointer",
                }}
              >
                Stats
              </button>
              <button
                disabled={revokingId === item.repository.id}
                onClick={() => handleRevoke(item.repository.id, item.repository.full_name)}
                style={{
                  backgroundColor: "#fef2f2",
                  color: "#ef4444",
                  border: "1px solid #fecaca",
                  borderRadius: "4px",
                  padding: "4px 8px",
                  fontSize: "11px",
                  cursor: revokingId === item.repository.id ? "not-allowed" : "pointer",
                }}
              >
                {revokingId === item.repository.id ? "..." : "Revoke"}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
