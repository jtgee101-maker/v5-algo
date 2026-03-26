"""ICT Trade Mission Control — Analytical Intelligence Platform.

Focus: Data-driven insights and signals for manual execution.
NOT auto-executing. The team reviews signals and executes manually.

Data Sources (all free, no API keys):
  - CoinGecko: BTCUSD prices, charts, market overview
  - Yahoo Finance: NAS100, US30, EURUSD, XAUUSD (Gold), USOIL (Oil)
  - free-crypto-news: Sentiment, headlines, breaking news
  - TradeLocker: Account state only (execution via manual trading)

Symbols: BTCUSD, NAS100, US30, EURUSD, XAUUSD, USOIL
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routers import (
    account_router, agents_router, config_router, control_router,
    health_router, incidents_router, journals_router, market_router,
    metrics_router, reconciliation_router, review_router, risk_router,
    signals_router, trades_router,
)
from backend.db.session import create_tables, AsyncSessionLocal, get_db
from backend.settings import VERSION


async def _auto_seed_account():
    try:
        from backend.db.models import Account
        from backend.db.repositories.base import GenericRepository
        async with AsyncSessionLocal() as session:
            repo = GenericRepository(session, Account)
            if not await repo.list_all(limit=1):
                await repo.create(
                    id="acct_demo_1", broker_name="gatesfx",
                    account_name="GatesFX Demo", account_type="demo",
                    mode="shadow", balance=0, equity=0, margin_used=0,
                    free_margin=0, drawdown_pct=0, status="disconnected",
                    currency="USD", updated_at=datetime.now(timezone.utc).isoformat())
                await session.commit()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    from backend.settings import DATA_DIR
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    await create_tables()
    await _auto_seed_account()
    yield


app = FastAPI(
    title="ICT Trade Mission Control — Analytics",
    description="Data-driven trading intelligence for manual execution. Covers BTCUSD, NAS100, US30, EURUSD, Gold, Oil.",
    version=VERSION, lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

for router in [
    health_router, account_router, market_router, signals_router,
    trades_router, risk_router, incidents_router, config_router,
    control_router, journals_router, agents_router, metrics_router,
    reconciliation_router, review_router,
]:
    app.include_router(router, prefix="/api")


@app.get("/")
async def root():
    return {
        "name": "ICT Trade Mission Control — Analytics V13",
        "version": VERSION,
        "symbols": ["BTCUSD", "NAS100", "US30", "EURUSD", "XAUUSD", "USOIL"],
        "mode": "analytical — manual execution",
        "docs": "/docs",
    }


# ══════════════════════════════════════════════════════════════════════
# RUNTIME CONFIG — single source of truth for all frontend + automations
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/config/runtime")
async def runtime_config(db=Depends(get_db)):
    """Full operational config — single source of truth.

    Every automation, scan, risk check, and frontend control reads this.
    No hardcoded values anywhere else.
    """
    from backend.dependencies import get_config_service
    from backend.db.session import get_db as _get_db
    from core.safety import get_circuit_breaker, get_trade_cooldown

    cfg = get_config_service(db)
    config = cfg.get_config()

    # Merge live safety state into config
    cb = get_circuit_breaker()
    config["circuit_breaker_state"] = cb.status()
    config["trade_cooldown_state"] = get_trade_cooldown().status()

    return config


@app.post("/api/config/update")
async def update_runtime_config(body: dict, db=Depends(get_db)):
    """Update runtime config from frontend.

    Accepts: { updates: { key: value, ... }, changed_by: "...", reason: "..." }
    Keys: manual_approval_required, allowed_symbols, auto_scan_enabled,
          scan_frequency_seconds, max_consecutive_losses, risk.max_daily_loss_pct, etc.
    """
    from backend.dependencies import get_config_service
    cfg = get_config_service(db)
    updates = body.get("updates", {})
    changed_by = body.get("changed_by", "operator")
    reason = body.get("reason", "")
    applied = await cfg.update_config(changed_by, reason, updates)

    # Sync circuit breaker config if changed
    if "max_consecutive_losses" in applied:
        from core.safety import get_circuit_breaker
        get_circuit_breaker().max_consecutive_losses = applied["max_consecutive_losses"]
    if "breaker_cooldown_minutes" in applied:
        from core.safety import get_circuit_breaker
        get_circuit_breaker().cooldown_minutes = applied["breaker_cooldown_minutes"]

    await db.commit()
    return {"success": True, "applied": applied, "config": cfg.get_config()}


@app.post("/api/circuit-breaker/reset")
async def reset_circuit_breaker_endpoint(db=Depends(get_db)):
    """Reset circuit breaker — manual or scheduled (midnight auto-reset)."""
    from core.safety import get_circuit_breaker
    cb = get_circuit_breaker()
    cb.force_reset()
    return {"success": True, "circuit_breaker": cb.status()}


@app.post("/api/circuit-breaker/auto-reset")
async def auto_reset_circuit_breaker(db=Depends(get_db)):
    """Midnight auto-reset — call this from a scheduler at 00:01 ET.

    Resets breaker, logs the event, resolves prior-day incidents.
    """
    from core.safety import get_circuit_breaker
    from backend.services.core_services import IncidentService

    cb = get_circuit_breaker()
    was_tripped = cb.tripped
    cb.force_reset()

    if was_tripped:
        await IncidentService(db).create_incident(
            title="Circuit breaker auto-reset (midnight)",
            category="circuit_breaker", severity="info",
            source="scheduler", status="resolved",
            summary="Automatic midnight reset of circuit breaker",
        )
        await db.commit()

    return {
        "success": True,
        "was_tripped": was_tripped,
        "circuit_breaker": cb.status(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════
# MARKET DATA — live prices from free sources
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/prices")
async def all_prices():
    """Live prices for all 6 symbols from CoinGecko + Yahoo Finance.

    Returns: {BTCUSD: {price, change_24h_pct, volume, source}, NAS100: {...}, ...}
    No API key required. Updates every 60 seconds.
    """
    from core.market_data import get_market_data_service
    prices = await get_market_data_service().get_all_prices()
    return {
        "prices": prices,
        "symbols": list(prices.keys()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/prices/{symbol}")
async def symbol_detail(symbol: str):
    """Detailed data for one symbol: price, 52w high/low, moving averages, volume."""
    from core.market_data import get_market_data_service
    return await get_market_data_service().get_symbol_detail(symbol.upper())


@app.get("/api/market-overview")
async def market_overview():
    """Full market overview — all prices + crypto globals + session status.

    This is the main dashboard data endpoint. One call, all the data.
    """
    from core.market_data import get_market_data_service
    from core.intelligence import get_news_service
    from core.safety import get_circuit_breaker, get_trade_cooldown

    mds = get_market_data_service()
    now = datetime.now(timezone.utc)
    hour, weekday = now.hour, now.weekday()

    # Session status
    sessions = {
        "BTCUSD": {"active": True, "label": "24/7", "type": "crypto"},
        "NAS100": {"active": weekday < 5 and 13 <= hour <= 21, "label": "NY 9AM-5PM ET", "type": "index"},
        "US30": {"active": weekday < 5 and 13 <= hour <= 21, "label": "NY 9AM-5PM ET", "type": "index"},
        "EURUSD": {"active": weekday < 5 and 8 <= hour <= 21, "label": "London+NY", "type": "fx"},
        "XAUUSD": {"active": weekday < 5 and 8 <= hour <= 21, "label": "London+NY", "type": "commodity"},
        "USOIL": {"active": weekday < 5 and 13 <= hour <= 21, "label": "NY", "type": "commodity"},
    }

    prices = await mds.get_all_prices()
    crypto_global = await mds.get_crypto_market_overview()

    # News sentiment
    try:
        news = get_news_service()
        sentiment = await news.get_market_context()
    except Exception:
        sentiment = {"btc_sentiment": "unavailable"}

    return {
        "timestamp": now.isoformat(),
        "prices": prices,
        "sessions": sessions,
        "crypto_global": crypto_global,
        "news_sentiment": sentiment,
        "safety": {
            "circuit_breaker": get_circuit_breaker().status(),
            "trade_cooldown": get_trade_cooldown().status(),
        },
    }


@app.get("/api/chart/btc")
async def btc_chart(days: int = 7):
    """BTC price chart data — 1d, 7d, 30d, 90d.

    Returns price points + volume for charting.
    """
    from core.market_data import get_market_data_service
    return await get_market_data_service().get_btc_chart(days)


# ══════════════════════════════════════════════════════════════════════
# BROKER TEST + ACCOUNT
# ══════════════════════════════════════════════════════════════════════

@app.post("/api/broker-test")
async def broker_test():
    result = {"connected": False, "auth": None, "all_accounts": None,
              "account": None, "instruments": [], "error": None}
    required = ["TRADELOCKER_EMAIL", "TRADELOCKER_PASSWORD", "TRADELOCKER_SERVER"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        result["error"] = f"Missing: {missing}"
        return result
    try:
        from core.execution.client import TradeLockerClient
        client = TradeLockerClient()
        await client.connect()
        result["auth"] = "success"
        result["connected"] = True
        try:
            resp = await client._client.get("/auth/jwt/all-accounts",
                headers={"Authorization": f"Bearer {client._access_token}"})
            result["all_accounts"] = resp.json() if resp.status_code in (200,201) else resp.text[:500]
        except Exception as e:
            result["all_accounts"] = str(e)
        try:
            result["account"] = await client.get_account_state()
        except Exception as e:
            result["account"] = str(e)
        try:
            instruments = await client.get_instruments()
            result["instruments"] = [{"name": i.get("name",""), "id": i.get("tradableInstrumentId","")} for i in instruments[:50]]
        except Exception as e:
            result["instruments"] = str(e)
        await client.disconnect()
    except Exception as e:
        result["error"] = str(e)
        result["auth"] = "failed"
    return result


@app.post("/api/seed-demo")
async def seed_demo():
    try:
        import json
        from backend.db.models import Account, TradeSignalRecord
        from backend.db.repositories.base import GenericRepository
        now = datetime.now(timezone.utc)
        created = []
        async with AsyncSessionLocal() as session:
            repo = GenericRepository(session, Account)
            if not await repo.get_by_id("acct_demo_1"):
                await repo.create(id="acct_demo_1", broker_name="gatesfx",
                    account_name="GatesFX Demo", account_type="demo", mode="shadow",
                    balance=50000, equity=50000, free_margin=50000, status="connected",
                    currency="USD", updated_at=now.isoformat())
                created.append("account")
            sig_repo = GenericRepository(session, TradeSignalRecord)
            if not await sig_repo.list_all(limit=1):
                for sym, side, conf, st in [("NAS100","buy",0.78,"pending"),("BTCUSD","buy",0.82,"pending"),
                    ("XAUUSD","buy",0.74,"pending"),("USOIL","sell",0.71,"pending"),
                    ("US30","sell",0.82,"approved"),("EURUSD","sell",0.65,"rejected")]:
                    await sig_repo.create(symbol=sym, strategy_name="ict_analysis",
                        strategy_version="v1", timestamp=now.isoformat(), side=side,
                        confidence=conf, entry_price=0, stop_price=0, take_profit_1=0,
                        confluence_tags=json.dumps(["momentum","session_bias"]),
                        status=st, json_payload="{}")
                created.append("signals")
            await session.commit()
        return {"success": True, "created": created}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════════════
# NEWS + SENTIMENT
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/news/sentiment")
async def news_sentiment():
    from core.intelligence import get_news_service
    return await get_news_service().get_market_context()

@app.get("/api/news/latest")
async def news_latest(limit: int = 10):
    from core.intelligence import get_news_service
    articles = await get_news_service().get_latest_news(limit)
    return {"articles": articles if isinstance(articles, list) else []}

@app.get("/api/news/bitcoin")
async def news_bitcoin():
    from core.intelligence import get_news_service
    return {"articles": await get_news_service().get_bitcoin_news(10)}


# ══════════════════════════════════════════════════════════════════════
# SAFETY STATUS
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/safety/status")
async def safety_status():
    from core.safety import get_circuit_breaker, get_trade_cooldown
    return {"circuit_breaker": get_circuit_breaker().status(),
            "trade_cooldown": get_trade_cooldown().status()}

@app.post("/api/safety/reset-breaker")
async def reset_circuit_breaker():
    from core.safety import get_circuit_breaker
    get_circuit_breaker().force_reset()
    return {"success": True, "status": get_circuit_breaker().status()}


# ══════════════════════════════════════════════════════════════════════
# SCRATCHPAD — reasoning audit trail
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/scratchpad/sessions")
async def scratchpad_sessions(count: int = 20):
    from core.intelligence import get_scratchpad
    return {"sessions": get_scratchpad().get_recent_sessions(count)}

@app.get("/api/scratchpad/{session_id}")
async def scratchpad_detail(session_id: str):
    from core.intelligence import get_scratchpad
    return {"session_id": session_id, "entries": get_scratchpad().get_session_log(session_id)}


# ══════════════════════════════════════════════════════════════════════
# TRADELOCKER DATA — candles, positions, live prices via official SDK
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/tl/instruments")
async def tl_instruments():
    """List all TradeLocker instruments with IDs for our symbols."""
    try:
        from core.tradelocker_data import get_tradelocker_data
        tld = get_tradelocker_data()
        resolved = {}
        for sym in ["BTCUSD", "NAS100", "US30", "EURUSD", "XAUUSD", "USOIL"]:
            inst_id = tld.resolve_instrument_id(sym)
            resolved[sym] = {"instrument_id": inst_id, "found": inst_id is not None}
        return {"instruments": resolved, "source": "tradelocker"}
    except Exception as e:
        # Fallback: return symbols without IDs
        return {
            "instruments": {s: {"instrument_id": None, "found": False} for s in
                           ["BTCUSD", "NAS100", "US30", "EURUSD", "XAUUSD", "USOIL"]},
            "source": "fallback",
            "error": str(e)[:200],
        }


@app.get("/api/tl/candles/{symbol}")
async def tl_candles(symbol: str, resolution: str = "1h", lookback: str = "7D"):
    """Get candle data — tries TradeLocker first, falls back to CoinGecko for BTC.

    ALWAYS returns: { symbol, resolution, count, candles: [{time, open, high, low, close, volume}] }
    The 'time' field is a Unix timestamp in seconds (for lightweight-charts).
    """
    sym = symbol.upper()
    candles = []
    source = "none"

    # Try TradeLocker SDK first
    try:
        from core.tradelocker_data import get_tradelocker_data
        tld = get_tradelocker_data()
        raw = tld.get_candles(sym, resolution, lookback)
        if raw and "error" not in raw and raw.get("candles"):
            source = "tradelocker"
            for c in raw["candles"]:
                # Normalize field names: {t,o,h,l,c,v} → {time,open,high,low,close,volume}
                ts = c.get("t") or c.get("time") or ""
                # Convert timestamp to unix seconds
                time_val = _parse_timestamp(ts)
                candles.append({
                    "time": time_val,
                    "open": float(c.get("o") or c.get("open") or 0),
                    "high": float(c.get("h") or c.get("high") or 0),
                    "low": float(c.get("l") or c.get("low") or 0),
                    "close": float(c.get("c") or c.get("close") or 0),
                    "volume": float(c.get("v") or c.get("volume") or 0),
                })
    except Exception:
        pass

    # Fallback for BTC: use CoinGecko chart data
    if not candles and sym == "BTCUSD":
        try:
            from core.market_data import get_market_data_service
            days_map = {"1D": 1, "5D": 5, "7D": 7, "1M": 30, "3M": 90}
            days = days_map.get(lookback, 7)
            chart = await get_market_data_service().get_btc_chart(days)
            if chart and chart.get("prices"):
                source = "coingecko"
                for p in chart["prices"]:
                    ts = int(p["timestamp"] / 1000) if p["timestamp"] > 1e12 else int(p["timestamp"])
                    price = p["price"]
                    candles.append({
                        "time": ts,
                        "open": price,
                        "high": price * 1.002,  # approximate OHLC from point data
                        "low": price * 0.998,
                        "close": price,
                        "volume": 0,
                    })
        except Exception:
            pass

    # Fallback for all: generate synthetic candles from current price
    if not candles:
        try:
            from core.market_data import get_market_data_service
            detail = await get_market_data_service().get_symbol_detail(sym)
            if detail and detail.get("price"):
                source = "synthetic"
                price = detail["price"]
                now_ts = int(datetime.now(timezone.utc).timestamp())
                candles = [{
                    "time": now_ts,
                    "open": price,
                    "high": detail.get("high", price * 1.01) or price * 1.01,
                    "low": detail.get("low", price * 0.99) or price * 0.99,
                    "close": price,
                    "volume": detail.get("volume", 0) or 0,
                }]
        except Exception:
            pass

    return {
        "symbol": sym,
        "resolution": resolution,
        "lookback": lookback,
        "count": len(candles),
        "candles": candles,
        "source": source,
        "latest": candles[-1] if candles else None,
    }


def _parse_timestamp(ts) -> int:
    """Convert various timestamp formats to unix seconds."""
    if isinstance(ts, (int, float)):
        return int(ts) if ts < 1e12 else int(ts / 1000)
    if isinstance(ts, str):
        try:
            from datetime import datetime as dt
            # Try ISO format
            parsed = dt.fromisoformat(ts.replace("Z", "+00:00"))
            return int(parsed.timestamp())
        except Exception:
            pass
        try:
            return int(float(ts))
        except Exception:
            pass
    return int(datetime.now(timezone.utc).timestamp())


@app.get("/api/tl/positions")
async def tl_positions():
    """Get all open positions — tries TradeLocker, returns normalized shape.

    ALWAYS returns: {
      count: N,
      positions: [{instrument, side, qty, openPrice, currentPrice, pnl, pnl_pct}],
      source: "tradelocker"|"fallback",
      timestamp: "..."
    }
    """
    positions = []
    source = "none"

    # Try TradeLocker SDK
    try:
        from core.tradelocker_data import get_tradelocker_data
        tld = get_tradelocker_data()
        raw_positions = tld.get_positions()
        if raw_positions:
            source = "tradelocker"
            for p in raw_positions:
                # Normalize field names from whatever the SDK returns
                instrument = (p.get("instrument") or p.get("symbol") or
                             p.get("instrumentName") or p.get("name") or "UNKNOWN")
                side = str(p.get("side") or p.get("direction") or p.get("type") or "unknown").lower()
                qty = float(p.get("qty") or p.get("quantity") or p.get("amount") or
                           p.get("lotSize") or p.get("size") or 0)
                open_price = float(p.get("openPrice") or p.get("entry") or
                                  p.get("entryPrice") or p.get("avgPrice") or 0)
                current_price = float(p.get("currentPrice") or p.get("close") or
                                    p.get("lastPrice") or p.get("marketPrice") or 0)
                pnl = float(p.get("pnl") or p.get("profit") or p.get("unrealizedPnl") or
                           p.get("grossPnl") or 0)

                # Calculate P&L percentage
                pnl_pct = 0
                if open_price > 0 and qty > 0:
                    notional = open_price * qty
                    pnl_pct = round((pnl / notional) * 100, 2) if notional > 0 else 0

                positions.append({
                    "instrument": instrument,
                    "side": side,
                    "qty": qty,
                    "openPrice": round(open_price, 5),
                    "currentPrice": round(current_price, 5),
                    "pnl": round(pnl, 2),
                    "pnl_pct": pnl_pct,
                })
    except Exception as e:
        source = "error"

    # Try raw TradeLocker API as secondary fallback
    if not positions and source != "tradelocker":
        try:
            from core.execution.client import TradeLockerClient
            client = TradeLockerClient()
            await client.connect()
            acc_id = os.environ.get("TRADELOCKER_ACCOUNT_ID", "1967672")
            resp = await client._client.get(
                f"/trade/accounts/{acc_id}/positions",
                headers=client._auth_headers(),
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                raw = data.get("d", {}).get("positions", []) if isinstance(data.get("d"), dict) else data.get("d", [])
                if isinstance(raw, list):
                    source = "tradelocker-raw"
                    for row in raw:
                        if isinstance(row, (list, tuple)) and len(row) >= 6:
                            positions.append({
                                "instrument": str(row[0]) if len(row) > 0 else "UNKNOWN",
                                "side": "buy" if str(row[1]).lower() in ("buy", "long", "1") else "sell",
                                "qty": float(row[2]) if len(row) > 2 else 0,
                                "openPrice": float(row[3]) if len(row) > 3 else 0,
                                "currentPrice": float(row[4]) if len(row) > 4 else 0,
                                "pnl": float(row[5]) if len(row) > 5 else 0,
                                "pnl_pct": 0,
                            })
            await client.disconnect()
        except Exception:
            pass

    # Calculate totals
    total_pnl = sum(p["pnl"] for p in positions)

    return {
        "count": len(positions),
        "positions": positions,
        "total_pnl": round(total_pnl, 2),
        "source": source,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/tl/price/{symbol}")
async def tl_latest_price(symbol: str):
    """Get latest price — tries TradeLocker, falls back to CoinGecko/Yahoo."""
    sym = symbol.upper()
    price = None
    source = "none"

    # Try TradeLocker
    try:
        from core.tradelocker_data import get_tradelocker_data
        price = get_tradelocker_data().get_latest_price(sym)
        if price:
            source = "tradelocker"
    except Exception:
        pass

    # Fallback to free sources
    if not price:
        try:
            from core.market_data import get_market_data_service
            detail = await get_market_data_service().get_symbol_detail(sym)
            if detail and detail.get("price"):
                price = detail["price"]
                source = detail.get("source", "free")
        except Exception:
            pass

    return {"symbol": sym, "price": price, "source": source}


@app.post("/api/analyze")
async def analyze_markets():
    """Full analytical scan — multi-source intelligence for manual execution.

    Pulls data from both CoinGecko/Yahoo AND TradeLocker.
    Generates signal ideas with reasoning for the team to review.
    """
    import json as json_mod
    from core.intelligence import get_news_service, get_scratchpad
    from core.market_data import get_market_data_service
    from core.tradelocker_data import get_tradelocker_data

    now = datetime.now(timezone.utc)
    hour, weekday = now.hour, now.weekday()
    scratchpad = get_scratchpad()
    session_id = scratchpad.start_session()

    result = {
        "timestamp": now.isoformat(),
        "session_id": session_id,
        "prices": {},
        "tl_prices": {},
        "candle_summary": {},
        "signals": [],
        "news_sentiment": None,
        "session": "off_hours",
        "analysis": {},
        "positions": [],
    }

    # Session
    if weekday < 5:
        if 13 <= hour <= 21:
            result["session"] = "ny_session"
        elif 8 <= hour < 13:
            result["session"] = "london_pre_ny"
    if result["session"] == "off_hours":
        result["session"] = "crypto_only"

    scratchpad.log("analysis_start", session=result["session"])

    # Free data sources (always work)
    mds = get_market_data_service()
    try:
        prices = await mds.get_all_prices()
        result["prices"] = prices
        scratchpad.log("free_prices", count=len(prices), symbols=list(prices.keys()))
    except Exception as e:
        scratchpad.log("free_prices_error", error=str(e)[:100])

    # TradeLocker data (candles + positions)
    tld = get_tradelocker_data()

    # Get live positions
    try:
        positions = tld.get_positions()
        result["positions"] = positions
        scratchpad.log("positions", count=len(positions))
    except Exception as e:
        scratchpad.log("positions_error", error=str(e)[:100])

    # Get candles for each active symbol
    active_symbols = ["BTCUSD"]  # Always
    if weekday < 5 and 13 <= hour <= 21:
        active_symbols.extend(["NAS100", "US30", "EURUSD", "XAUUSD", "USOIL"])
    elif weekday < 5 and 8 <= hour < 13:
        active_symbols.extend(["EURUSD", "XAUUSD"])

    for symbol in active_symbols:
        try:
            candle_data = tld.get_candles(symbol, "1h", "5D")
            if "error" not in candle_data:
                candles = candle_data.get("candles", [])
                if candles:
                    latest = candles[-1]
                    result["candle_summary"][symbol] = {
                        "count": len(candles),
                        "latest_close": latest.get("c"),
                        "latest_high": latest.get("h"),
                        "latest_low": latest.get("l"),
                        "resolution": "1h",
                    }
                    result["tl_prices"][symbol] = latest.get("c")
                    scratchpad.log("candles_fetched", symbol=symbol, count=len(candles))
            else:
                scratchpad.log("candles_error", symbol=symbol, error=candle_data.get("error", "")[:100])
        except Exception as e:
            scratchpad.log("candles_error", symbol=symbol, error=str(e)[:100])

    # News sentiment
    try:
        news = get_news_service()
        sentiment = await news.get_market_context()
        result["news_sentiment"] = sentiment
        scratchpad.log("news", sentiment=sentiment.get("btc_sentiment"), score=sentiment.get("sentiment_score"))
    except Exception:
        result["news_sentiment"] = {"btc_sentiment": "unavailable"}

    # Generate signal ideas for each symbol
    all_prices = {**result.get("prices", {})}
    # Merge TL prices
    for sym, price in result.get("tl_prices", {}).items():
        if price and sym not in all_prices:
            all_prices[sym] = {"symbol": sym, "price": price, "source": "tradelocker"}

    for symbol, price_data in all_prices.items():
        if isinstance(price_data, (int, float)):
            price_data = {"symbol": symbol, "price": price_data, "source": "tradelocker"}

        price = price_data.get("price", 0)
        change = price_data.get("change_24h_pct", 0)
        if not price:
            continue

        analysis = {"symbol": symbol, "price": price, "change_24h_pct": change, "source": price_data.get("source")}

        # Momentum
        if change > 2:
            analysis["momentum"] = "strong_bullish"
            analysis["bias"] = "long"
        elif change > 0.5:
            analysis["momentum"] = "bullish"
            analysis["bias"] = "long"
        elif change < -2:
            analysis["momentum"] = "strong_bearish"
            analysis["bias"] = "short"
        elif change < -0.5:
            analysis["momentum"] = "bearish"
            analysis["bias"] = "short"
        else:
            analysis["momentum"] = "neutral"
            analysis["bias"] = "wait"

        # Daily range from Yahoo/CoinGecko
        if price_data.get("high_today") and price_data.get("low_today"):
            dr = price_data["high_today"] - price_data["low_today"]
            analysis["daily_range"] = round(dr, 2)
            analysis["position_in_range"] = round((price - price_data["low_today"]) / dr * 100, 1) if dr > 0 else 50

        # Candle context from TradeLocker
        cs = result.get("candle_summary", {}).get(symbol)
        if cs:
            analysis["candle_data_available"] = True
            analysis["latest_candle_close"] = cs.get("latest_close")
            analysis["candle_bars"] = cs.get("count")

        # Moving averages
        if price_data.get("50d_avg") and price_data.get("200d_avg"):
            analysis["above_50d"] = price > price_data["50d_avg"]
            analysis["above_200d"] = price > price_data["200d_avg"]
            analysis["golden_cross"] = price_data["50d_avg"] > price_data["200d_avg"]

        # News for BTC
        if symbol == "BTCUSD" and result.get("news_sentiment"):
            analysis["news_sentiment"] = result["news_sentiment"].get("btc_sentiment")
            analysis["news_score"] = result["news_sentiment"].get("sentiment_score", 0)

        # Active position check
        for pos in result.get("positions", []):
            if symbol.lower() in str(pos).lower():
                analysis["has_open_position"] = True

        result["analysis"][symbol] = analysis
        scratchpad.log("analyzed", **{k: v for k, v in analysis.items() if not isinstance(v, (list, dict))})

        # Generate signal idea
        if analysis["bias"] != "wait":
            signal = {"symbol": symbol, "bias": analysis["bias"], "momentum": analysis["momentum"],
                      "price": price, "change_24h": change, "reasoning": [], "confidence": "low", "conf_score": 0}
            cs_val = 0
            reasons = []

            if abs(change) > 2:
                reasons.append(f"Strong {analysis['momentum']} momentum ({change:+.1f}%)")
                cs_val += 2
            elif abs(change) > 0.5:
                reasons.append(f"{analysis['momentum'].replace('_', ' ').title()} momentum ({change:+.1f}%)")
                cs_val += 1

            if analysis.get("above_50d") and analysis["bias"] == "long":
                reasons.append("Above 50-day moving average")
                cs_val += 1
            elif not analysis.get("above_50d", True) and analysis["bias"] == "short":
                reasons.append("Below 50-day moving average")
                cs_val += 1

            if analysis.get("golden_cross") and analysis["bias"] == "long":
                reasons.append("Golden cross active (50d > 200d)")
                cs_val += 1

            if analysis.get("news_sentiment") == "bullish" and analysis["bias"] == "long":
                reasons.append("News sentiment bullish")
                cs_val += 1
            elif analysis.get("news_sentiment") == "bearish" and analysis["bias"] == "short":
                reasons.append("News sentiment bearish")
                cs_val += 1

            if analysis.get("position_in_range") is not None:
                pos_r = analysis["position_in_range"]
                if analysis["bias"] == "long" and pos_r < 30:
                    reasons.append(f"Near daily low ({pos_r:.0f}% of range)")
                    cs_val += 1
                elif analysis["bias"] == "short" and pos_r > 70:
                    reasons.append(f"Near daily high ({pos_r:.0f}% of range)")
                    cs_val += 1

            if analysis.get("candle_data_available"):
                reasons.append(f"TradeLocker candle data confirmed ({analysis.get('candle_bars', 0)} bars)")
                cs_val += 1

            if analysis.get("has_open_position"):
                reasons.append("⚠️ Already have open position on this symbol")

            signal["reasoning"] = reasons
            signal["conf_score"] = cs_val
            signal["confidence"] = "high" if cs_val >= 4 else "medium" if cs_val >= 2 else "low"
            result["signals"].append(signal)

    scratchpad.log("analysis_complete", symbols=len(result["analysis"]), signals=len(result["signals"]))
    result["scratchpad_entries"] = len(scratchpad.get_entries())
    return result


# ══════════════════════════════════════════════════════════════════════
# DRM — DISPLACEMENT REBALANCE MODEL (Your $23K Edge)
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/drm/{symbol}")
async def drm_analysis(symbol: str, resolution: str = "1h", lookback: str = "5D"):
    """Run your Displacement Rebalance Model on a symbol.

    Uses internal candle fetching (TradeLocker → CoinGecko → synthetic fallback).
    ALWAYS returns a valid DRM response shape, even if analysis is empty.

    Examples:
      /api/drm/USOIL?resolution=1h&lookback=5D
      /api/drm/BTCUSD?resolution=4h&lookback=7D
    """
    from core.strategy.drm import get_drm_engine
    sym = symbol.upper()

    # Use our own candle endpoint (which has all the fallbacks built in)
    candle_response = await tl_candles(sym, resolution, lookback)
    raw_candles = candle_response.get("candles", [])

    # Empty result shape — returned if no candles available
    empty_result = {
        "symbol": sym,
        "current_price": 0,
        "atr": 0,
        "volatility_regime": "unknown",
        "displacements": [],
        "fair_value_gaps": [],
        "unfilled_fvgs": 0,
        "signals": [],
        "resolution": resolution,
        "lookback": lookback,
        "candle_count": 0,
        "source": candle_response.get("source", "none"),
    }

    if len(raw_candles) < 15:  # Need minimum bars for ATR(14)
        empty_result["error"] = f"Insufficient candle data ({len(raw_candles)} bars, need 15+)"
        # Try to get at least the current price
        try:
            from core.market_data import get_market_data_service
            detail = await get_market_data_service().get_symbol_detail(sym)
            if detail and detail.get("price"):
                empty_result["current_price"] = detail["price"]
        except Exception:
            pass
        return empty_result

    # Convert normalized candles {time,open,high,low,close,volume}
    # back to DRM engine format {t,o,h,l,c,v}
    drm_candles = []
    for c in raw_candles:
        drm_candles.append({
            "t": str(c.get("time", "")),
            "o": float(c.get("open", 0)),
            "h": float(c.get("high", 0)),
            "l": float(c.get("low", 0)),
            "c": float(c.get("close", 0)),
            "v": float(c.get("volume", 0)),
        })

    try:
        drm = get_drm_engine()
        result = drm.analyze(sym, drm_candles)
        result["resolution"] = resolution
        result["lookback"] = lookback
        result["candle_count"] = len(drm_candles)
        result["source"] = candle_response.get("source", "unknown")
        return result
    except Exception as e:
        empty_result["error"] = f"DRM analysis failed: {str(e)[:200]}"
        return empty_result


@app.get("/api/probability")
async def barrier_probability(
    current: float, target: float, atr: float, days: int = 3
):
    """Calculate barrier-touch probability (BlackRock-style math).

    How likely is price to TOUCH a level within N days?

    Examples:
      /api/probability?current=90.4&target=105&atr=8.99&days=5
      /api/probability?current=90.4&target=85&atr=8.99&days=3
    """
    import math

    daily_sigma = atr / 1.596
    distance = abs(target - current)
    multi_day_sigma = daily_sigma * math.sqrt(days)

    if multi_day_sigma <= 0:
        return {"error": "invalid atr"}

    z = distance / (multi_day_sigma * math.sqrt(2))
    touch_prob = math.erfc(z)

    direction = "up" if target > current else "down"
    risk = abs(current - target)

    return {
        "current": current,
        "target": target,
        "direction": direction,
        "distance": round(distance, 4),
        "atr": atr,
        "daily_sigma": round(daily_sigma, 4),
        "days": days,
        "touch_probability": round(touch_prob * 100, 2),
        "touch_probability_raw": round(touch_prob, 4),
        "interpretation": f"{round(touch_prob*100,1)}% chance of touching {target} within {days} days",
    }


@app.post("/api/drm/scan")
async def drm_scan_all():
    """Run DRM analysis on ALL active symbols using internal candle fetching.

    Uses the same fallback chain as /tl/candles (TradeLocker → CoinGecko → synthetic).
    ALWAYS returns results for all 6 symbols, even if some have no candle data.
    """
    from core.strategy.drm import get_drm_engine
    from core.intelligence import get_scratchpad

    scratchpad = get_scratchpad()
    session_id = scratchpad.start_session()
    scratchpad.log("drm_scan_start")

    drm = get_drm_engine()
    now = datetime.now(timezone.utc)

    results = {
        "timestamp": now.isoformat(),
        "session_id": session_id,
        "symbols": {},
        "all_signals": [],
        "summary": {"total_fvgs": 0, "unfilled_fvgs": 0, "signals": 0},
    }

    for symbol in ["BTCUSD", "NAS100", "US30", "EURUSD", "XAUUSD", "USOIL"]:
        try:
            # Use our internal endpoint which has full fallback chain
            drm_result = await drm_analysis(symbol, "1h", "5D")

            if drm_result.get("error"):
                results["symbols"][symbol] = {
                    "error": drm_result["error"],
                    "current_price": drm_result.get("current_price", 0),
                }
                scratchpad.log("drm_skip", symbol=symbol, reason=drm_result.get("error", "")[:100])
                continue

            results["symbols"][symbol] = {
                "current_price": drm_result.get("current_price"),
                "atr": drm_result.get("atr"),
                "volatility_regime": drm_result.get("volatility_regime"),
                "displacements": len(drm_result.get("displacements", [])),
                "total_fvgs": len(drm_result.get("fair_value_gaps", [])),
                "unfilled_fvgs": drm_result.get("unfilled_fvgs", 0),
                "signals": drm_result.get("signals", []),
                "source": drm_result.get("source", "unknown"),
            }

            results["summary"]["total_fvgs"] += len(drm_result.get("fair_value_gaps", []))
            results["summary"]["unfilled_fvgs"] += drm_result.get("unfilled_fvgs", 0)

            for sig in drm_result.get("signals", []):
                sig["symbol"] = symbol
                results["all_signals"].append(sig)
                results["summary"]["signals"] += 1

            scratchpad.log("drm_analyzed", symbol=symbol,
                price=drm_result.get("current_price"),
                fvgs=len(drm_result.get("fair_value_gaps", [])),
                signals=len(drm_result.get("signals", [])),
                source=drm_result.get("source"))

        except Exception as e:
            results["symbols"][symbol] = {"error": str(e)[:200]}
            scratchpad.log("drm_error", symbol=symbol, error=str(e)[:100])

    # Sort signals by confidence
    results["all_signals"].sort(key=lambda s: s.get("conf_score", 0), reverse=True)

    scratchpad.log("drm_scan_complete",
        symbols_scanned=len(results["symbols"]),
        total_signals=results["summary"]["signals"])

    return results
