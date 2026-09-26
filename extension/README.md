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
   - **Adaptive checklist** — only the dimensions relevant to this PR

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
npm run build
# Output: extension/dist/
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
# 86 tests: URL parsing, session management, API client, components
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_BACKEND_URL` | `http://localhost:8000` | FastAPI backend URL (no trailing slash) |

Set in `.env` file (never commit `.env`). For production deployment on Render, set `VITE_BACKEND_URL=https://your-app.onrender.com`.

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
│   ├── components/   # React UI components
│   └── types/        # TypeScript interfaces (mirrors backend schemas)
└── dist/             # Build output (load this in Chrome)
```

## Known Limitations

- **Risk tier feedback**: Fully working. `AnalysisResponse.risk_assessment_id` is used as `prediction_reference_id` when submitting risk_tier feedback (Step 18.1).
- **Reviewer / checklist feedback**: The backend supports it; the extension UI currently only exposes feedback for the risk tier. `reviewer_recommendation_id` and `checklist_item_id` are not yet in `AnalysisResponse`.
- **Checklist completion is local-only**: The `checklist_item_completions` table exists in the backend schema but no PATCH endpoint has been implemented yet.
- **No analytics dashboard in the popup**: Analytics data is available via `GET /api/analytics/me` but the popup does not render a full analytics view. The API client supports it.
- **OAuth callback tab**: Requires the backend running and `GITHUB_REDIRECT_URI` reachable from the browser.
