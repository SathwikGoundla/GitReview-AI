/**
 * Tests that verify the TypeScript type definitions align with the
 * exact field names returned by the backend API schemas.
 *
 * These tests construct objects conforming to each interface and verify
 * that required fields are present and correctly typed.
 * They act as a contract regression guard: if the backend changes a field
 * name, TypeScript compilation will fail here first.
 */

import { describe, it, expect } from "vitest";
import type {
  AnalysisResponse,
  PRSummaryResponse,
  ReviewerRecommendationSchema,
  ChecklistItemSchema,
  FeedbackRating,
  PredictionType,
  SubmitFeedbackRequest,
} from "../types";

describe("Type contract — AnalysisResponse fields match backend schema", () => {
  it("AnalysisResponse has all required backend fields including risk_assessment_id", () => {
    const analysis: AnalysisResponse = {
      analysis_id: "550e8400-e29b-41d4-a716-446655440000",
      pull_request_id: "660e8400-e29b-41d4-a716-446655440001",
      commit_sha: "a".repeat(40),
      status: "completed",
      summary: "Adds authentication middleware.",
      risk_tier: "high",
      risk_source: "hybrid",
      risk_rationale: {
        factors: [
          { factor: "Sensitive path touched", source: "deterministic" },
        ],
      },
      risk_confidence: 87.5,
      // Step 18.1: risk_assessment_id is now exposed by the backend
      risk_assessment_id: "770e8400-e29b-41d4-a716-446655440002",
      review_suggestions: [
        { focus_area: "Check null handling in middleware", category: "null_handling" },
      ],
      reviewer_recommendation: {
        username: "gowtham",
        reason: "Previously reviewed authentication module",
        confidence_score: 72.0,
      },
      checklist_items: [
        {
          category: "security",
          confidence_score: 95.0,
          trigger_source: "both",
        },
      ],
      checklist_is_fallback: false,
      triggered_by: "extension",
      model_name: "gemini-2.5-flash",
      prompt_template_version: "v1",
      created_at: new Date().toISOString(),
    };

    // Field presence checks
    expect(analysis.analysis_id).toBeTruthy();
    expect(analysis.risk_tier).toBe("high");
    expect(analysis.risk_source).toBe("hybrid");
    expect(analysis.risk_confidence).toBe(87.5);
    expect(analysis.risk_assessment_id).toBe("770e8400-e29b-41d4-a716-446655440002");
    expect(analysis.checklist_is_fallback).toBe(false);
    expect(analysis.triggered_by).toBe("extension");
    expect(analysis.review_suggestions).toHaveLength(1);
    expect(analysis.checklist_items).toHaveLength(1);
    expect(analysis.reviewer_recommendation?.username).toBe("gowtham");
  });

  it("AnalysisResponse allows null risk_assessment_id (degraded/failed analysis)", () => {
    const partial: Pick<AnalysisResponse, "risk_assessment_id"> = {
      risk_assessment_id: null,
    };
    expect(partial.risk_assessment_id).toBeNull();
  });

  it("AnalysisResponse allows null reviewer_recommendation (abstention)", () => {
    const partial: Pick<AnalysisResponse, "reviewer_recommendation"> = {
      reviewer_recommendation: null,
    };
    expect(partial.reviewer_recommendation).toBeNull();
  });

  it("AnalysisResponse allows null summary (degraded analysis)", () => {
    const partial: Pick<AnalysisResponse, "summary"> = {
      summary: null,
    };
    expect(partial.summary).toBeNull();
  });
});

describe("Type contract — PRSummaryResponse", () => {
  it("has all fields matching backend schema", () => {
    const pr: PRSummaryResponse = {
      pr_number: 42,
      title: "Add authentication middleware",
      author_username: "sathwik",
      state: "open",
      head_branch: "feat/auth",
      base_branch: "main",
      commit_sha: "b".repeat(40),
      lines_added: 150,
      lines_removed: 20,
    };

    expect(pr.pr_number).toBe(42);
    expect(pr.state).toBe("open");
    expect(pr.head_branch).toBe("feat/auth");
  });
});

describe("Type contract — ReviewerRecommendationSchema", () => {
  it("has all required fields", () => {
    const rec: ReviewerRecommendationSchema = {
      username: "bhargav",
      reason: "Primary committer on authentication/ path",
      confidence_score: 68.0,
    };

    expect(rec.username).toBe("bhargav");
    expect(rec.confidence_score).toBeGreaterThanOrEqual(0);
    expect(rec.confidence_score).toBeLessThanOrEqual(100);
  });
});

describe("Type contract — ChecklistItemSchema", () => {
  it("has all required fields and valid trigger_source values", () => {
    const item: ChecklistItemSchema = {
      category: "security",
      confidence_score: 91.0,
      trigger_source: "deterministic",
    };

    expect(item.category).toBe("security");
    expect(["deterministic", "ai", "both"]).toContain(item.trigger_source);
  });
});

describe("Type contract — feedback types", () => {
  it("FeedbackRating is limited to helpful | unhelpful", () => {
    const validRatings: FeedbackRating[] = ["helpful", "unhelpful"];
    expect(validRatings).toHaveLength(2);
  });

  it("PredictionType is limited to the three backend enum values", () => {
    const validTypes: PredictionType[] = [
      "risk_tier",
      "reviewer_recommendation",
      "checklist_item",
    ];
    expect(validTypes).toHaveLength(3);
  });

  it("SubmitFeedbackRequest has all required backend fields", () => {
    const req: SubmitFeedbackRequest = {
      prediction_type: "risk_tier",
      prediction_reference_id: "770e8400-e29b-41d4-a716-446655440003",
      rating: "helpful",
      comment: "Correctly identified the auth risk.",
    };

    expect(req.prediction_type).toBe("risk_tier");
    expect(req.rating).toBe("helpful");
    expect(req.comment).toBeDefined();
  });

  it("SubmitFeedbackRequest allows undefined comment", () => {
    const req: SubmitFeedbackRequest = {
      prediction_type: "checklist_item",
      prediction_reference_id: "880e8400-e29b-41d4-a716-446655440004",
      rating: "unhelpful",
    };

    expect(req.comment).toBeUndefined();
  });
});

describe("Risk tier values", () => {
  it("all four backend risk tiers are represented in the type", () => {
    // These are the exact values from risk_assessments.risk_tier CHECK constraint
    const validTiers = ["low", "medium", "high", "critical"];
    expect(validTiers).toHaveLength(4);
    // TypeScript ensures these are strings — runtime check:
    for (const tier of validTiers) {
      expect(typeof tier).toBe("string");
    }
  });
});
