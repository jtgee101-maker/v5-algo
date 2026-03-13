# Broker Discovery Skill

Use this skill when candle/history endpoints fail or return empty payloads.

## Goal
Find a working candle endpoint/parameter combo for TradeLocker and persist it for the scanner.

## Steps
1. Ensure broker env vars are set (`TRADELOCKER_EMAIL`, `TRADELOCKER_PASSWORD`, `TRADELOCKER_SERVER`, optional `TRADELOCKER_ACCOUNT_ID`, `TRADELOCKER_ACC_NUM`).
2. Run endpoint discovery:
   ```bash
   python scripts/discover_broker.py
   ```
3. Verify discovery output file exists:
   ```bash
   cat data/broker_endpoints.json
   ```
4. Trigger runtime discovery endpoint:
   ```bash
   curl -X POST https://v5-algo.onrender.com/api/discover-candles
   ```
5. If no working URL is found, inspect the `tested` payload and add new patterns in:
   - `backend/app.py` (`/api/discover-candles` and `_discover_candle_url`)
   - `scripts/discover_broker.py`

## Success criteria
- `data/broker_endpoints.json` has `working_candle_url`.
- `/api/discover-candles` returns `working` and `cached_pattern`.
- `/api/run-scan` reports non-zero candle counts for at least one symbol.
