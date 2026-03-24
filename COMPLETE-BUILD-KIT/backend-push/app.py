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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routers import (
    account_router, agents_router, config_router, control_router,
    health_router, incidents_router, journals_router, market_router,
    metrics_router, reconciliation_router, review_router, risk_router,
    signals_router, trades_router,
)
from backend.db.session import create_tables, AsyncSessionLocal
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
        "name": "ICT Trade Mission Control — Analytics",
        "version": VERSION,
        "symbols": ["BTCUSD", "NAS100", "US30", "EURUSD", "XAUUSD", "USOIL"],
        "mode": "analytical — manual execution",
        "docs": "/docs",
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
    from core.tradelocker_data import get_tradelocker_data
    tld = get_tradelocker_data()
    resolved = {}
    for sym in ["BTCUSD", "NAS100", "US30", "EURUSD", "XAUUSD", "USOIL"]:
        inst_id = tld.resolve_instrument_id(sym)
        resolved[sym] = {"instrument_id": inst_id, "found": inst_id is not None}
    return {"instruments": resolved}


@app.get("/api/tl/candles/{symbol}")
async def tl_candles(symbol: str, resolution: str = "1h", lookback: str = "7D"):
    """Get candle data from TradeLocker via official SDK.

    Examples:
      /api/tl/candles/USOIL?resolution=1h&lookback=7D
      /api/tl/candles/BTCUSD?resolution=5m&lookback=1D
      /api/tl/candles/XAUUSD?resolution=1D&lookback=3M
    """
    from core.tradelocker_data import get_tradelocker_data
    return get_tradelocker_data().get_candles(symbol.upper(), resolution, lookback)


@app.get("/api/tl/positions")
async def tl_positions():
    """Get all open positions from TradeLocker — live P&L."""
    from core.tradelocker_data import get_tradelocker_data
    positions = get_tradelocker_data().get_positions()
    return {
        "count": len(positions),
        "positions": positions,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/tl/price/{symbol}")
async def tl_latest_price(symbol: str):
    """Get latest price for a symbol from TradeLocker."""
    from core.tradelocker_data import get_tradelocker_data
    price = get_tradelocker_data().get_latest_price(symbol.upper())
    return {"symbol": symbol.upper(), "price": price, "source": "tradelocker"}


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

    Detects: displacement events, fair value gaps, entry zones,
    liquidity targets, and barrier-touch probabilities.

    This IS your edge — the exact model that made $23K on USOIL.

    Examples:
      /api/drm/USOIL?resolution=1h&lookback=5D
      /api/drm/BTCUSD?resolution=4h&lookback=7D
      /api/drm/XAUUSD?resolution=15m&lookback=1D
    """
    from core.strategy.drm import get_drm_engine
    from core.tradelocker_data import get_tradelocker_data

    tld = get_tradelocker_data()
    candle_data = tld.get_candles(symbol.upper(), resolution, lookback)

    if "error" in candle_data:
        return {"symbol": symbol, "error": candle_data["error"]}

    candles = candle_data.get("candles", [])
    if not candles:
        return {"symbol": symbol, "error": "no candle data"}

    drm = get_drm_engine()
    result = drm.analyze(symbol.upper(), candles)
    result["resolution"] = resolution
    result["lookback"] = lookback
    result["candle_count"] = len(candles)
    return result


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
    """Run DRM analysis on ALL active symbols.

    Finds displacement rebalance setups across BTCUSD, NAS100,
    US30, EURUSD, XAUUSD, USOIL simultaneously.
    """
    from core.strategy.drm import get_drm_engine
    from core.tradelocker_data import get_tradelocker_data
    from core.intelligence import get_scratchpad

    scratchpad = get_scratchpad()
    session_id = scratchpad.start_session()
    scratchpad.log("drm_scan_start")

    tld = get_tradelocker_data()
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
            candle_data = tld.get_candles(symbol, "1h", "5D")
            candles = candle_data.get("candles", [])
            if not candles or "error" in candle_data:
                results["symbols"][symbol] = {"error": candle_data.get("error", "no data")}
                scratchpad.log("drm_skip", symbol=symbol, reason=candle_data.get("error", "no data"))
                continue

            analysis = drm.analyze(symbol, candles)
            results["symbols"][symbol] = {
                "current_price": analysis.get("current_price"),
                "atr": analysis.get("atr"),
                "volatility_regime": analysis.get("volatility_regime"),
                "displacements": len(analysis.get("displacements", [])),
                "total_fvgs": len(analysis.get("fair_value_gaps", [])),
                "unfilled_fvgs": analysis.get("unfilled_fvgs", 0),
                "signals": analysis.get("signals", []),
            }

            results["summary"]["total_fvgs"] += len(analysis.get("fair_value_gaps", []))
            results["summary"]["unfilled_fvgs"] += analysis.get("unfilled_fvgs", 0)

            for sig in analysis.get("signals", []):
                sig["symbol"] = symbol
                results["all_signals"].append(sig)
                results["summary"]["signals"] += 1

            scratchpad.log("drm_analyzed", symbol=symbol,
                price=analysis.get("current_price"),
                fvgs=len(analysis.get("fair_value_gaps", [])),
                signals=len(analysis.get("signals", [])))

        except Exception as e:
            results["symbols"][symbol] = {"error": str(e)[:200]}
            scratchpad.log("drm_error", symbol=symbol, error=str(e)[:100])

    # Sort signals by confidence
    results["all_signals"].sort(key=lambda s: s.get("conf_score", 0), reverse=True)

    scratchpad.log("drm_scan_complete",
        symbols_scanned=len(results["symbols"]),
        total_signals=results["summary"]["signals"])

    return results
