# Deploying to Render

## Prerequisites

- GitHub repo with this project at the root (pyproject.toml, backend/, core/, etc. at top level)
- A Render account (free tier works)

## Option A: Blueprint Deploy (recommended)

This repo includes a `render.yaml` Blueprint file. Render reads it automatically.

1. Push the repo to GitHub
2. Go to https://dashboard.render.com
3. Click **New → Blueprint**
4. Connect your GitHub repo
5. Render detects `render.yaml` and creates the service
6. Click **Apply**
7. Wait for build + deploy (2–3 minutes on free tier)
8. Verify: visit `https://your-service.onrender.com/api/health`

## Option B: Manual Web Service

1. Go to https://dashboard.render.com
2. Click **New → Web Service**
3. Connect your GitHub repo
4. Configure:
   - **Name**: `ict-trade-mission-control`
   - **Runtime**: Python
   - **Build Command**: `pip install .`
   - **Start Command**: `uvicorn backend.app:app --host 0.0.0.0 --port $PORT`
   - **Plan**: Free
5. Add environment variables (see below)
6. Click **Create Web Service**

## Environment Variables

Set these in Render's dashboard under **Environment**:

| Variable | Value | Required |
|---|---|---|
| `PYTHON_VERSION` | `3.11.10` | Yes |
| `AUTH_DISABLED` | `true` (for dev) or `false` (for production) | Yes |
| `DEFAULT_MODE` | `shadow` | Yes |
| `LIVE_LOCKED` | `true` | Yes |
| `MANUAL_APPROVAL` | `true` | Yes |
| `API_KEYS` | `{"your-key": "admin"}` | Only if AUTH_DISABLED=false |

### Optional (for Postgres instead of SQLite)

If you add a Render Postgres database, Render automatically sets `DATABASE_URL`.
The app detects this and switches from SQLite to Postgres. No code changes needed.

Without Postgres, the app uses SQLite in the `data/` directory. Note that on Render's
free tier, the filesystem is ephemeral — SQLite data resets on each deploy. This is
fine for shadow/demo validation. For persistent data, add Render Postgres.

## Verify Deployment

After deploy, check:

```
GET https://your-service.onrender.com/
→ {"name": "ICT Trade Mission Control", "version": "0.5.0", "docs": "/docs"}

GET https://your-service.onrender.com/api/health
→ {"status": "ok", "mode": "shadow", ...}

GET https://your-service.onrender.com/docs
→ Interactive Swagger UI with all 19 endpoints
```

## Seed Demo Data After Deploy

The SQLite database starts empty. To seed demo data, you can:

1. **Call the API** — POST to various endpoints to create test records
2. **Run the seed script locally** against the Render URL (if auth is configured)
3. **Use the Render shell** (paid plans) to run: `python scripts/bootstrap_demo_data.py`

For free tier, the simplest approach is to add a seed endpoint or have the app
auto-seed on first startup when the DB is empty.

## Repo Structure for Render

Render expects these at the build root:

```
repo-root/
  pyproject.toml          ← pip install reads this
  render.yaml             ← Render Blueprint reads this
  backend/
    app.py                ← uvicorn targets backend.app:app
    ...
  core/
  config/
  ...
```

If your repo has the project nested in a subfolder (like `ict-trading-system/`),
set `rootDir: ict-trading-system` in render.yaml.


### Folder naming for Root Directory

Avoid folder names with spaces (for example `ict-trading-system 7`) because they can
create URL-encoding and path issues in some deploy workflows. Prefer a folder name like
`ict-trading-system` and set Render `rootDir` to that folder name.

## Troubleshooting

### Build fails with "no pyproject.toml found"
- Verify pyproject.toml is at the rootDir level
- Check render.yaml rootDir setting

### App crashes on startup
- Check Render logs for Python import errors
- Ensure all dependencies are in pyproject.toml `[project] dependencies`
- The `[dev]` extras are not needed for production deploy

### SQLite errors
- The app auto-creates the data/ directory on startup
- If path errors persist, set `DATABASE_URL` to an absolute path

### Health check fails
- Render expects a 200 from /api/health within 5 minutes of deploy
- Check that the app starts without errors in the Render log

### Port errors
- Render sets `PORT` automatically — the app reads it from env
- Never hardcode the port in the start command
