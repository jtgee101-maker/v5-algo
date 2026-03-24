# v5-algo Frontend

React + Vite frontend for ICT Mission Control with live API integration.

## Quick start
```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

## Build
```bash
npm run build
npm run preview
```

## Backend verification
Run endpoint smoke checks before UI testing:
```bash
VITE_API_URL=https://v5-algo.onrender.com/api npm run verify:api
```

## Netlify deployment (conflict-resolved guide)
Use **one** of the two valid configurations below.

### Option A (recommended): use repo-root `netlify.toml`
1. Push this repo to GitHub.
2. In Netlify, create a site from this repo.
3. Ensure Netlify uses the root `netlify.toml` (already configured):
   - Base directory: `frontend`
   - Build command: `npm run build`
   - Publish directory: `dist`
4. Set env var:
   - `VITE_API_URL=https://v5-algo.onrender.com/api`
5. Redeploy.

### Option B (manual UI settings without `netlify.toml`)
- Build command: `npm run build`
- Publish directory: `frontend/dist`
- Env var: `VITE_API_URL=https://v5-algo.onrender.com/api`

## If Netlify shows “Page not found / product doesn’t exist”
- Confirm either Option A or Option B is configured exactly.
- If using Option A, keep publish as `dist` (because base is `frontend`).
- If using Option B, set publish to `frontend/dist` (because no base directory is used).
- Trigger **Clear cache and deploy site** after updating settings.

## Current implementation status
- End-to-end routing and app shell for 13 sections.
- Live polling and action workflows for market data, DRM scan, signals, positions, risk, and settings.
- Error/loading/empty state components for resilient API-driven UX.
