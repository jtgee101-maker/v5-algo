# Product Development Plan (PDP)
## Build Order for Claude Code + Ruflo

Version: 2.0  
Date: March 24, 2026

## Phase sequence
0. Pre-flight backend checks against Render
1. Foundation layer (api client, hooks, state store, shared UI)
2. Layout shell (sidebar, header, price banner, router)
3. Dashboard hero
4. DRM analysis page
5. Charts page
6. Scanner + Signals
7. News + Research + Positions
8. Remaining pages
9. Polish + deploy

## Verification highlights
- Prices poll every 45s
- Positions poll every 30s
- 13 routes render
- `npm run build` passes
- Render static deploy with `VITE_API_URL`
