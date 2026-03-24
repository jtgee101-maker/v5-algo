"""Market data service — free, reliable data for analytical signals.

Instead of depending on TradeLocker candle API (which 404s),
pull data from sources that work:

1. CoinGecko (free, no key) — crypto prices, charts, market cap
2. free-crypto-news (free, no key) — sentiment, headlines
3. Yahoo Finance via yfinance — indices, FX, commodities
4. TradeLocker — account state + execution only

Symbols covered:
  Crypto: BTCUSD
  Indices: NAS100, US30
  FX: EURUSD
  Commodities: XAUUSD (Gold), USOIL (Oil)
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)


# ── CoinGecko (free, no API key) ────────────────────────────────────

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

COINGECKO_MAP = {
    "BTCUSD": "bitcoin",
    "ETHUSD": "ethereum",
}

# ── Yahoo Finance symbols ────────────────────────────────────────────

YAHOO_MAP = {
    "NAS100": "^IXIC",       # NASDAQ Composite (proxy for NAS100)
    "US30": "^DJI",          # Dow Jones
    "EURUSD": "EURUSD=X",   # EUR/USD forex
    "XAUUSD": "GC=F",       # Gold futures
    "USOIL": "CL=F",        # WTI Crude Oil futures
}

ALL_SYMBOLS = ["BTCUSD", "NAS100", "US30", "EURUSD", "XAUUSD", "USOIL"]


class MarketDataService:
    """Aggregates market data from multiple free sources."""

    def __init__(self):
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl = 60  # 1 min

    async def get_all_prices(self) -> dict[str, dict]:
        """Get current prices for all symbols from free sources."""
        prices = {}

        # Crypto from CoinGecko
        try:
            crypto = await self._coingecko_prices()
            prices.update(crypto)
        except Exception as e:
            logger.debug("market_data.coingecko_error", error=str(e)[:100])

        # Everything else from Yahoo Finance
        try:
            yahoo = await self._yahoo_prices()
            prices.update(yahoo)
        except Exception as e:
            logger.debug("market_data.yahoo_error", error=str(e)[:100])

        return prices

    async def get_symbol_detail(self, symbol: str) -> dict[str, Any]:
        """Get detailed data for one symbol."""
        if symbol in COINGECKO_MAP:
            return await self._coingecko_detail(symbol)
        elif symbol in YAHOO_MAP:
            return await self._yahoo_detail(symbol)
        return {"symbol": symbol, "error": "unknown symbol"}

    async def get_crypto_market_overview(self) -> dict[str, Any]:
        """Global crypto market overview from CoinGecko."""
        cached = self._get_cached("crypto_overview")
        if cached:
            return cached

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{COINGECKO_BASE}/global")
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    result = {
                        "total_market_cap_usd": data.get("total_market_cap", {}).get("usd", 0),
                        "total_volume_24h": data.get("total_volume", {}).get("usd", 0),
                        "btc_dominance": data.get("market_cap_percentage", {}).get("btc", 0),
                        "eth_dominance": data.get("market_cap_percentage", {}).get("eth", 0),
                        "market_cap_change_24h": data.get("market_cap_change_percentage_24h_usd", 0),
                        "active_cryptos": data.get("active_cryptocurrencies", 0),
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                    self._set_cached("crypto_overview", result)
                    return result
        except Exception as e:
            logger.debug("coingecko.global_error", error=str(e)[:100])

        return {"error": "unavailable"}

    async def get_btc_chart(self, days: int = 7) -> dict[str, Any]:
        """BTC price chart data from CoinGecko (free)."""
        cache_key = f"btc_chart_{days}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{COINGECKO_BASE}/coins/bitcoin/market_chart",
                    params={"vs_currency": "usd", "days": str(days)},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    prices = data.get("prices", [])
                    volumes = data.get("total_volumes", [])

                    result = {
                        "symbol": "BTCUSD",
                        "days": days,
                        "data_points": len(prices),
                        "prices": [
                            {"timestamp": p[0], "price": round(p[1], 2)}
                            for p in prices
                        ],
                        "volumes": [
                            {"timestamp": v[0], "volume": round(v[1], 0)}
                            for v in volumes
                        ],
                        "current": round(prices[-1][1], 2) if prices else None,
                        "high": round(max(p[1] for p in prices), 2) if prices else None,
                        "low": round(min(p[1] for p in prices), 2) if prices else None,
                        "change_pct": round(
                            ((prices[-1][1] - prices[0][1]) / prices[0][1]) * 100, 2
                        ) if len(prices) >= 2 else 0,
                    }
                    self._set_cached(cache_key, result, ttl=300)  # 5 min cache for charts
                    return result
        except Exception as e:
            logger.debug("coingecko.chart_error", error=str(e)[:100])

        return {"symbol": "BTCUSD", "error": "unavailable"}

    # ── Private: CoinGecko ───────────────────────────────────────────

    async def _coingecko_prices(self) -> dict[str, dict]:
        cached = self._get_cached("cg_prices")
        if cached:
            return cached

        ids = ",".join(COINGECKO_MAP.values())
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{COINGECKO_BASE}/simple/price",
                    params={
                        "ids": ids,
                        "vs_currencies": "usd",
                        "include_24hr_change": "true",
                        "include_24hr_vol": "true",
                        "include_market_cap": "true",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    result = {}
                    for symbol, coin_id in COINGECKO_MAP.items():
                        coin = data.get(coin_id, {})
                        result[symbol] = {
                            "symbol": symbol,
                            "price": coin.get("usd", 0),
                            "change_24h_pct": round(coin.get("usd_24h_change", 0), 2),
                            "volume_24h": coin.get("usd_24h_vol", 0),
                            "market_cap": coin.get("usd_market_cap", 0),
                            "source": "coingecko",
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }
                    self._set_cached("cg_prices", result)
                    return result
        except Exception:
            pass
        return {}

    async def _coingecko_detail(self, symbol: str) -> dict[str, Any]:
        coin_id = COINGECKO_MAP.get(symbol)
        if not coin_id:
            return {"error": f"unknown crypto: {symbol}"}

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{COINGECKO_BASE}/coins/{coin_id}",
                    params={"localization": "false", "tickers": "false",
                            "community_data": "false", "developer_data": "false"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    md = data.get("market_data", {})
                    return {
                        "symbol": symbol,
                        "name": data.get("name"),
                        "price": md.get("current_price", {}).get("usd"),
                        "ath": md.get("ath", {}).get("usd"),
                        "ath_change_pct": md.get("ath_change_percentage", {}).get("usd"),
                        "atl": md.get("atl", {}).get("usd"),
                        "market_cap": md.get("market_cap", {}).get("usd"),
                        "market_cap_rank": data.get("market_cap_rank"),
                        "total_volume": md.get("total_volume", {}).get("usd"),
                        "high_24h": md.get("high_24h", {}).get("usd"),
                        "low_24h": md.get("low_24h", {}).get("usd"),
                        "change_24h": md.get("price_change_percentage_24h"),
                        "change_7d": md.get("price_change_percentage_7d"),
                        "change_30d": md.get("price_change_percentage_30d"),
                        "circulating_supply": md.get("circulating_supply"),
                        "total_supply": md.get("total_supply"),
                        "source": "coingecko",
                    }
        except Exception as e:
            return {"symbol": symbol, "error": str(e)[:100]}
        return {"symbol": symbol, "error": "unavailable"}

    # ── Private: Yahoo Finance (via web API) ─────────────────────────

    async def _yahoo_prices(self) -> dict[str, dict]:
        cached = self._get_cached("yahoo_prices")
        if cached:
            return cached

        result = {}
        symbols_str = ",".join(YAHOO_MAP.values())

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"https://query1.finance.yahoo.com/v7/finance/quote",
                    params={"symbols": symbols_str},
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    quotes = data.get("quoteResponse", {}).get("result", [])

                    yahoo_reverse = {v: k for k, v in YAHOO_MAP.items()}
                    for q in quotes:
                        yahoo_sym = q.get("symbol", "")
                        our_sym = yahoo_reverse.get(yahoo_sym)
                        if our_sym:
                            result[our_sym] = {
                                "symbol": our_sym,
                                "price": q.get("regularMarketPrice", 0),
                                "change_24h_pct": round(q.get("regularMarketChangePercent", 0), 2),
                                "volume_24h": q.get("regularMarketVolume", 0),
                                "high_today": q.get("regularMarketDayHigh", 0),
                                "low_today": q.get("regularMarketDayLow", 0),
                                "prev_close": q.get("regularMarketPreviousClose", 0),
                                "market_state": q.get("marketState", "unknown"),
                                "source": "yahoo",
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                            }
                    self._set_cached("yahoo_prices", result)
                    return result
        except Exception as e:
            logger.debug("yahoo.prices_error", error=str(e)[:100])

        return {}

    async def _yahoo_detail(self, symbol: str) -> dict[str, Any]:
        yahoo_sym = YAHOO_MAP.get(symbol)
        if not yahoo_sym:
            return {"error": f"unknown symbol: {symbol}"}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"https://query1.finance.yahoo.com/v7/finance/quote",
                    params={"symbols": yahoo_sym},
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if resp.status_code == 200:
                    quotes = resp.json().get("quoteResponse", {}).get("result", [])
                    if quotes:
                        q = quotes[0]
                        return {
                            "symbol": symbol,
                            "yahoo_symbol": yahoo_sym,
                            "name": q.get("shortName", symbol),
                            "price": q.get("regularMarketPrice"),
                            "change_pct": round(q.get("regularMarketChangePercent", 0), 2),
                            "change_abs": round(q.get("regularMarketChange", 0), 2),
                            "volume": q.get("regularMarketVolume"),
                            "high": q.get("regularMarketDayHigh"),
                            "low": q.get("regularMarketDayLow"),
                            "open": q.get("regularMarketOpen"),
                            "prev_close": q.get("regularMarketPreviousClose"),
                            "52w_high": q.get("fiftyTwoWeekHigh"),
                            "52w_low": q.get("fiftyTwoWeekLow"),
                            "50d_avg": q.get("fiftyDayAverage"),
                            "200d_avg": q.get("twoHundredDayAverage"),
                            "market_state": q.get("marketState"),
                            "source": "yahoo",
                        }
        except Exception as e:
            return {"symbol": symbol, "error": str(e)[:100]}
        return {"symbol": symbol, "error": "unavailable"}

    # ── Cache helpers ────────────────────────────────────────────────

    def _get_cached(self, key: str) -> Optional[Any]:
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < self._cache_ttl:
                return data
        return None

    def _set_cached(self, key: str, data: Any, ttl: int = 0) -> None:
        self._cache[key] = (time.time(), data)
        if ttl:
            self._cache_ttl = ttl  # Not perfect but simple


# Singleton
_market_data = MarketDataService()

def get_market_data_service() -> MarketDataService:
    return _market_data
