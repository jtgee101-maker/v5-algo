# Frontend Branch Workflow (Monorepo)

This repo keeps backend + frontend together, but you can maintain a dedicated `frontend` branch where the branch root is exactly the `frontend/` app.

## Why
- cleaner Netlify + frontend CI integration
- easier frontend-only PRs
- no backend files in frontend deployments

## One-time setup
From repo root:

```bash
git fetch origin
```

## Sync `frontend` branch from current working branch

```bash
scripts/sync-frontend-branch.sh frontend origin
```

What it does:
1. Creates a subtree split from `frontend/` on your current branch.
2. Moves local `frontend` branch to that split commit.
3. Force-pushes `frontend` branch to remote (`origin/frontend`) using `--force-with-lease`.

## Daily workflow
1. Build features on the normal monorepo branch (e.g., `work`, `main`, or `feature/*`).
2. Merge as usual.
3. Re-run:
   ```bash
   scripts/sync-frontend-branch.sh frontend origin
   ```
4. Point Netlify frontend site to the `frontend` branch if you want frontend-only deploys.

## Netlify recommendation
- If using the `frontend` branch, set project root to `/` (branch already contains frontend root).
- Build command: `npm run build`
- Publish directory: `dist`
- Env: `VITE_API_URL=https://v5-algo.onrender.com/api`

## Notes
- This workflow intentionally rewrites `origin/frontend` to match the latest split commit.
- `--force-with-lease` protects against accidentally overwriting unseen remote updates.
