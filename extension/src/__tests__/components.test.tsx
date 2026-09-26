/**
 * Tests for React components — render output verification.
 * Uses @testing-library/react for DOM queries.
 */

import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { RiskBadge } from "../components/RiskBadge";
import { ConfidenceBar } from "../components/ConfidenceBar";
import { ReviewerCard } from "../components/ReviewerCard";
import { Checklist } from "../components/Checklist";
import type { ChecklistItemSchema, ReviewerRecommendationSchema } from "../types";

// ── RiskBadge ─────────────────────────────────────────────────────────────────

describe("RiskBadge", () => {
  it("renders LOW for risk_tier=low", () => {
    render(<RiskBadge tier="low" />);
    expect(screen.getByText("LOW")).toBeTruthy();
  });

  it("renders MEDIUM for risk_tier=medium", () => {
    render(<RiskBadge tier="medium" />);
    expect(screen.getByText("MEDIUM")).toBeTruthy();
  });

  it("renders HIGH for risk_tier=high", () => {
    render(<RiskBadge tier="high" />);
    expect(screen.getByText("HIGH")).toBeTruthy();
  });

  it("renders CRITICAL for risk_tier=critical", () => {
    render(<RiskBadge tier="critical" />);
    expect(screen.getByText("CRITICAL")).toBeTruthy();
  });

  it("renders UNKNOWN for an unexpected tier", () => {
    render(<RiskBadge tier="extreme" />);
    expect(screen.getByText("UNKNOWN")).toBeTruthy();
  });

  it("is case-insensitive for tier names", () => {
    render(<RiskBadge tier="HIGH" />);
    expect(screen.getByText("HIGH")).toBeTruthy();
  });
});

// ── ConfidenceBar ─────────────────────────────────────────────────────────────

describe("ConfidenceBar", () => {
  it("shows High band for score >= 80", () => {
    render(<ConfidenceBar score={85} />);
    expect(screen.getByText(/85%.*High/)).toBeTruthy();
  });

  it("shows Moderate band for score 50–79", () => {
    render(<ConfidenceBar score={65} />);
    expect(screen.getByText(/65%.*Moderate/)).toBeTruthy();
  });

  it("shows Low band for score < 50", () => {
    render(<ConfidenceBar score={30} />);
    expect(screen.getByText(/30%.*Low/)).toBeTruthy();
  });

  it("clamps score to 100 if over", () => {
    render(<ConfidenceBar score={110} />);
    expect(screen.getByText(/100%/)).toBeTruthy();
  });

  it("clamps score to 0 if negative", () => {
    render(<ConfidenceBar score={-5} />);
    expect(screen.getByText(/0%/)).toBeTruthy();
  });

  it("renders a custom label", () => {
    render(<ConfidenceBar score={75} label="Reviewer confidence" />);
    expect(screen.getByText("Reviewer confidence")).toBeTruthy();
  });

  it("renders the default 'Confidence' label", () => {
    render(<ConfidenceBar score={60} />);
    expect(screen.getByText("Confidence")).toBeTruthy();
  });
});

// ── ReviewerCard ──────────────────────────────────────────────────────────────

describe("ReviewerCard", () => {
  it("shows abstention message when recommendation is null", () => {
    render(<ReviewerCard recommendation={null} />);
    expect(
      screen.getByText(/insufficient repository history/i)
    ).toBeTruthy();
  });

  it("shows reviewer username when recommendation is present", () => {
    const rec: ReviewerRecommendationSchema = {
      username: "gowtham",
      reason: "Primary reviewer of authentication module",
      confidence_score: 72.0,
    };
    render(<ReviewerCard recommendation={rec} />);
    expect(screen.getByText(/@gowtham/)).toBeTruthy();
  });

  it("shows the reason when recommendation is present", () => {
    const rec: ReviewerRecommendationSchema = {
      username: "bhargav",
      reason: "Primary reviewer of authentication module",
      confidence_score: 68.0,
    };
    render(<ReviewerCard recommendation={rec} />);
    expect(
      screen.getByText("Primary reviewer of authentication module")
    ).toBeTruthy();
  });

  it("renders a GitHub profile link", () => {
    const rec: ReviewerRecommendationSchema = {
      username: "sumedh",
      reason: "CODEOWNERS match",
      confidence_score: 90.0,
    };
    render(<ReviewerCard recommendation={rec} />);
    const link = screen.getByRole("link");
    expect(link.getAttribute("href")).toContain("github.com/sumedh");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
  });
});

// ── Checklist ─────────────────────────────────────────────────────────────────

