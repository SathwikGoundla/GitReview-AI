import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Dashboard } from "../components/Dashboard";
import { AnalyticsView } from "../components/AnalyticsView";
import { RepositoryManager } from "../components/RepositoryManager";
import * as apiClient from "../api/client";

// Mock the API client
vi.mock("../api/client", () => ({
  apiGetUserAnalytics: vi.fn(),
  apiGetRepositoryAnalytics: vi.fn(),
  apiListRepositories: vi.fn(),
  apiRevokeRepositoryAccess: vi.fn(),
}));

describe("Dashboard & Analytics Components", () => {
  const mockUserAnalytics = {
    total_analyses: 10,
    completed_analyses: 10,
    degraded_analyses: 0,
    failed_analyses: 0,
    unique_prs_analyzed: 5,
    risk_distribution: { low: 2, medium: 4, high: 3, critical: 1 },
    avg_confidence: 85,
    feedback_given: { helpful: 8, unhelpful: 2, total: 10, helpful_percentage: 0.8 },
    reviewer_stats: { recommendations_made: 8, abstentions: 2 },
    authorized_repository_count: 2,
    first_analysis_at: "2023-01-01T00:00:00Z",
    latest_analysis_at: "2023-01-10T00:00:00Z",
  };

  const mockRepoAnalytics = {
    repository_id: "repo-123",
    full_name: "test/repo",
    github_repo_id: 1234,
    total_analyses: 5,
    completed_analyses: 5,
    degraded_analyses: 0,
    failed_analyses: 0,
    unique_prs_analyzed: 3,
    risk_distribution: { low: 1, medium: 2, high: 2, critical: 0 },
    avg_confidence: 90,
    feedback_received: { helpful: 4, unhelpful: 1, total: 5, helpful_percentage: 0.8 },
    reviewer_stats: { recommendations_made: 4, abstentions: 1 },
    authorized_user_count: 3,
    first_analysis_at: "2023-01-01T00:00:00Z",
    latest_analysis_at: "2023-01-10T00:00:00Z",
  };

  const mockRepos = {
    repositories: [
      {
        repository: { id: "repo-123", full_name: "test/repo", github_repo_id: 1, owner: "test", name: "repo", default_branch: "main" },
        access: { repository_id: "repo-123", authorized_at: "2023-01-01T00:00:00Z", is_active: true, github_permission_level: "write" }
      }
    ],
    total: 1
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("AnalyticsView", () => {
    it("renders zero state when total_analyses is 0", () => {
      render(<AnalyticsView data={{ ...mockUserAnalytics, total_analyses: 0, feedback: mockUserAnalytics.feedback_given }} title="Test" />);
      expect(screen.getByText("No analyses yet.")).toBeInTheDocument();
    });

    it("renders analytics correctly", () => {
      render(<AnalyticsView data={{ ...mockUserAnalytics, feedback: mockUserAnalytics.feedback_given }} title="Your Analytics" />);
      expect(screen.getByText("Your Analytics")).toBeInTheDocument();
      expect(screen.getByText("Total")).toBeInTheDocument();
      expect(screen.getByText("10")).toBeInTheDocument(); // total
      expect(screen.getByText("80%")).toBeInTheDocument(); // helpful
    });
  });

  describe("RepositoryManager", () => {
    it("renders loading state initially", () => {
      vi.mocked(apiClient.apiListRepositories).mockReturnValue(new Promise(() => {}));
      render(<RepositoryManager onSelectRepository={vi.fn()} />);
      expect(screen.getByText("Loading repositories...")).toBeInTheDocument();
    });

    it("renders error state", async () => {
      vi.mocked(apiClient.apiListRepositories).mockRejectedValue(new Error("Network Error"));
      render(<RepositoryManager onSelectRepository={vi.fn()} />);
      await waitFor(() => expect(screen.getByText("Network Error")).toBeInTheDocument());
    });

    it("renders empty state", async () => {
      vi.mocked(apiClient.apiListRepositories).mockResolvedValue({ repositories: [], total: 0 });
      render(<RepositoryManager onSelectRepository={vi.fn()} />);
      await waitFor(() => expect(screen.getByText("No authorized repositories yet.")).toBeInTheDocument());
    });

    it("renders repositories and supports revoke", async () => {
      vi.mocked(apiClient.apiListRepositories).mockResolvedValue(mockRepos);
      vi.mocked(apiClient.apiRevokeRepositoryAccess).mockResolvedValue({ message: "revoked", repository_id: "repo-123" });
      
      // Mock window.confirm
      const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

      render(<RepositoryManager onSelectRepository={vi.fn()} />);
      
      await waitFor(() => expect(screen.getByText("test/repo")).toBeInTheDocument());
      
      const revokeBtn = screen.getByText("Revoke");
      fireEvent.click(revokeBtn);

      expect(confirmSpy).toHaveBeenCalled();
      await waitFor(() => expect(apiClient.apiRevokeRepositoryAccess).toHaveBeenCalledWith("repo-123"));
      
      // Should be removed from list
      expect(screen.queryByText("test/repo")).not.toBeInTheDocument();
      
      confirmSpy.mockRestore();
    });

    it("supports stats selection", async () => {
      vi.mocked(apiClient.apiListRepositories).mockResolvedValue(mockRepos);
      const onSelect = vi.fn();
      render(<RepositoryManager onSelectRepository={onSelect} />);
      
      await waitFor(() => expect(screen.getByText("test/repo")).toBeInTheDocument());
      
      const statsBtn = screen.getByText("Stats");
      fireEvent.click(statsBtn);

      expect(onSelect).toHaveBeenCalledWith("repo-123", "test/repo");
    });
  });

  describe("Dashboard", () => {
    it("loads and displays user analytics and repos", async () => {
      vi.mocked(apiClient.apiGetUserAnalytics).mockResolvedValue(mockUserAnalytics as any);
      vi.mocked(apiClient.apiListRepositories).mockResolvedValue(mockRepos);

      render(<Dashboard />);
      
      await waitFor(() => {
        expect(screen.getByText("Your Analytics")).toBeInTheDocument();
        expect(screen.getByText("test/repo")).toBeInTheDocument();
      });
    });

    it("handles repo selection and back navigation", async () => {
      vi.mocked(apiClient.apiGetUserAnalytics).mockResolvedValue(mockUserAnalytics as any);
      vi.mocked(apiClient.apiListRepositories).mockResolvedValue(mockRepos);
      vi.mocked(apiClient.apiGetRepositoryAnalytics).mockResolvedValue(mockRepoAnalytics as any);

      render(<Dashboard />);
      
      await waitFor(() => expect(screen.getByText("test/repo")).toBeInTheDocument());
      
      const statsBtn = screen.getByText("Stats");
      fireEvent.click(statsBtn);

      await waitFor(() => {
        expect(screen.getByText("test/repo Analytics")).toBeInTheDocument();
      });

      const backBtn = screen.getByText("← Back to Dashboard");
      fireEvent.click(backBtn);

      await waitFor(() => {
        expect(screen.getByText("Your Analytics")).toBeInTheDocument();
      });
    });
  });
});
