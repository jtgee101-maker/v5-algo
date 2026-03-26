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

import json
import math
import os
import time
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


# ══════════════════════════════════════════════════════════════════════
# SCANNER TRUTH — data source classification + lifecycle + cooldown
# ══════════════════════════════════════════════════════════════════════

@app.post("/api/scanner/analyze")
async def scanner_analyze_with_truth():
    """Scanner with full data-source truth model.

    Frontend should use this instead of raw /analyze.
    Includes: debounce, per-symbol source classification, scan lifecycle.
    """
    from core.scanner_truth import get_data_classifier, get_scan_manager

    scan_mgr = get_scan_manager()
    classifier = get_data_classifier()
    scan_id = f"scan_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

    # Cooldown check
    can_run, reuse_meta = scan_mgr.can_scan()
    if not can_run:
        return {
            "scan_id": reuse_meta.get("reused_scan_id", scan_id),
            "reused": True,
            **reuse_meta,
            "scan_metadata": scan_mgr.get_last_scan_info(),
        }

    # Start scan
    scan_mgr.start_scan(scan_id)

    try:
        # Classify data sources for each symbol
        symbols = ["BTCUSD", "NAS100", "US30", "EURUSD", "XAUUSD", "USOIL"]
        symbol_truth = []
        for sym in symbols:
            try:
                candle_resp = await tl_candles(sym, "1h", "5D")
                st = classifier.classify_symbol(
                    symbol=sym,
                    source=candle_resp.get("source", "none"),
                    candle_count=candle_resp.get("count", 0),
                    has_error="error" in candle_resp,
                )
                symbol_truth.append(st)
            except Exception:
                symbol_truth.append(classifier.classify_symbol(sym, "none", 0, has_error=True))

        # Aggregate scan truth
        aggregate = classifier.classify_scan(symbol_truth)

        # If all synthetic/unavailable, return withheld
        if aggregate["all_synthetic"]:
            scan_mgr.complete_scan(scan_id, True, aggregate, 0, 0)
            return {
                "scan_id": scan_id, "reused": False,
                "scan_status": aggregate["scan_status"],
                "all_synthetic": True, "any_live": False,
                "withheld_reason": "No live or fallback data available for any symbol",
                "actionable_results": [], "signals": [],
                "data_truth": aggregate,
                "symbol_truth": symbol_truth,
                "scan_metadata": scan_mgr.get_last_scan_info(),
            }

        # Run actual analysis
        analysis_result = await analyze_markets()

        # Tag each symbol with source truth
        for st in symbol_truth:
            sym = st["symbol"]
            if sym in analysis_result.get("analysis", {}):
                analysis_result["analysis"][sym]["data_truth"] = st
            for sig in analysis_result.get("signals", []):
                if sig.get("symbol") == sym:
                    sig["source_status"] = st["source_status"]
                    sig["market_data_valid"] = st["market_data_valid"]

        # Filter: only actionable signals from valid data
        actionable = [
            s for s in analysis_result.get("signals", [])
            if s.get("market_data_valid", False)
        ]
        withheld = [
            s for s in analysis_result.get("signals", [])
            if not s.get("market_data_valid", False)
        ]

        scan_mgr.complete_scan(scan_id, True, aggregate, len(actionable), len(withheld))

        return {
            "scan_id": scan_id, "reused": False,
            "scan_status": aggregate["scan_status"],
            "all_synthetic": aggregate["all_synthetic"],
            "any_live": aggregate["any_live"],
            "withheld_reason": None,
            "actionable_results": actionable,
            "actionable_count": len(actionable),
            "analysis": analysis_result.get("analysis", {}),
            "signals": actionable,
            "withheld_signals": withheld,
            "withheld_count": len(withheld),
            "data_truth": aggregate,
            "symbol_truth": symbol_truth,
            "scan_metadata": scan_mgr.get_last_scan_info(),
            "prices": analysis_result.get("prices", {}),
            "session": analysis_result.get("session"),
            "news_sentiment": analysis_result.get("news_sentiment"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        scan_mgr.complete_scan(scan_id, False, {"scan_status": "error"}, 0, 0, str(e)[:200])
        return {
            "scan_id": scan_id, "reused": False,
            "scan_status": "error", "all_synthetic": True, "any_live": False,
            "error": str(e)[:200],
            "actionable_results": [], "signals": [],
            "data_truth": {}, "scan_metadata": scan_mgr.get_last_scan_info(),
        }


@app.get("/api/scanner/last-scan")
async def last_scan_metadata():
    """Get last scan metadata for frontend auto-scan decisions."""
    try:
        from core.scanner_truth import get_scan_manager
        return get_scan_manager().get_last_scan_info()
    except Exception:
        return {"last_attempted": None, "last_successful": None, "last_live_data": None, "total_runs": 0}


@app.get("/api/scanner/cooldown")
async def scanner_cooldown_status():
    """Check if scanner is in cooldown or can run."""
    try:
        from core.scanner_truth import get_scan_manager
        can_run, meta = get_scan_manager().can_scan()
        return {"can_scan": can_run, **(meta or {})}
    except Exception:
        return {"can_scan": True, "reused_recent_scan": False}


# ══════════════════════════════════════════════════════════════════════
# LEARNING ENGINE — learns from your trades, detects mistakes, builds rules
# ══════════════════════════════════════════════════════════════════════

@app.post("/api/learn/record-trade")
async def record_trade(body: dict):
    """Record a completed trade for learning.

    Body: { symbol, side, entry_price, exit_price, pnl, qty,
            entry_time, exit_time, strategy, risk_pct, notes }
    """
    from core.learning import get_trade_memory
    mem = get_trade_memory()
    mem.record_trade(body)
    return {
        "success": True,
        "total_trades": len(mem.get_all_trades()),
        "patterns": mem.get_patterns(),
    }


@app.get("/api/learn/patterns")
async def learning_patterns():
    """Get learned trading patterns — win rate, best symbols, timing, hold duration."""
    from core.learning import get_trade_memory
    mem = get_trade_memory()
    return {
        "patterns": mem.get_patterns(),
        "total_trades": len(mem.get_all_trades()),
    }


@app.get("/api/learn/mistakes")
async def detect_mistakes():
    """Detect trading mistakes — revenge trades, oversizing, tilt."""
    from core.learning import get_trade_memory
    return {
        "mistakes": get_trade_memory().detect_mistakes(),
    }


@app.get("/api/learn/rules")
async def generate_rules():
    """Generate adaptive trading rules from your trade history."""
    from core.learning import get_trade_memory
    return {
        "rules": get_trade_memory().generate_rules(),
    }


@app.get("/api/learn/trades")
async def get_all_learned_trades():
    """Get all recorded trades with P&L."""
    from core.learning import get_trade_memory
    trades = get_trade_memory().get_all_trades()
    return {
        "count": len(trades),
        "trades": trades[-50:],  # Last 50
        "total_pnl": sum(t.get("pnl", 0) for t in trades),
    }


@app.post("/api/learn/import-positions")
async def import_positions_to_memory():
    """Import current TradeLocker positions into trade memory for learning."""
    from core.learning import get_trade_memory

    # Fetch current positions from our own endpoint
    pos_response = await tl_positions()
    positions = pos_response.get("positions", [])

    mem = get_trade_memory()
    imported = 0
    for p in positions:
        mem.record_trade({
            "symbol": p.get("instrument", "UNKNOWN"),
            "side": p.get("side", "unknown"),
            "entry_price": p.get("openPrice", 0),
            "exit_price": p.get("currentPrice", 0),
            "pnl": p.get("pnl", 0),
            "qty": p.get("qty", 0),
            "entry_time": datetime.now(timezone.utc).isoformat(),
            "strategy": "drm_manual",
            "status": "open",
        })
        imported += 1

    return {
        "success": True,
        "imported": imported,
        "total_trades": len(mem.get_all_trades()),
        "patterns": mem.get_patterns(),
    }


# ══════════════════════════════════════════════════════════════════════
# PAIRS TRADING — cointegration analysis from KidQuant notebook
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/pairs/test")
async def test_cointegrated_pairs(cutoff: float = 0.05):
    """Test all 6 symbol pairs for cointegration.

    Uses the Engle-Granger cointegration test from the pairs trading notebook.
    Returns which pairs are statistically cointegrated (mean-reverting together).

    A cointegrated pair means: when one goes up and the other doesn't follow,
    you can bet they'll converge again. That's a tradeable signal.
    """
    from core.learning import get_pairs_analyzer
    from core.market_data import get_market_data_service

    # Get price data for all symbols
    mds = get_market_data_service()
    price_data = {}

    # For BTC, use CoinGecko chart data
    try:
        btc_chart = await mds.get_btc_chart(days=90)
        if btc_chart and btc_chart.get("prices"):
            price_data["BTCUSD"] = [p["price"] for p in btc_chart["prices"]]
    except Exception:
        pass

    # For others, we'd need historical data — use what we can get
    # Note: Yahoo Finance free API gives limited history via our market_data module
    # For now, return what's available from candle data
    for sym in ["NAS100", "US30", "EURUSD", "XAUUSD", "USOIL"]:
        try:
            candle_response = await tl_candles(sym, "1D", "3M")
            candles = candle_response.get("candles", [])
            if candles:
                price_data[sym] = [c["close"] for c in candles if c.get("close")]
        except Exception:
            pass

    if len(price_data) < 2:
        return {"error": "Need price data for at least 2 symbols", "available": list(price_data.keys())}

    analyzer = get_pairs_analyzer()
    result = analyzer.find_cointegrated_pairs(price_data, cutoff)
    result["symbols_tested"] = list(price_data.keys())
    result["data_points"] = {k: len(v) for k, v in price_data.items()}
    return result


@app.get("/api/pairs/zscore/{sym1}/{sym2}")
async def pair_zscore(sym1: str, sym2: str, window_long: int = 60, window_short: int = 5):
    """Calculate spread z-score between two symbols.

    When z-score < -1: BUY the ratio (sym1 is cheap relative to sym2)
    When z-score > +1: SELL the ratio (sym1 is expensive relative to sym2)

    This is the core pairs trading signal from the notebook.
    """
    from core.learning import get_pairs_analyzer

    # Get candle data for both symbols
    c1 = await tl_candles(sym1.upper(), "1D", "3M")
    c2 = await tl_candles(sym2.upper(), "1D", "3M")

    prices1 = [c["close"] for c in c1.get("candles", []) if c.get("close")]
    prices2 = [c["close"] for c in c2.get("candles", []) if c.get("close")]

    if not prices1 or not prices2:
        return {"error": f"No price data for {sym1} and/or {sym2}"}

    analyzer = get_pairs_analyzer()
    result = analyzer.calculate_spread_zscore(prices1, prices2, window_long, window_short)
    result["pair"] = f"{sym1.upper()}/{sym2.upper()}"
    return result


@app.get("/api/pairs/stationarity/{symbol}")
async def stationarity_check(symbol: str):
    """Test if a symbol's price series is stationary (mean-reverting).

    Stationary = mean-reverting = good for DRM/pairs strategies
    Non-stationary = trending = DRM edge may not apply
    """
    from core.learning import get_pairs_analyzer

    candle_response = await tl_candles(symbol.upper(), "1D", "3M")
    candles = candle_response.get("candles", [])
    prices = [c["close"] for c in candles if c.get("close")]

    if len(prices) < 20:
        return {"error": f"Need 20+ data points, got {len(prices)}"}

    analyzer = get_pairs_analyzer()
    result = analyzer.stationarity_test(prices)
    result["symbol"] = symbol.upper()
    result["data_points"] = len(prices)
    return result


@app.get("/api/learn/recommendations")
async def get_recommendations():
    """Get combined recommendations: DRM signals + pairs analysis + learned rules + mistake warnings.

    This is the master intelligence endpoint — combines everything into actionable advice.
    """
    from core.learning import get_trade_memory
    from core.safety import get_circuit_breaker

    mem = get_trade_memory()
    patterns = mem.get_patterns()
    mistakes = mem.detect_mistakes()
    rules = mem.generate_rules()
    cb = get_circuit_breaker()

    recommendations = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "account_performance": {
            "total_pnl": patterns.get("total_pnl", 0),
            "win_rate": patterns.get("win_rate", 0),
            "expectancy": patterns.get("expectancy", 0),
            "profit_factor": patterns.get("profit_factor", 0),
        },
        "active_warnings": [],
        "rules": rules,
        "best_symbol": patterns.get("best_symbol"),
        "worst_symbol": patterns.get("worst_symbol"),
        "hold_time_insight": patterns.get("hold_time", {}).get("insight", ""),
    }

    # Warnings
    if cb.tripped:
        recommendations["active_warnings"].append({
            "type": "circuit_breaker",
            "severity": "critical",
            "message": "Circuit breaker tripped — no trading allowed",
        })

    for m in mistakes:
        if m.get("severity") == "high":
            recommendations["active_warnings"].append({
                "type": m["type"],
                "severity": "high",
                "message": m["message"],
            })

    if patterns.get("expectancy", 0) < 0:
        recommendations["active_warnings"].append({
            "type": "negative_expectancy",
            "severity": "critical",
            "message": "Negative expectancy — STOP trading and review strategy",
        })

    return recommendations


# ══════════════════════════════════════════════════════════════════════
# RISK POLICY ENGINE — Phase 2: Mandatory evaluation for every trade
# ══════════════════════════════════════════════════════════════════════

@app.post("/api/risk/evaluate")
async def evaluate_trade_risk(body: dict, db=Depends(get_db)):
    """Evaluate a proposed trade against all risk policies.

    NEVER crashes — returns safe blocked state on any internal error.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        from core.risk_policy import get_risk_engine, get_hardened_breaker
        from backend.dependencies import get_config_service
        from core.safety import get_trade_cooldown

        cfg = get_config_service(db)
        config = cfg.get_config()

        # Try hardened breaker, fall back to basic
        try:
            cb = get_hardened_breaker()
            cb_status = cb.status()
        except Exception:
            from core.safety import get_circuit_breaker
            cb_status = get_circuit_breaker().status()

        # Get account state with freshness tracking
        account_state = await _get_account_state_with_freshness()

        decision = get_risk_engine().evaluate(
            symbol=body.get("symbol", ""),
            direction=body.get("direction", ""),
            strategy=body.get("strategy", "manual"),
            proposed_entry=body.get("proposed_entry", 0),
            stop_loss_distance=body.get("stop_loss_distance", 0),
            proposed_risk_pct=body.get("proposed_risk_pct", 0),
            runtime_config=config,
            circuit_breaker_status=cb_status,
            cooldown_status=get_trade_cooldown().status(),
            account_equity=account_state["equity"],
            daily_pnl=account_state["daily_pnl"],
            open_positions=account_state["positions"],
            atr=body.get("atr", 0),
            session_active=body.get("session_active", True),
            source=body.get("source", "api"),
        )

        if account_state["stale"]:
            decision.warnings.append(
                f"Account state is STALE ({account_state['age_seconds']}s old)"
            )

        result = decision.to_dict()

        # Try durable audit — don't crash if table missing
        try:
            from backend.services.audit_service import DurableAuditService
            await DurableAuditService(db).log_risk_decision(result)
            await db.commit()
        except Exception:
            pass

        result["account_state_freshness"] = {
            "stale": account_state["stale"],
            "age_seconds": account_state["age_seconds"],
            "source": account_state["source"],
        }
        return result

    except Exception as e:
        # Safe failure: return blocked state
        return {
            "approved": False,
            "adjusted_risk_pct": None,
            "blockers": [f"Risk evaluation system error: {str(e)[:100]}"],
            "warnings": ["Risk engine degraded — blocking as safety precaution"],
            "safety_state": {"degraded": True, "mode": "unknown"},
            "config_hash": "",
            "portfolio_snapshot": {},
            "request_snapshot": body,
            "timestamp": now_iso,
            "account_state_freshness": {"stale": True, "age_seconds": -1, "source": "error"},
        }


async def _get_account_state_with_freshness() -> dict:
    """Get account state with freshness tracking. Phase 3: broker truth."""
    state = {
        "equity": 0, "balance": 0, "daily_pnl": 0, "weekly_pnl": 0,
        "drawdown_pct": 0, "positions": [], "source": "none",
        "fetched_at": None, "stale": True, "age_seconds": 9999,
    }

    fetch_start = time.time()

    # Get positions
    try:
        pos_response = await tl_positions()
        state["positions"] = pos_response.get("positions", [])
        state["daily_pnl"] = pos_response.get("total_pnl", 0)
        state["source"] = pos_response.get("source", "unknown")
    except Exception:
        pass

    # Get account state from broker
    try:
        from core.execution.client import TradeLockerClient
        client = TradeLockerClient()
        await client.connect()
        acct = await client.get_account_state()
        await client.disconnect()
        if acct:
            state["equity"] = float(acct.get("equity", 0) or 0)
            state["balance"] = float(acct.get("balance", 0) or 0)
            state["drawdown_pct"] = float(acct.get("drawdown_pct", 0) or 0)
            if state["source"] == "none":
                state["source"] = "tradelocker"
    except Exception:
        pass

    fetch_time = time.time() - fetch_start
    state["fetched_at"] = datetime.now(timezone.utc).isoformat()
    state["age_seconds"] = round(fetch_time, 2)
    # Consider stale if fetch took >10s or no data at all
    state["stale"] = fetch_time > 10 or state["source"] == "none"

    return state


@app.get("/api/risk/audit-log")
async def risk_audit_log(limit: int = 50, category: str = None, db=Depends(get_db)):
    """Get audit log. NEVER returns 404 — returns empty array if no data."""
    try:
        from backend.services.audit_service import DurableAuditService
        audit_svc = DurableAuditService(db)
        entries = await audit_svc.get_recent(category=category, limit=limit)
        return {"entries": entries, "count": len(entries), "durable": True}
    except Exception:
        # Table might not exist yet — fall back to in-memory log
        try:
            from core.risk_policy import get_risk_engine
            entries = get_risk_engine().get_audit_log(limit)
            return {"entries": entries, "count": len(entries), "durable": False}
        except Exception:
            return {"entries": [], "count": 0, "durable": False}


# ══════════════════════════════════════════════════════════════════════
# EXECUTION GATE — lifecycle-aware, durable, crash-proof
# ══════════════════════════════════════════════════════════════════════

@app.post("/api/execution/gate")
async def execution_gate(body: dict, db=Depends(get_db)):
    """Submit a trade through the mandatory execution gate.

    Creates a durable ExecutionLifecycleRecord that tracks from policy through broker.
    NEVER crashes — returns safe blocked state on any internal error.

    Lifecycle: request → policy → lifecycle record → broker submission → result
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    exec_id = f"exec_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{body.get('symbol', 'UNK')}"
    symbol = body.get("symbol", "").upper()
    direction = body.get("direction", "")

    try:
        from core.risk_policy import get_execution_gate, get_hardened_breaker
        from backend.dependencies import get_config_service
        from backend.services.execution_lifecycle import ExecutionLifecycleService, BrokerExecutionService
        from core.safety import get_trade_cooldown

        lifecycle_svc = ExecutionLifecycleService(db)
        cfg = get_config_service(db)
        config = cfg.get_config()
        mode = config.get("mode", "shadow")

        try:
            cb = get_hardened_breaker()
        except Exception:
            cb = None

        account_state = await _get_account_state_with_freshness()

        # Block if account state is stale and equity is zero
        if account_state["stale"] and account_state["equity"] == 0:
            try:
                await lifecycle_svc.create_execution(
                    execution_id=exec_id, symbol=symbol, direction=direction,
                    source=body.get("source", "api"), strategy=body.get("strategy", "manual"),
                    policy_result="blocked", policy_message="Account state unavailable",
                    policy_blockers=["Account state unavailable"], config_hash="",
                    account_state_stale=True, mode=mode, lifecycle_status="policy_blocked",
                )
                await db.commit()
            except Exception:
                pass
            return _gate_response(exec_id, False, "policy_blocked",
                ["Account state unavailable"], [], None, None,
                "Execution blocked: account state unavailable",
                {"stale": True, "age_seconds": -1})

        # Run risk policy
        gate_result = await get_execution_gate().evaluate_and_gate(
            symbol=symbol, direction=direction,
            strategy=body.get("strategy", "manual"),
            proposed_entry=body.get("proposed_entry", 0),
            stop_loss_distance=body.get("stop_loss_distance", 0),
            proposed_risk_pct=body.get("proposed_risk_pct", 0),
            runtime_config=config, circuit_breaker=cb,
            cooldown_status=get_trade_cooldown().status(),
            account_equity=account_state["equity"],
            account_balance=account_state["balance"],
            daily_pnl=account_state["daily_pnl"],
            account_drawdown_pct=account_state["drawdown_pct"],
            open_positions=account_state["positions"],
            source=body.get("source", "api"),
        )

        decision = gate_result.get("decision", {})
        approved = gate_result.get("approved", False)
        blockers = decision.get("blockers", [])
        warnings = decision.get("warnings", [])
        config_hash = decision.get("config_hash", "")

        # Determine lifecycle status from policy
        if not approved:
            lifecycle_status = "policy_blocked"
        elif mode == "shadow":
            lifecycle_status = "policy_simulated"
        else:
            lifecycle_status = "policy_ready_for_broker"

        # Create durable lifecycle record
        try:
            await lifecycle_svc.create_execution(
                execution_id=exec_id, symbol=symbol, direction=direction,
                source=body.get("source", "api"), strategy=body.get("strategy", "manual"),
                signal_id=body.get("signal_id"),
                policy_result="approved" if approved else "blocked",
                policy_message=_build_human_message_v2(lifecycle_status, blockers, warnings),
                policy_blockers=blockers, policy_warnings=warnings,
                config_hash=config_hash, account_state_stale=account_state["stale"],
                mode=mode, lifecycle_status=lifecycle_status,
                quantity_requested=body.get("quantity", 0),
            )
            await db.commit()
        except Exception:
            pass

        # If ready for broker, attempt submission
        broker_result = None
        if lifecycle_status == "policy_ready_for_broker":
            try:
                broker_svc = BrokerExecutionService(lifecycle_svc)
                broker_result = await broker_svc.submit_to_broker(
                    exec_id, symbol, direction,
                    quantity=body.get("quantity", 0.5), mode=mode,
                )
                # Update lifecycle status based on broker result
                if broker_result.get("broker_status") == "submitted":
                    lifecycle_status = "broker_submitted"
                elif broker_result.get("broker_status") == "rejected":
                    lifecycle_status = "broker_rejected"
                await db.commit()
            except Exception as e:
                broker_result = {"success": False, "broker_status": "unknown",
                                "message": str(e)[:100]}

        return _gate_response(
            exec_id, approved, lifecycle_status,
            blockers, warnings, config_hash,
            broker_result, _build_human_message_v2(lifecycle_status, blockers, warnings),
            {"stale": account_state["stale"], "age_seconds": account_state["age_seconds"]},
        )

    except Exception as e:
        return _gate_response(
            exec_id, False, "policy_blocked",
            [f"Execution gate error: {str(e)[:100]}"],
            ["Execution gate degraded"], None, None,
            f"System error: {str(e)[:80]}",
            {"stale": True, "age_seconds": -1},
        )


def _gate_response(
    exec_id, approved, lifecycle_status, blockers, warnings,
    config_hash, broker_result, message, freshness,
) -> dict:
    """Build consistent gate response shape."""
    return {
        "execution_id": exec_id,
        "approved": approved,
        "result": lifecycle_status,
        "lifecycle_status": lifecycle_status,
        "decision": {
            "approved": approved,
            "blockers": blockers,
            "warnings": warnings,
            "safety_state": {},
            "config_hash": config_hash or "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "broker_status": broker_result.get("broker_status") if broker_result else None,
        "broker_order_id": broker_result.get("broker_order_id") if broker_result else None,
        "broker_message": broker_result.get("message") if broker_result else None,
        "message": message,
        "account_state_freshness": freshness,
        "durable": True,
    }


def _build_human_message_v2(status, blockers, warnings) -> str:
    if status == "policy_blocked":
        return f"Blocked: {blockers[0]}" if blockers else "Blocked by risk policy"
    elif status == "policy_simulated":
        return "Simulated (shadow mode) — not sent to broker"
    elif status == "policy_ready_for_broker":
        return f"Approved with warnings: {warnings[0]}" if warnings else "Approved — ready for broker"
    elif status == "broker_submitted":
        return "Order submitted to broker"
    elif status == "broker_rejected":
        return "Broker rejected the order"
    return f"Status: {status}"


# ══════════════════════════════════════════════════════════════════════
# EXECUTION STATUS + HISTORY + RECONCILIATION
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/execution/status/{execution_id}")
async def execution_status(execution_id: str, db=Depends(get_db)):
    """Get full lifecycle status for one execution. Cheap + stable for polling."""
    try:
        from backend.services.execution_lifecycle import ExecutionLifecycleService
        svc = ExecutionLifecycleService(db)
        result = await svc.get_status(execution_id)
        if result:
            return result
        return {"error": "Execution not found", "execution_id": execution_id}
    except Exception:
        return {"error": "Lifecycle service unavailable", "execution_id": execution_id}


@app.get("/api/execution/history")
async def execution_history(
    limit: int = 50, symbol: str = None, status: str = None,
    db=Depends(get_db),
):
    """Get execution history with filters. Returns full lifecycle records."""
    try:
        from backend.services.execution_lifecycle import ExecutionLifecycleService
        svc = ExecutionLifecycleService(db)
        records = await svc.get_history(limit=limit, symbol=symbol, status=status)
        return {"executions": records, "count": len(records), "durable": True}
    except Exception:
        return {"executions": [], "count": 0, "durable": False}


@app.post("/api/execution/reconcile/{execution_id}")
async def reconcile_execution(execution_id: str, db=Depends(get_db)):
    """Reconcile one execution against broker truth."""
    try:
        from backend.services.execution_lifecycle import ExecutionLifecycleService

        # Get broker positions for reconciliation
        positions = []
        try:
            pos_response = await tl_positions()
            positions = pos_response.get("positions", [])
        except Exception:
            pass

        svc = ExecutionLifecycleService(db)
        result = await svc.reconcile(execution_id, broker_positions=positions)
        await db.commit()
        return result
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


@app.get("/api/execution/log")
async def execution_log(limit: int = 50, db=Depends(get_db)):
    """Get execution audit log. NEVER returns 404."""
    try:
        from backend.services.audit_service import DurableAuditService
        entries = await DurableAuditService(db).get_recent(category="execution_lifecycle", limit=limit)
        if not entries:
            entries = await DurableAuditService(db).get_recent(category="execution", limit=limit)
        return {"entries": entries, "count": len(entries), "durable": True}
    except Exception:
        try:
            from core.risk_policy import get_execution_gate
            entries = get_execution_gate().get_execution_log(limit)
            return {"entries": entries, "count": len(entries), "durable": False}
        except Exception:
            return {"entries": [], "count": 0, "durable": False}


# ══════════════════════════════════════════════════════════════════════
# SIGNAL INTELLIGENCE — validation, scoring, dedup, classification
# ══════════════════════════════════════════════════════════════════════

@app.post("/api/signals/promote-from-scan")
async def promote_scan_to_signal(body: dict, db=Depends(get_db)):
    """Promote a scanner result through signal intelligence + durable memory.

    Pipeline: validate → score → DURABLE DEDUP → classify → persist
    Dedup survives restarts. Duplicate spam is suppressed at DB level.
    """
    try:
        from core.signal_intelligence import get_signal_pipeline
        from backend.dependencies import get_config_service
        from backend.services.signal_service import SignalService
        from backend.services.signal_memory import DurableSignalMemory

        cfg = get_config_service(db)
        config = cfg.get_config()

        if config.get("kill_switch", {}).get("active"):
            return {"success": False, "error": "Kill switch active", "classification": "rejected"}

        pipeline = get_signal_pipeline()
        memory = DurableSignalMemory(db)

        symbol = body.get("symbol", "").upper()
        direction = body.get("direction", "")
        strategy = body.get("strategy", "scanner_promotion")
        source = body.get("source", "scanner")
        entry = float(body.get("entry", 0))
        stop_loss = float(body.get("stop_loss", 0))
        take_profit = float(body.get("take_profit", 0))

        # Step 1: Run intelligence pipeline (validation + scoring)
        result = pipeline.process(
            symbol=symbol, direction=direction,
            entry=entry, stop_loss=stop_loss, take_profit=take_profit,
            source=source, strategy=strategy,
            confidence=float(body.get("confidence", 0)),
            current_price=float(body.get("current_price", 0)),
            atr=float(body.get("atr", 0)),
            volatility_regime=body.get("volatility_regime", "unknown"),
            momentum=body.get("momentum", "neutral"),
            displacement_detected=body.get("displacement_detected", False),
            displacement_atr_multiple=float(body.get("displacement_atr_multiple", 0)),
            fvg_present=body.get("fvg_present", False),
            fvg_fill_pct=float(body.get("fvg_fill_pct", 0)),
            unfilled_fvg_count=int(body.get("unfilled_fvg_count", 0)),
            allowed_symbols=config.get("allowed_symbols", []),
            sentiment_aligned=body.get("sentiment_aligned", False),
            sentiment_available=body.get("sentiment_available", False),
        )

        if not result.get("valid"):
            return {
                "success": False, "signal_id": None,
                "classification": "invalid",
                "score_total": 0, "valid": False,
                "action": "reject",
                "rejection_reason": result.get("rejection_reason"),
                "why_tradable": [], "why_not_tradable": result.get("why_not_tradable", []),
                "memory": None, "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # Step 2: DURABLE dedup check (survives restarts)
        memory_result = await memory.check_and_record(
            symbol=symbol, direction=direction, strategy=strategy, source=source,
            entry=entry, stop_loss=stop_loss, take_profit=take_profit,
            classification=result["classification"],
            score_total=result["score_total"],
            score_components=result.get("score_components"),
            scan_id=body.get("scan_id", ""),
        )

        # If spam — suppress entirely
        if memory_result["action_taken"] == "suppressed":
            await db.commit()
            return {
                "success": False, "signal_id": None,
                "classification": "rejected",
                "score_total": result["score_total"], "valid": True,
                "action": "suppressed",
                "rejection_reason": f"Duplicate spam (seen {memory_result['emit_count']}x in window)",
                "why_tradable": result.get("why_tradable", []),
                "why_not_tradable": ["Duplicate spam — suppressed"],
                "memory": memory_result, "review_required": False,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # If duplicate but not spam — downgrade actionable→candidate
        classification = result["classification"]
        if memory_result["duplicate_detected"] and classification == "actionable":
            classification = "candidate"

        # Step 3: Persist signal only for actionable + candidate (and only if new or versioned)
        signal_id = None
        should_persist = (
            classification in ("actionable", "candidate")
            and memory_result["action_taken"] in ("created", "new_version", "versioned")
        )

        if should_persist:
            try:
                signal_svc = SignalService(db)
                signal = await signal_svc.create_signal(
                    symbol=symbol,
                    strategy_name=strategy,
                    side=direction,
                    confidence=result["score_total"],
                    entry_price=entry,
                    stop_price=stop_loss,
                    take_profit_1=take_profit,
                    risk_score=result.get("validation", {}).get("validation_score", 0),
                    structure_score=result.get("score_components", {}).get("structure", 0),
                    confluence_tags=json.dumps(result.get("why_tradable", [])),
                    status="pending",
                    json_payload=json.dumps({
                        "classification": classification,
                        "score_total": result["score_total"],
                        "score_components": result.get("score_components"),
                        "why_tradable": result.get("why_tradable"),
                        "why_not_tradable": result.get("why_not_tradable"),
                        "memory_id": memory_result.get("memory_id"),
                        "version_number": memory_result.get("version_number"),
                        "fingerprint": memory_result.get("fingerprint"),
                        "review_required": memory_result.get("duplicate_detected", False),
                    }),
                )
                signal_id = signal.id
                # Link signal to memory
                await memory.link_signal(memory_result["memory_id"], signal_id)
                await db.commit()
            except Exception as e:
                result["persistence_error"] = str(e)[:100]
        else:
            await db.commit()

        return {
            "success": classification in ("actionable", "candidate"),
            "signal_id": signal_id,
            "classification": classification,
            "score_total": result["score_total"],
            "score_components": result.get("score_components"),
            "valid": True,
            "action": memory_result["action_taken"],
            "rejection_reason": result.get("rejection_reason"),
            "why_tradable": result.get("why_tradable", []),
            "why_not_tradable": result.get("why_not_tradable", []),
            "review_required": memory_result.get("duplicate_detected", False),
            "freshness": result.get("freshness"),
            "validation_warnings": result.get("validation", {}).get("soft_warnings", []),
            "memory": {
                "memory_id": memory_result.get("memory_id"),
                "version_number": memory_result.get("version_number"),
                "emit_count": memory_result.get("emit_count"),
                "duplicate_detected": memory_result.get("duplicate_detected"),
                "duplicate_type": memory_result.get("duplicate_type"),
                "action_taken": memory_result.get("action_taken"),
                "first_seen_at": memory_result.get("first_seen_at"),
                "last_seen_at": memory_result.get("last_seen_at"),
                "is_new": memory_result.get("is_new"),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        return {"success": False, "error": str(e)[:200], "classification": "invalid"}


@app.post("/api/signals/validate")
async def validate_signal_only(body: dict, db=Depends(get_db)):
    """Validate a signal without persisting. For preview/debugging.

    Returns validation + scoring + dedup result without creating anything.
    """
    try:
        from core.signal_intelligence import get_signal_pipeline
        from backend.dependencies import get_config_service

        config = get_config_service(db).get_config()
        result = get_signal_pipeline().process(
            symbol=body.get("symbol", ""),
            direction=body.get("direction", ""),
            entry=float(body.get("entry", 0)),
            stop_loss=float(body.get("stop_loss", 0)),
            take_profit=float(body.get("take_profit", 0)),
            source=body.get("source", "unknown"),
            strategy=body.get("strategy", ""),
            current_price=float(body.get("current_price", 0)),
            atr=float(body.get("atr", 0)),
            volatility_regime=body.get("volatility_regime", "unknown"),
            momentum=body.get("momentum", "neutral"),
            displacement_detected=body.get("displacement_detected", False),
            displacement_atr_multiple=float(body.get("displacement_atr_multiple", 0)),
            fvg_present=body.get("fvg_present", False),
            fvg_fill_pct=float(body.get("fvg_fill_pct", 0)),
            unfilled_fvg_count=int(body.get("unfilled_fvg_count", 0)),
            allowed_symbols=config.get("allowed_symbols", []),
        )
        return result
    except Exception as e:
        return {"valid": False, "error": str(e)[:200], "classification": "invalid"}


@app.get("/api/signals/dedup-stats")
async def dedup_stats(db=Depends(get_db)):
    """Get durable signal memory metrics — survives restarts."""
    try:
        from backend.services.signal_memory import DurableSignalMemory
        return await DurableSignalMemory(db).get_metrics()
    except Exception:
        return {"total_memory_records": 0, "durable": False}


@app.get("/api/signals/memory")
async def signal_memory_list(symbol: str = None, limit: int = 50, db=Depends(get_db)):
    """Get active signal memory records. Shows what setups the system remembers."""
    try:
        from backend.services.signal_memory import DurableSignalMemory
        records = await DurableSignalMemory(db).get_active_memories(symbol=symbol, limit=limit)
        return {"memories": records, "count": len(records), "durable": True}
    except Exception:
        return {"memories": [], "count": 0, "durable": False}


@app.get("/api/signals/memory/{memory_id}")
async def signal_memory_detail(memory_id: str, db=Depends(get_db)):
    """Get one signal memory record with version history."""
    try:
        from backend.services.signal_memory import DurableSignalMemory
        mem = DurableSignalMemory(db)
        record = await mem.get_memory(memory_id)
        if not record:
            return {"error": "Memory record not found"}
        history = await mem.get_version_history(memory_id)
        return {**record, "version_history": history}
    except Exception as e:
        return {"error": str(e)[:200]}


@app.post("/api/signals/memory/expire-stale")
async def expire_stale_memories(max_age_hours: int = 24, db=Depends(get_db)):
    """Expire memory records older than max_age_hours."""
    try:
        from backend.services.signal_memory import DurableSignalMemory
        expired = await DurableSignalMemory(db).expire_stale(max_age_hours)
        await db.commit()
        return {"expired": expired, "max_age_hours": max_age_hours}
    except Exception as e:
        return {"expired": 0, "error": str(e)[:200]}


@app.post("/api/drm/decision/{symbol}")
async def drm_decision(symbol: str, resolution: str = "1h", lookback: str = "5D", db=Depends(get_db)):
    """DRM Decision Engine — converts DRM analysis into a trade decision.

    Instead of dumping zones, returns:
    - setup_detected (yes/no)
    - setup_type (displacement_rebalance_long, no_valid_setup, etc.)
    - confluence_score (0-7)
    - trade_eligible (yes/no)
    - why_tradable / why_not_tradable
    """
    try:
        from core.signal_intelligence import get_signal_pipeline

        # Run DRM analysis first
        drm_result = await drm_analysis(symbol, resolution, lookback)

        if drm_result.get("error"):
            return {
                "symbol": symbol.upper(),
                "setup_detected": False,
                "setup_type": "no_data",
                "trade_eligible": False,
                "why_not_tradable": [drm_result["error"]],
                "why_tradable": [],
                "confluence_score": 0,
            }

        # Run DRM decision engine
        decision = get_signal_pipeline().drm_decision.evaluate(drm_result)

        # Merge full DRM data for context
        decision["drm_data"] = {
            "current_price": drm_result.get("current_price"),
            "atr": drm_result.get("atr"),
            "volatility_regime": drm_result.get("volatility_regime"),
            "displacements": drm_result.get("displacements", []),
            "fair_value_gaps": drm_result.get("fair_value_gaps", []),
            "unfilled_fvgs": drm_result.get("unfilled_fvgs", 0),
            "signals": drm_result.get("signals", []),
        }

        return decision

    except Exception as e:
        return {
            "symbol": symbol.upper(),
            "setup_detected": False,
            "setup_type": "error",
            "trade_eligible": False,
            "why_not_tradable": [str(e)[:200]],
            "why_tradable": [],
            "error": str(e)[:200],
        }


# ══════════════════════════════════════════════════════════════════════
# OPERATOR FEED — memory-aware, clean-by-construction signal stream
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/signals/feed")
async def operator_signal_feed(
    main_feed: bool = True,
    include_history: bool = False,
    include_superseded: bool = False,
    include_repeat_noise: bool = False,
    actionable_only: bool = False,
    candidates_only: bool = False,
    symbol: str = None,
    status: str = None,
    limit: int = 50,
    db=Depends(get_db),
):
    """Memory-aware operator signal feed — clean by construction.

    Default: returns only current versions of meaningful setups.
    Superseded versions, repeat noise, stale signals excluded by default.

    This is where capital deployment decisions begin.

    Query params:
      main_feed=true (default) — clean operator feed
      include_history=true — include everything
      include_superseded=true — include old versions
      include_repeat_noise=true — include spam emissions
      actionable_only=true — only actionable classification
      symbol=USOIL — filter by symbol
      status=pending — filter by signal status

    Each signal includes:
      is_current_version, is_superseded, show_in_main_feed,
      repeat_noise, review_required, review_priority,
      conflicting_duplicate, conflict_reason, memory_id,
      version_number, emit_count, classification, score_total,
      why_tradable, why_not_tradable
    """
    try:
        from backend.services.operator_feed import OperatorFeedService
        feed_svc = OperatorFeedService(db)
        return await feed_svc.get_operator_feed(
            main_feed=main_feed,
            include_history=include_history,
            include_superseded=include_superseded,
            include_repeat_noise=include_repeat_noise,
            actionable_only=actionable_only,
            candidates_only=candidates_only,
            symbol=symbol,
            status=status,
            limit=limit,
        )
    except Exception as e:
        return {
            "signals": [],
            "count": 0,
            "summary": {"total_signals": 0, "main_feed_count": 0},
            "error": str(e)[:200],
        }


# ══════════════════════════════════════════════════════════════════════
# ENHANCED SAFETY — crash-proof endpoints (NEVER return 500)
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/safety/full-status")
async def full_safety_status(db=Depends(get_db)):
    """Complete safety state for frontend truth.

    This endpoint MUST NEVER crash. If any subsystem fails,
    it returns degraded state instead of a 500 error.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    # Load config — with safe fallback
    config = {}
    try:
        from backend.dependencies import get_config_service
        cfg = get_config_service(db)
        config = cfg.get_config()
    except Exception:
        config = {
            "mode": "shadow", "kill_switch": {"active": False, "reason": ""},
            "allowed_symbols": ["BTCUSD", "NAS100", "US30", "EURUSD", "XAUUSD", "USOIL"],
            "risk": {}, "scanning": {"auto_enabled": False}, "version": "unknown",
        }

    # Load circuit breaker — try hardened first, fall back to basic
    cb_status = {"tripped": False, "consecutive_losses": 0, "max_consecutive_losses": 3}
    cb_tripped = False
    try:
        from core.risk_policy import get_hardened_breaker
        cb = get_hardened_breaker()
        cb_status = cb.status()
        cb_tripped = cb.tripped
    except Exception:
        try:
            from core.safety import get_circuit_breaker
            cb = get_circuit_breaker()
            cb_status = cb.status()
            cb_tripped = cb.tripped
        except Exception:
            pass

    # Load trade cooldown
    cooldown_status = {"cooldown_seconds": 300, "active_cooldowns": {}}
    try:
        from core.safety import get_trade_cooldown
        cooldown_status = get_trade_cooldown().status()
    except Exception:
        pass

    # Build blockers
    blockers = []
    ks = config.get("kill_switch", {})
    if ks.get("active"):
        blockers.append("Kill switch active")
    if cb_tripped:
        blockers.append(f"Circuit breaker: {cb_status.get('consecutive_losses', 0)} consecutive losses")
    if config.get("mode") == "shadow":
        blockers.append("Shadow mode — simulation only")

    return {
        "timestamp": now_iso,
        "mode": config.get("mode", "shadow"),
        "kill_switch": config.get("kill_switch", {"active": False, "reason": ""}),
        "circuit_breaker": cb_status,
        "trade_cooldown": cooldown_status,
        "allowed_symbols": config.get("allowed_symbols", []),
        "risk_config": config.get("risk", {}),
        "scanning": config.get("scanning", {}),
        "config_version": config.get("version", "unknown"),
        "safety_summary": {
            "can_trade": not ks.get("active", False) and not cb_tripped,
            "blockers": blockers,
        },
    }


@app.post("/api/safety/hardened-reset")
async def hardened_breaker_reset(body: dict = {}, db=Depends(get_db)):
    """Reset circuit breaker. Refuses if kill switch active unless forced."""
    try:
        # Try hardened breaker first
        from core.risk_policy import get_hardened_breaker
        from backend.dependencies import get_config_service

        cfg = get_config_service(db)
        config = cfg.get_config()
        cb = get_hardened_breaker()

        result = cb.force_reset(
            reason=body.get("reason", "manual_reset"),
            source=body.get("source", "operator"),
            kill_switch_active=config.get("kill_switch", {}).get("active", False),
            force_override=body.get("force_override", False),
        )

        return {**result, "circuit_breaker": cb.status()}

    except Exception:
        # Fallback to basic breaker
        try:
            from core.safety import get_circuit_breaker
            cb = get_circuit_breaker()
            cb.force_reset()
            return {"success": True, "circuit_breaker": cb.status()}
        except Exception as e:
            return {"success": False, "error": str(e)[:200]}