describe("Checklist", () => {
  const items: ChecklistItemSchema[] = [
    { category: "security", confidence_score: 95.0, trigger_source: "deterministic" },
    { category: "testing", confidence_score: 82.0, trigger_source: "ai" },
    { category: "null_handling", confidence_score: 60.0, trigger_source: "both" },
  ];

  it("renders human-readable category labels", () => {
    render(<Checklist items={items} isFallback={false} />);
    expect(screen.getByText("Security Validation")).toBeTruthy();
    expect(screen.getByText("Test Coverage")).toBeTruthy();
    expect(screen.getByText("Null Handling")).toBeTruthy();
  });

  it("shows 0/N checked by default", () => {
    render(<Checklist items={items} isFallback={false} />);
    expect(screen.getByText("0/3 checked")).toBeTruthy();
  });

  it("increments checked count when an item is checked", () => {
    render(<Checklist items={items} isFallback={false} />);
    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[0]);
    expect(screen.getByText("1/3 checked")).toBeTruthy();
  });

  it("decrements when unchecked again", () => {
    render(<Checklist items={items} isFallback={false} />);
    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[0]);
    expect(screen.getByText("0/3 checked")).toBeTruthy();
  });

  it("shows fallback badge when isFallback is true", () => {
    render(<Checklist items={items} isFallback={true} />);
    expect(screen.getByText(/baseline/i)).toBeTruthy();
  });

  it("does not show fallback badge when isFallback is false", () => {
    render(<Checklist items={items} isFallback={false} />);
    expect(screen.queryByText(/baseline/i)).toBeNull();
  });

  it("shows empty message when no items", () => {
    render(<Checklist items={[]} isFallback={false} />);
    expect(screen.getByText(/no checklist items/i)).toBeTruthy();
  });

  it("shows source labels", () => {
    render(<Checklist items={items} isFallback={false} />);
    expect(screen.getByText("rule")).toBeTruthy();
    expect(screen.getByText("AI")).toBeTruthy();
    expect(screen.getByText("rule+AI")).toBeTruthy();
  });

  it("renders a local-state caveat note", () => {
    render(<Checklist items={items} isFallback={false} />);
    expect(screen.getByText(/local to this session/i)).toBeTruthy();
  });
});

// ── FeedbackForm (Step 18.1) ──────────────────────────────────────────────────

import { vi, afterEach } from "vitest";
import { FeedbackForm } from "../components/FeedbackForm";
import { waitFor } from "@testing-library/react";

const MOCK_ANALYSIS_ID = "550e8400-e29b-41d4-a716-446655440000";
const MOCK_RISK_ID = "660e8400-e29b-41d4-a716-446655440001";

