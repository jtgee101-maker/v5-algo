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

## Netlify deployment
1. Push this repo to GitHub.
2. In Netlify, create a new site from Git.
3. If you connect the **repo root** as the Netlify project root, the committed root `netlify.toml` will auto-use:
   - Base directory: `frontend`
   - Build command: `npm run build`
   - Publish directory: `dist`
4. If you instead set Netlify base to `frontend` manually, keep:
   - Build command: `npm run build`
   - Publish directory: `dist`
5. Set environment variable:
   - `VITE_API_URL=https://v5-algo.onrender.com/api`
6. Deploy.

Both root `netlify.toml` and `frontend/public/_redirects` include SPA redirects for React Router.

## Optional: dedicated `frontend` Git branch
If you want GitHub/Netlify wired to a frontend-only branch (branch root = this folder), use:
```bash
scripts/sync-frontend-branch.sh frontend origin
```
See `FRONTEND_BRANCHING.md` in the repo root for the full workflow.

## Current implementation status
- End-to-end routing and app shell for 13 sections.
- Live polling and action workflows for market data, DRM scan, signals, positions, risk, and settings.
- Error/loading/empty state components for resilient API-driven UX.
- Added `/build-progress` page to track PRD/PDP phases with live backend connectivity checks.
