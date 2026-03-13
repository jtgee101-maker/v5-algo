# Self Operator Skill

Use this skill to operate the full v5-algo system end-to-end without additional prompts.

## Standard operating runbook

### 1) Discover broker endpoints
```bash
python scripts/discover_broker.py
```

### 2) Trigger broker candle discovery
```bash
curl -X POST https://v5-algo.onrender.com/api/discover-candles
```

### 3) Run market scan
```bash
curl -X POST https://v5-algo.onrender.com/api/run-scan
```

### 4) Inspect intelligence logs
```bash
curl https://v5-algo.onrender.com/api/scratchpad/sessions
```

### 5) Debug loop (if candles fail)
1. Re-run `/api/discover-candles` and inspect `tested` responses.
2. Expand patterns in `backend/app.py` and `scripts/discover_broker.py`.
3. Re-deploy and repeat runbook.

## Guardrails
- Run discovery before scans after fresh deploys.
- Keep safety protections enabled (`/api/safety/status`).
- Prefer cached pattern (`_discover_candle_pattern`) once discovered.