// Save and restore fetch
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("FeedbackForm (Step 18.1 — real submission)", () => {
  it("shows 'Was this helpful?' buttons when predictionReferenceId is present", () => {
    render(
      <FeedbackForm
        analysisId={MOCK_ANALYSIS_ID}
        predictionType="risk_tier"
        predictionReferenceId={MOCK_RISK_ID}
      />
    );
    expect(screen.getByText("Was this helpful?")).toBeTruthy();
    expect(screen.getByRole("button", { name: /mark as helpful/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /mark as unhelpful/i })).toBeTruthy();
  });

  it("shows unavailable message when predictionReferenceId is null", () => {
    render(
      <FeedbackForm
        analysisId={MOCK_ANALYSIS_ID}
        predictionType="risk_tier"
        predictionReferenceId={null}
      />
    );
    expect(screen.getByText(/unavailable/i)).toBeTruthy();
    expect(screen.queryByText("Was this helpful?")).toBeNull();
  });

  it("calls the feedback API with correct payload on helpful click", async () => {
    // Provide a session so the API client attaches X-Session-Token
    await chrome.storage.local.set({
      gitreview_session: {
        token: "test-token",
        user: { id: "u1", github_username: "sathwik", avatar_url: null },
      },
    });

    let capturedBody: Record<string, unknown> = {};
    globalThis.fetch = vi.fn().mockImplementation((_url: string, init: RequestInit) => {
      capturedBody = JSON.parse(init.body as string);
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({
          feedback_id: "aaa-bbb",
          analysis_id: MOCK_ANALYSIS_ID,
          prediction_type: "risk_tier",
          prediction_reference_id: MOCK_RISK_ID,
          rating: "helpful",
          created_at: new Date().toISOString(),
        }),
      });
    });

    render(
      <FeedbackForm
        analysisId={MOCK_ANALYSIS_ID}
        predictionType="risk_tier"
        predictionReferenceId={MOCK_RISK_ID}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /mark as helpful/i }));

    await waitFor(() => {
      expect(screen.getByText(/feedback recorded/i)).toBeTruthy();
    });

    expect(capturedBody.prediction_type).toBe("risk_tier");
    expect(capturedBody.prediction_reference_id).toBe(MOCK_RISK_ID);
    expect(capturedBody.rating).toBe("helpful");
  });

  it("calls the feedback API with unhelpful rating", async () => {
    let capturedBody: Record<string, unknown> = {};
    globalThis.fetch = vi.fn().mockImplementation((_url: string, init: RequestInit) => {
      capturedBody = JSON.parse(init.body as string);
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({
          feedback_id: "ccc-ddd",
          analysis_id: MOCK_ANALYSIS_ID,
          prediction_type: "risk_tier",
          prediction_reference_id: MOCK_RISK_ID,
          rating: "unhelpful",
          created_at: new Date().toISOString(),
        }),
      });
    });

    render(
      <FeedbackForm
        analysisId={MOCK_ANALYSIS_ID}
        predictionType="risk_tier"
        predictionReferenceId={MOCK_RISK_ID}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /mark as unhelpful/i }));

    await waitFor(() => {
      expect(screen.getByText(/feedback recorded.*unhelpful/i)).toBeTruthy();
    });

    expect(capturedBody.rating).toBe("unhelpful");
  });

  it("shows success state with Change option after submission", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        feedback_id: "eee-fff",
        analysis_id: MOCK_ANALYSIS_ID,
        prediction_type: "risk_tier",
        prediction_reference_id: MOCK_RISK_ID,
        rating: "helpful",
        created_at: new Date().toISOString(),
      }),
    });

    render(
      <FeedbackForm
        analysisId={MOCK_ANALYSIS_ID}
        predictionType="risk_tier"
        predictionReferenceId={MOCK_RISK_ID}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /mark as helpful/i }));

    await waitFor(() => {
      expect(screen.getByText(/feedback recorded/i)).toBeTruthy();
      expect(screen.getByRole("button", { name: /change/i })).toBeTruthy();
    });
  });

  it("shows error message and Retry on 401", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ error: "invalid_session", message: "Session expired." }),
    });

    render(
      <FeedbackForm
        analysisId={MOCK_ANALYSIS_ID}
        predictionType="risk_tier"
        predictionReferenceId={MOCK_RISK_ID}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /mark as helpful/i }));

    await waitFor(() => {
      expect(screen.getByText(/session expired/i)).toBeTruthy();
      expect(screen.getByRole("button", { name: /retry/i })).toBeTruthy();
    });
  });

  it("shows error on 400 validation error", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ detail: "validation error" }),
    });

    render(
      <FeedbackForm
        analysisId={MOCK_ANALYSIS_ID}
        predictionType="risk_tier"
        predictionReferenceId={MOCK_RISK_ID}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /mark as helpful/i }));

    await waitFor(() => {
      // Shows some error message
      expect(screen.getByText(/retry/i)).toBeTruthy();
    });
  });

  it("shows error on network failure", async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));

    render(
      <FeedbackForm
        analysisId={MOCK_ANALYSIS_ID}
        predictionType="risk_tier"
        predictionReferenceId={MOCK_RISK_ID}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /mark as helpful/i }));

    await waitFor(() => {
      expect(screen.getByText(/retry/i)).toBeTruthy();
    });
  });

  it("Retry button re-enables the form after error", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ error: "invalid_session", message: "Session expired." }),
    });

    render(
      <FeedbackForm
        analysisId={MOCK_ANALYSIS_ID}
        predictionType="risk_tier"
        predictionReferenceId={MOCK_RISK_ID}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /mark as helpful/i }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /retry/i })).toBeTruthy();
    });

    fireEvent.click(screen.getByRole("button", { name: /retry/i }));

    // After retry, the form should be back in idle state showing the rating buttons
    await waitFor(() => {
      expect(screen.getByText("Was this helpful?")).toBeTruthy();
    });
  });

  it("calls onFeedbackSubmitted callback with the rating", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        feedback_id: "ggg-hhh",
        analysis_id: MOCK_ANALYSIS_ID,
        prediction_type: "risk_tier",
        prediction_reference_id: MOCK_RISK_ID,
        rating: "helpful",
        created_at: new Date().toISOString(),
      }),
    });

    const onSubmitted = vi.fn();
    render(
      <FeedbackForm
        analysisId={MOCK_ANALYSIS_ID}
        predictionType="risk_tier"
        predictionReferenceId={MOCK_RISK_ID}
        onFeedbackSubmitted={onSubmitted}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /mark as helpful/i }));

    await waitFor(() => {
      expect(onSubmitted).toHaveBeenCalledWith("helpful");
    });
  });
});
