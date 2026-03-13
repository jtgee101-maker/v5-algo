"""FastAPI application — ICT Trade Mission Control API.

Integrates patterns from:
- Byte-Ventures/claude-trader: Circuit breaker, trade cooldown, ATR sizing
- nirholas/free-crypto-news: Free sentiment API
- virattt/dexter: Scratchpad reasoning logs
- yorkeccak/finance: Multi-source data aggregation
- degentic-tools/claude-code-trading-terminal: Data pipeline validation
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
                    currency="USD", updated_at=datetime.now(timezone.utc).isoformat(),
                )
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
    title="ICT Trade Mission Control",
    description="Self-healing agent-assisted CFD trading system API",
    version=VERSION, lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# Mount all routers
for router in [
    health_router, account_router, market_router, signals_router,
    trades_router, risk_router, incidents_router, config_router,
    control_router, journals_router, agents_router, metrics_router,
    reconciliation_router, review_router,
]:
    app.include_router(router, prefix="/api")


@app.get("/")
async def root():
    return {"name": "ICT Trade Mission Control", "version": VERSION, "docs": "/docs"}


# ══════════════════════════════════════════════════════════════════════
# BROKER TEST
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
            result["instruments"] = [{"name": i.get("name",""), "id": i.get("tradableInstrumentId","")} for i in instruments[:30]]
        except Exception as e:
            result["instruments"] = str(e)
        await client.disconnect()
    except Exception as e:
        result["error"] = str(e)
        result["auth"] = "failed"
    return result


# ══════════════════════════════════════════════════════════════════════
# SEED DEMO
# ══════════════════════════════════════════════════════════════════════

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
                for sym, side, conf, st in [("NAS100","buy",0.78,"pending"),("EURUSD","buy",0.74,"pending"),
                    ("US30","sell",0.82,"approved"),("BTCUSD","sell",0.65,"rejected")]:
                    await sig_repo.create(symbol=sym, strategy_name="ny_sweep_reversal",
                        strategy_version="v1", timestamp=now.isoformat(), side=side,
                        confidence=conf, entry_price=18245.5, stop_price=18210.0,
                        take_profit_1=18290.0, confluence_tags=json.dumps(["smt_divergence","sweep_rejected"]),
                        status=st, json_payload="{}")
                created.append("signals")
            await session.commit()
        return {"success": True, "created": created}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════════════
# CANDLE URL AUTO-DISCOVERY
# ══════════════════════════════════════════════════════════════════════

_discovered_candle_pattern: str | None = None


async def _discover_candle_url(client, inst_id: str) -> str:
    """Auto-discover the correct TradeLocker candle URL.

    Tries all known patterns, caches the first one that works.
    Also checks data/broker_endpoints.json if discover_broker.py was run.
    """
    global _discovered_candle_pattern

    # Check if already discovered this session
    if _discovered_candle_pattern:
        return _discovered_candle_pattern.format(inst_id=inst_id)

    # Check if discover_broker.py saved a result
    try:
        import json as _json
        from pathlib import Path
        cached = Path("data/broker_endpoints.json")
        if cached.exists():
            data = _json.loads(cached.read_text())
            pattern = data.get("working_candle_url")
            if pattern:
                url = pattern.format(inst_id=inst_id)
                resp = await client._client.get(
                    url, headers=client._auth_headers(),
                    params={"resolution": "5", "count": 5},
                )
                if resp.status_code in (200, 201):
                    _discovered_candle_pattern = pattern
                    return url
    except Exception:
        pass

    # Try all known patterns
    acc_id = os.environ.get("TRADELOCKER_ACCOUNT_ID", "1967672")
    acc_num = os.environ.get("TRADELOCKER_ACC_NUM", "3")

    patterns = [
        f"/trade/accounts/{acc_num}/instruments/{{inst_id}}/candles",
        f"/trade/accounts/{acc_id}/instruments/{{inst_id}}/candles",
        f"/trade/instruments/{{inst_id}}/candles",
        f"/trade/history/{{inst_id}}/candles",
        f"/trade/accounts/{acc_num}/history/{{inst_id}}/candles",
        f"/history/candles/{{inst_id}}",
        f"/accounts/{acc_num}/instruments/{{inst_id}}/candles",
        f"/instruments/{{inst_id}}/candles",
    ]

    param_sets = [
        {"resolution": "5", "count": "10"},
        {"resolution": "300", "count": "10"},
        {"resolution": "5m", "count": "10"},
    ]

    for pattern in patterns:
        url = pattern.format(inst_id=inst_id)
        for params in param_sets:
            try:
                resp = await client._client.get(
                    url, headers=client._auth_headers(), params=params,
                )
                if resp.status_code in (200, 201):
                    try:
                        data = resp.json()
                        if data.get("d") or data.get("candles") or data.get("data") or isinstance(data, list):
                            _discovered_candle_pattern = pattern
                            return url
                    except Exception:
                        pass
            except Exception:
                continue

    # Last resort — return first pattern
    return patterns[0].format(inst_id=inst_id)


# ══════════════════════════════════════════════════════════════════════
# MARKET SCANNER — with safety, sentiment, and scratchpad
# ══════════════════════════════════════════════════════════════════════

@app.post("/api/run-scan")
async def run_scan():
    """Full market scan with integrated intelligence.

    Flow:
    1. Safety check (circuit breaker + cooldown) — claude-trader
    2. Connect to broker, fetch candles
    3. Fetch news sentiment — free-crypto-news
    4. Validate prices — trading-terminal pattern
    5. Run market structure + strategies
    6. Log everything to scratchpad — dexter pattern
    7. Persist signals to DB
    """
    import json as json_mod
    from core.safety import get_circuit_breaker, get_trade_cooldown
    from core.intelligence import get_news_service, get_scratchpad, get_price_validator

    now = datetime.now(timezone.utc)
    hour, weekday = now.hour, now.weekday()
    scratchpad = get_scratchpad()
    session_id = scratchpad.start_session()

    result = {
        "timestamp": now.isoformat(),
        "session_id": session_id,
        "symbols_scanned": [],
        "signals_generated": [],
        "errors": [],
        "session": "off_hours",
        "candle_counts": {},
        "news_sentiment": None,
        "safety": {},
    }

    # ── Step 1: Safety checks (claude-trader pattern) ────────────────
    cb = get_circuit_breaker()
    blocked, reason = cb.is_blocked()
    result["safety"]["circuit_breaker"] = cb.status()
    if blocked:
        result["errors"].append(reason)
        scratchpad.log("safety_blocked", reason=reason)
        return result

    scratchpad.log("safety_check", circuit_breaker="ok", cooldown="ok")

    # ── Step 2: Session-aware pair selection ──────────────────────────
    active_pairs = ["BTCUSD"]  # Crypto 24/7
    result["session"] = "crypto_only"
    if weekday < 5:
        if 13 <= hour <= 21:
            active_pairs.extend(["NAS100", "US30", "EURUSD"])
            result["session"] = "ny_session"
        elif 8 <= hour < 13:
            active_pairs.append("EURUSD")
            result["session"] = "london_pre_ny"

    scratchpad.log("scan_start", pairs=active_pairs, session=result["session"])

    # ── Step 3: Fetch news sentiment (free-crypto-news) ──────────────
    try:
        news = get_news_service()
        market_ctx = await news.get_market_context()
        result["news_sentiment"] = market_ctx
        scratchpad.log("news_sentiment",
            sentiment=market_ctx.get("btc_sentiment"),
            score=market_ctx.get("sentiment_score"),
            headlines=len(market_ctx.get("top_headlines", [])),
        )
    except Exception as e:
        result["news_sentiment"] = {"error": str(e)[:100]}
        scratchpad.log("news_error", error=str(e)[:100])

    # ── Step 4: Connect to broker ────────────────────────────────────
    try:
        from core.execution.client import TradeLockerClient
        client = TradeLockerClient()
        await client.connect()
        scratchpad.log("broker_connected")
    except Exception as e:
        result["errors"].append(f"Broker: {str(e)[:200]}")
        scratchpad.log("broker_error", error=str(e)[:200])
        return result

    # ── Step 5: Update account balance ───────────────────────────────
    try:
        acct_data = await client.get_account_state()
        if isinstance(acct_data, dict) and acct_data.get("s") == "ok":
            details = acct_data.get("d", {}).get("accountDetailsData", [])
            if len(details) >= 5:
                from backend.db.models import Account
                from backend.db.repositories.base import GenericRepository
                async with AsyncSessionLocal() as session:
                    await GenericRepository(session, Account).update_by_id(
                        "acct_demo_1", balance=float(details[0]), equity=float(details[1]),
                        free_margin=float(details[4]) if len(details) > 4 else 0,
                        status="connected", updated_at=now.isoformat())
                    await session.commit()
                scratchpad.log("account_updated", balance=details[0], equity=details[1])
    except Exception as e:
        result["errors"].append(f"Account: {str(e)[:100]}")

    # ── Step 6: Scan each pair ───────────────────────────────────────
    acc_num = os.environ.get("TRADELOCKER_ACC_NUM", "3")
    price_validator = get_price_validator()
    cooldown = get_trade_cooldown()

    for symbol in active_pairs:
        # Cooldown check (claude-trader pattern)
        cd_blocked, cd_reason = cooldown.is_blocked(symbol)
        if cd_blocked:
            result["errors"].append(cd_reason)
            scratchpad.log("cooldown_blocked", symbol=symbol, reason=cd_reason)
            continue

        try:
            instruments = await client.get_instruments()
            inst = next((i for i in instruments if i.get("name") == symbol), None)
            if not inst:
                result["errors"].append(f"{symbol}: not found")
                scratchpad.log("instrument_missing", symbol=symbol)
                continue

            inst_id = inst.get("tradableInstrumentId")

            # Fetch candles — auto-discovers correct URL pattern
            candle_url = await _discover_candle_url(client, inst_id)
            resp = await client._client.get(
                candle_url,
                headers=client._auth_headers(),
                params={"resolution": "5", "count": 200},
            )

            if resp.status_code not in (200, 201):
                # Try alternate param format
                resp = await client._client.get(
                    candle_url,
                    headers=client._auth_headers(),
                    params={"resolution": "300", "count": 200},
                )

            if resp.status_code not in (200, 201):
                result["errors"].append(f"{symbol}: candles HTTP {resp.status_code} at {candle_url}")
                scratchpad.log("candles_error", symbol=symbol, status=resp.status_code, url=candle_url)
                result["symbols_scanned"].append(symbol)
                continue

            candle_data = resp.json()
            result["symbols_scanned"].append(symbol)

            # Count candles
            if isinstance(candle_data, dict) and "d" in candle_data:
                d = candle_data["d"]
                if isinstance(d, list):
                    result["candle_counts"][symbol] = len(d)
                elif isinstance(d, dict):
                    k = next(iter(d), None)
                    if k and isinstance(d[k], list):
                        result["candle_counts"][symbol] = len(d[k])

            scratchpad.log("candles_fetched", symbol=symbol,
                count=result["candle_counts"].get(symbol, 0))

            # ── Price validation (trading-terminal pattern) ──────────
            try:
                ref_price = await price_validator.get_reference_price(symbol)
                if ref_price:
                    scratchpad.log("price_reference", symbol=symbol,
                        reference=ref_price, source="coingecko")
            except Exception:
                pass

            # ── Market structure + strategies ────────────────────────
            try:
                from core.market_structure.engine import MarketStructureEngine
                market_state = MarketStructureEngine().build(
                    symbol=symbol, candle_data=candle_data, timestamp=now)

                scratchpad.log("market_structure", symbol=symbol,
                    bias=str(market_state.structure_bias.value) if market_state.structure_bias else "unknown",
                    swings=len(market_state.swing_points),
                    fvgs=len(market_state.fvgs),
                    sweeps=len(market_state.sweep_events),
                )

                from core.strategy.engine import StrategyEngine
                signals = StrategyEngine().evaluate(market_state)

                for signal in signals:
                    scratchpad.log("signal_generated", symbol=signal.symbol,
                        strategy=signal.strategy_id, direction=signal.direction.value,
                        confidence=round(signal.confidence, 3),
                        entry=signal.entry_price, stop=signal.stop_price,
                        rr=signal.reward_risk, tags=signal.confluence_tags)

                    from backend.db.models import TradeSignalRecord
                    from backend.db.repositories.base import GenericRepository
                    async with AsyncSessionLocal() as session:
                        await GenericRepository(session, TradeSignalRecord).create(
                            symbol=signal.symbol, strategy_name=signal.strategy_id,
                            strategy_version="v1", timestamp=now.isoformat(),
                            side="buy" if signal.direction.value == "long" else "sell",
                            confidence=signal.confidence, entry_price=signal.entry_price,
                            stop_price=signal.stop_price,
                            take_profit_1=signal.targets[0].price if signal.targets else None,
                            confluence_tags=json_mod.dumps(signal.confluence_tags),
                            status="pending", json_payload=json_mod.dumps({
                                "reward_risk": signal.reward_risk,
                                "invalidation": signal.invalidation,
                                "news_sentiment": result.get("news_sentiment", {}).get("btc_sentiment"),
                                "scratchpad_session": session_id,
                            }))
                        await session.commit()

                    result["signals_generated"].append({
                        "symbol": signal.symbol, "strategy": signal.strategy_id,
                        "direction": signal.direction.value,
                        "confidence": round(signal.confidence, 3),
                        "entry": signal.entry_price, "stop": signal.stop_price,
                        "rr": signal.reward_risk,
                    })

            except Exception as e:
                result["errors"].append(f"{symbol}: analysis — {str(e)[:200]}")
                scratchpad.log("analysis_error", symbol=symbol, error=str(e)[:200])

        except Exception as e:
            result["errors"].append(f"{symbol}: {str(e)[:200]}")
            scratchpad.log("scan_error", symbol=symbol, error=str(e)[:200])

    try:
        await client.disconnect()
    except Exception:
        pass

    scratchpad.log("scan_complete",
        symbols=len(result["symbols_scanned"]),
        signals=len(result["signals_generated"]),
        errors=len(result["errors"]))

    result["scratchpad_entries"] = len(scratchpad.get_entries())
    return result


# ══════════════════════════════════════════════════════════════════════
# INTELLIGENCE ENDPOINTS — news, safety, scratchpad
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/news/sentiment")
async def news_sentiment():
    """Get current crypto news sentiment (free, no key)."""
    from core.intelligence import get_news_service
    return await get_news_service().get_market_context()


@app.get("/api/news/latest")
async def news_latest(limit: int = 10):
    """Get latest crypto news articles."""
    from core.intelligence import get_news_service
    articles = await get_news_service().get_latest_news(limit)
    return {"articles": articles if isinstance(articles, list) else []}


@app.get("/api/news/bitcoin")
async def news_bitcoin():
    """Get Bitcoin-specific news."""
    from core.intelligence import get_news_service
    return {"articles": await get_news_service().get_bitcoin_news(10)}


@app.get("/api/safety/status")
async def safety_status():
    """Get safety module status — circuit breaker + cooldown."""
    from core.safety import get_circuit_breaker, get_trade_cooldown
    return {
        "circuit_breaker": get_circuit_breaker().status(),
        "trade_cooldown": get_trade_cooldown().status(),
    }


@app.post("/api/safety/reset-breaker")
async def reset_circuit_breaker():
    """Manually reset the circuit breaker."""
    from core.safety import get_circuit_breaker
    get_circuit_breaker().force_reset()
    return {"success": True, "status": get_circuit_breaker().status()}


@app.get("/api/scratchpad/sessions")
async def scratchpad_sessions(count: int = 20):
    """List recent scratchpad sessions (Dexter pattern)."""
    from core.intelligence import get_scratchpad
    return {"sessions": get_scratchpad().get_recent_sessions(count)}


@app.get("/api/scratchpad/{session_id}")
async def scratchpad_detail(session_id: str):
    """Get full reasoning log for a scan session."""
    from core.intelligence import get_scratchpad
    entries = get_scratchpad().get_session_log(session_id)
    return {"session_id": session_id, "entries": entries}


# ══════════════════════════════════════════════════════════════════════
# BROKER DISCOVERY — self-healing endpoint finder
# ══════════════════════════════════════════════════════════════════════

@app.post("/api/discover-candles")
async def discover_candles():
    """Auto-discover working TradeLocker candle URL patterns.

    Tries every known URL variation and returns which ones work.
    The working pattern is cached for subsequent run-scan calls.
    """
    global _discovered_candle_pattern
    _discovered_candle_pattern = None  # Force re-discovery

    from core.execution.client import TradeLockerClient
    client = TradeLockerClient()
    await client.connect()

    instruments = await client.get_instruments()
    btc = next((i for i in instruments if "BTC" in i.get("name", "")), None)
    if not btc:
        await client.disconnect()
        return {"error": "No BTC instrument found", "instruments": [i.get("name") for i in instruments[:30]]}

    inst_id = btc.get("tradableInstrumentId")
    acc_id = os.environ.get("TRADELOCKER_ACCOUNT_ID", "1967672")
    acc_num = os.environ.get("TRADELOCKER_ACC_NUM", "3")

    patterns = [
        f"/trade/accounts/{acc_num}/instruments/{inst_id}/candles",
        f"/trade/accounts/{acc_id}/instruments/{inst_id}/candles",
        f"/trade/instruments/{inst_id}/candles",
        f"/trade/history/{inst_id}/candles",
        f"/trade/accounts/{acc_num}/history/{inst_id}/candles",
        f"/history/candles/{inst_id}",
        f"/accounts/{acc_num}/instruments/{inst_id}/candles",
        f"/instruments/{inst_id}/candles",
        f"/trade/accounts/{acc_num}/historicalCandles/{inst_id}",
    ]

    param_sets = [
        {"resolution": "5", "count": "10"},
        {"resolution": "300", "count": "10"},
        {"resolution": "5m", "count": "10"},
    ]

    results = []
    working = None

    for url in patterns:
        for params in param_sets:
            try:
                resp = await client._client.get(url, headers=client._auth_headers(), params=params)
                entry = {"url": url, "params": params, "status": resp.status_code}
                if resp.status_code in (200, 201):
                    try:
                        data = resp.json()
                        entry["has_data"] = bool(data.get("d") or data.get("candles") or isinstance(data, list))
                        entry["keys"] = list(data.keys()) if isinstance(data, dict) else "list"
                        entry["preview"] = resp.text[:200]
                        if entry["has_data"] and not working:
                            working = {"url": url, "params": params}
                    except Exception:
                        entry["has_data"] = False
                elif resp.status_code != 404:
                    entry["body"] = resp.text[:150]
                results.append(entry)
            except Exception as e:
                results.append({"url": url, "params": params, "status": "error", "error": str(e)[:100]})

    await client.disconnect()

    # Cache the working pattern
    if working:
        # Convert specific inst_id back to template
        template = working["url"].replace(str(inst_id), "{inst_id}")
        _discovered_candle_pattern = template

    return {
        "instrument": {"name": btc.get("name"), "id": inst_id},
        "acc_num": acc_num,
        "acc_id": acc_id,
        "working": working,
        "cached_pattern": _discovered_candle_pattern,
        "tested": [r for r in results if r.get("status") != 404],  # Skip 404s for clarity
    }
