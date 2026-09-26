/**
 * GitReview AI Extension — Vitest test setup
 *
 * Runs before every test file.
 * Sets up the chrome extension API mock so unit tests do not require
 * an actual Chrome environment.
 */

import "@testing-library/jest-dom";

// ── Chrome API mock ───────────────────────────────────────────────────────────
// The extension uses chrome.storage.local and chrome.runtime.sendMessage.
// We provide minimal mocks for these so tests can run in jsdom.

const mockStorage: Record<string, unknown> = {};

const chromeMock = {
  storage: {
    local: {
      get: async (key: string | string[]) => {
        if (typeof key === "string") {
          return { [key]: mockStorage[key] };
        }
        const result: Record<string, unknown> = {};
        for (const k of key) result[k] = mockStorage[k];
        return result;
      },
      set: async (items: Record<string, unknown>) => {
        Object.assign(mockStorage, items);
      },
      remove: async (key: string | string[]) => {
        const keys = typeof key === "string" ? [key] : key;
        for (const k of keys) delete mockStorage[k];
      },
    },
  },
  runtime: {
    sendMessage: async () => undefined,
    onMessage: {
      addListener: () => undefined,
      removeListener: () => undefined,
    },
  },
  tabs: {
    query: async () => [],
    create: async () => ({ id: 1 }),
    remove: async () => undefined,
    onUpdated: {
      addListener: () => undefined,
      removeListener: () => undefined,
    },
  },
};

// Attach the mock to the global scope so imports of chrome APIs work
(globalThis as Record<string, unknown>).chrome = chromeMock;

// Reset storage before each test
beforeEach(() => {
  for (const key of Object.keys(mockStorage)) {
    delete mockStorage[key];
  }
});
