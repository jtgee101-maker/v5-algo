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

## Netlify deployment (step-by-step)
1. Push this repo to GitHub.
2. In Netlify, create a new site from the repository.
3. In **Site configuration → Build & deploy → Build settings**, set:
   - **Base directory:** `frontend`
   - **Build command:** `npm run build`
   - **Publish directory:** `dist`
   - **Node version:** `20`
4. In **Environment variables**, set:
   - `VITE_API_URL=https://v5-algo.onrender.com/api`
5. Redeploy the site.

This repository also includes a **root** `netlify.toml` configured for a `frontend/` base directory and SPA redirects.

## If Netlify shows “Page not found / product doesn’t exist”
- Confirm build base directory is `frontend`.
- Confirm publish directory is `dist` (relative to `frontend`).
- Confirm `VITE_API_URL` is set in Netlify env vars.
- Trigger **Clear cache and deploy site** after changing settings.

## Current implementation status
- End-to-end routing and app shell for 13 sections.
- Live polling and action workflows for market data, DRM scan, signals, positions, risk, and settings.
- Error/loading/empty state components for resilient API-driven UX.
