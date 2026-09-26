/**
 * Tests for extractPRContext — the GitHub PR URL parser.
 *
 * These are purely deterministic unit tests with no external dependencies.
 * Every code path is exercised to ensure the parser is robust against
 * the range of GitHub URLs the content script may encounter.
 */

import { describe, it, expect } from "vitest";
import { extractPRContext } from "../content/github-pr";

describe("extractPRContext", () => {
  // ── Valid PR URLs ───────────────────────────────────────────────────────────

  it("parses a standard PR URL", () => {
    const result = extractPRContext(
      "https://github.com/SathwikGoundla/GitReview-AI/pull/42"
    );
    expect(result).toEqual({
      owner: "SathwikGoundla",
      repo: "GitReview-AI",
      pullNumber: 42,
    });
  });

  it("parses a PR URL with a /files suffix", () => {
    const result = extractPRContext(
      "https://github.com/SathwikGoundla/GitReview-AI/pull/42/files"
    );
    expect(result).toEqual({
      owner: "SathwikGoundla",
      repo: "GitReview-AI",
      pullNumber: 42,
    });
  });

  it("parses a PR URL with a /commits suffix", () => {
    const result = extractPRContext(
      "https://github.com/SathwikGoundla/GitReview-AI/pull/42/commits"
    );
    expect(result).toEqual({
      owner: "SathwikGoundla",
      repo: "GitReview-AI",
      pullNumber: 42,
    });
  });

  it("parses a PR URL with query params", () => {
    const result = extractPRContext(
      "https://github.com/owner/repo/pull/7?diff=split&w=1"
    );
    expect(result).toEqual({ owner: "owner", repo: "repo", pullNumber: 7 });
  });

  it("handles PR number 1", () => {
    const result = extractPRContext(
      "https://github.com/owner/repo/pull/1"
    );
    expect(result?.pullNumber).toBe(1);
  });

  it("handles large PR numbers", () => {
    const result = extractPRContext(
      "https://github.com/owner/repo/pull/99999"
    );
    expect(result?.pullNumber).toBe(99999);
  });

  it("handles org/team repos with hyphenated names", () => {
    const result = extractPRContext(
      "https://github.com/my-org/my-project-backend/pull/123"
    );
    expect(result).toEqual({
      owner: "my-org",
      repo: "my-project-backend",
      pullNumber: 123,
    });
  });

  // ── Non-PR GitHub URLs — must return null ──────────────────────────────────

  it("returns null for a repository root", () => {
    expect(
      extractPRContext("https://github.com/SathwikGoundla/GitReview-AI")
    ).toBeNull();
  });

  it("returns null for an issues URL", () => {
    expect(
      extractPRContext(
        "https://github.com/SathwikGoundla/GitReview-AI/issues/5"
      )
    ).toBeNull();
  });

  it("returns null for a commit URL", () => {
    expect(
      extractPRContext(
        "https://github.com/SathwikGoundla/GitReview-AI/commit/abc123"
      )
    ).toBeNull();
  });

  it("returns null for GitHub root", () => {
    expect(extractPRContext("https://github.com/")).toBeNull();
  });

  it("returns null for a non-GitHub URL", () => {
    expect(
      extractPRContext("https://gitlab.com/owner/repo/merge_requests/1")
    ).toBeNull();
  });

  it("returns null for a Google URL", () => {
    expect(extractPRContext("https://google.com")).toBeNull();
  });

  // ── Edge / invalid cases ───────────────────────────────────────────────────

  it("returns null for PR number 0", () => {
    expect(
      extractPRContext("https://github.com/owner/repo/pull/0")
    ).toBeNull();
  });

  it("returns null for non-numeric PR segment", () => {
    expect(
      extractPRContext("https://github.com/owner/repo/pull/abc")
    ).toBeNull();
  });

  it("returns null for an empty string", () => {
    expect(extractPRContext("")).toBeNull();
  });

  it("returns null for a completely invalid URL", () => {
    expect(extractPRContext("not-a-url")).toBeNull();
  });

  it("returns null for a URL with only two segments", () => {
    expect(extractPRContext("https://github.com/owner")).toBeNull();
  });
});
