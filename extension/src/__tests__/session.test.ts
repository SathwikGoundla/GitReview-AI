/**
 * Tests for auth/session.ts — chrome.storage.local session management.
 * The chrome mock is set up in test-setup.ts (clears before each test).
 */

import { describe, it, expect } from "vitest";
import {
  saveSession,
  getSession,
  clearSession,
  getSessionToken,
  isAuthenticated,
} from "../auth/session";
import type { UserProfile } from "../types";

const MOCK_USER: UserProfile = {
  id: "550e8400-e29b-41d4-a716-446655440000",
  github_username: "sathwik",
  avatar_url: "https://avatars.githubusercontent.com/u/12345?v=4",
};

const MOCK_TOKEN = "raw-opaque-session-token-abc123";

describe("session management", () => {
  it("returns null when no session is stored", async () => {
    const session = await getSession();
    expect(session).toBeNull();
  });

  it("returns null token when no session is stored", async () => {
    const token = await getSessionToken();
    expect(token).toBeNull();
  });

  it("isAuthenticated returns false when no session is stored", async () => {
    const auth = await isAuthenticated();
    expect(auth).toBe(false);
  });

  it("saves and retrieves a session", async () => {
    await saveSession(MOCK_TOKEN, MOCK_USER);
    const session = await getSession();
    expect(session).not.toBeNull();
    expect(session!.token).toBe(MOCK_TOKEN);
    expect(session!.user.github_username).toBe("sathwik");
    expect(session!.user.id).toBe(MOCK_USER.id);
  });

  it("getSessionToken returns the token after saving", async () => {
    await saveSession(MOCK_TOKEN, MOCK_USER);
    const token = await getSessionToken();
    expect(token).toBe(MOCK_TOKEN);
  });

  it("isAuthenticated returns true after saving a session", async () => {
    await saveSession(MOCK_TOKEN, MOCK_USER);
    const auth = await isAuthenticated();
    expect(auth).toBe(true);
  });

  it("clearSession removes the session", async () => {
    await saveSession(MOCK_TOKEN, MOCK_USER);
    await clearSession();
    const session = await getSession();
    expect(session).toBeNull();
  });

  it("getSessionToken returns null after clearing", async () => {
    await saveSession(MOCK_TOKEN, MOCK_USER);
    await clearSession();
    const token = await getSessionToken();
    expect(token).toBeNull();
  });

  it("isAuthenticated returns false after clearing", async () => {
    await saveSession(MOCK_TOKEN, MOCK_USER);
    await clearSession();
    const auth = await isAuthenticated();
    expect(auth).toBe(false);
  });

  it("overwrites a previous session on re-save", async () => {
    await saveSession(MOCK_TOKEN, MOCK_USER);
    const newToken = "different-token-xyz";
    const newUser: UserProfile = {
      id: "660e8400-e29b-41d4-a716-446655440001",
      github_username: "gowtham",
      avatar_url: null,
    };
    await saveSession(newToken, newUser);
    const session = await getSession();
    expect(session!.token).toBe(newToken);
    expect(session!.user.github_username).toBe("gowtham");
  });

  it("stores avatar_url as null when not provided", async () => {
    const userNoAvatar: UserProfile = {
      id: "770e8400-e29b-41d4-a716-446655440002",
      github_username: "bhargav",
      avatar_url: null,
    };
    await saveSession(MOCK_TOKEN, userNoAvatar);
    const session = await getSession();
    expect(session!.user.avatar_url).toBeNull();
  });
});
