# Frontend Build Steps (Execution Guide)

This is the practical sequence to go from clone → deployed UI.

## 1) Backend checks
```bash
curl https://v5-algo.onrender.com/api/health
curl https://v5-algo.onrender.com/api/prices
curl https://v5-algo.onrender.com/api/drm/USOIL
```

## 2) Local frontend run
```bash
cd frontend
cp .env.example .env
npm install
npm run verify:api
npm run dev
```

## 3) Local production check
```bash
npm run build
npm run preview
```

## 4) Netlify deploy
- Connect repo
- Base directory: `frontend`
- Build command: `npm run build`
- Publish directory: `dist`
- Env var: `VITE_API_URL=https://v5-algo.onrender.com/api`
- Deploy + verify dashboard routes

## 5) Smoke route checklist
- `/` Dashboard
- `/drm`
- `/charts`
- `/scanner`
- `/signals`
- `/positions`
- `/news`
- `/research/USOIL`
- `/settings`
