# GitReview AI — Chrome Extension

A Manifest V3 Chrome Extension that embeds AI-powered Pull Request review assistance directly into GitHub PR pages.

## What It Does

When you open a GitHub Pull Request, the extension:

1. Detects the PR context from the URL
2. Authenticates via GitHub OAuth through the backend
3. Calls the FastAPI backend to run (or retrieve cached) AI analysis
4. Displays inline:
   - **Risk tier** (Low / Medium / High / Critical) with colour coding
   - **Confidence score** (0–100%, colour-banded)
   - **Explainable rationale** — the factors that drove the risk rating
   - **Review focus areas** — specific things to look for in the diff
   - **Suggested reviewer** — from CODEOWNERS and contribution history
   - **Adaptive checklist** — only the dimensions relevant to this PR; items can be checked off and the state is saved to the backend
5. Provides a **Dashboard** view (used by default when no PR page is detected) with individual and repository analytics and repository authorization management

## Prerequisites

- Node.js 18+
- The GitReview AI backend running (see `../backend/`)
- A GitHub OAuth App configured on the backend

## Setup

```bash
cd extension

# Install dependencies
npm install

# Configure the backend URL (copy and edit)
cp .env.example .env
# Edit .env: set VITE_BACKEND_URL=http://localhost:8000
```

## Development Build (watch mode)

```bash
npm run dev
# Rebuilds to dist/ on every source change
```

## Production Build

```bash
# VITE_BACKEND_URL is REQUIRED for a production build; the build fails without it.
VITE_BACKEND_URL=https://your-backend.example npm run build
# Output: extension/dist/  (generated, git-ignored)
```

`npm run package` runs a production build and writes `extension/release/gitreview-ai-extension.zip` (also git-ignored).

## Type-check

```bash
npm run typecheck
```

## Load in Chrome

1. Open `chrome://extensions`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked**
4. Select the `extension/dist/` folder
5. The GitReview AI icon appears in your toolbar

## Tests

```bash
npm test
# 106 tests (Vitest): URL parsing, session management, API client, components, dashboard
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_BACKEND_URL` | `http://localhost:8000` in development builds only; **no default in production builds** (build fails if unset) | FastAPI backend URL (no trailing slash) |

Set in `.env` file (never commit `.env`) or in the environment of the build command. For a production deployment, set `VITE_BACKEND_URL` to your deployed backend URL.

## Authentication Flow

1. Click the extension icon → **Sign in with GitHub**
2. Extension calls `GET /api/auth/login` → opens the GitHub OAuth page
3. After granting access, GitHub redirects to the backend callback
4. The service worker intercepts the callback tab, completes the OAuth exchange
5. Session token stored in `chrome.storage.local`
6. Tab is closed; popup reflects authenticated state

**OAuth callback requirement**: The `GITHUB_REDIRECT_URI` in the backend `.env` must match the callback URL your GitHub OAuth App is configured with.

## Structure

```
extension/
├── public/           # Copied to dist/ as-is
│   ├── manifest.json # Manifest V3 definition
│   └── icon*.png     # Extension icons
├── src/
│   ├── background/   # Service worker (session, OAuth, messaging)
│   ├── content/      # GitHub PR page detection
│   ├── popup/        # React popup app
│   ├── api/          # Typed API client (all backend calls)
│   ├── auth/         # Session storage (chrome.storage.local)
│   ├── components/   # React UI components (analysis, dashboard, analytics, repositories)
│   └── types/        # TypeScript interfaces (mirrors backend schemas)
└── dist/             # Build output (load this in Chrome)
```

## Known Limitations

- **Feedback coverage**: The UI collects feedback for the **risk tier** and the **reviewer recommendation**. The backend also accepts `checklist_item` feedback, but the checklist UI does not expose a feedback control yet.
- **Checklist completion**: Persisted via `PATCH /api/analyses/{analysis_id}/checklist/{item_id}` with an optimistic UI update that reverts if the request fails. Completion is tracked per reviewer by the backend.
- **Not validated against live services**: Extension tests run against mocked fetch/chrome APIs. Behaviour in a real Chrome browser against a deployed backend and live GitHub has not been validated.
- **OAuth callback tab**: Requires the backend running and `GITHUB_REDIRECT_URI` reachable from the browser.
