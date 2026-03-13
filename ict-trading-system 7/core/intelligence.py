"""Market intelligence — aggregates external data for trading decisions.

Integrates patterns from:
- nirholas/free-crypto-news: Free sentiment API, no key required
- yorkeccak/finance: Multi-source data aggregation
- virattt/dexter: Scratchpad logging for reasoning audit trail
- degentic-tools/claude-code-trading-terminal: Data pipeline normalization

Provides:
1. Crypto news sentiment (free, real-time)
2. Market fear/greed context
3. Scratchpad — JSONL reasoning log for every scan (Dexter pattern)
4. Multi-source price validation
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

# ── Free Crypto News API (no key required) ───────────────────────────
# Source: https://github.com/nirholas/free-crypto-news
NEWS_API_BASE = "https://cryptocurrency.cv/api"


class NewsService:
    """Free crypto news and sentiment — from nirholas/free-crypto-news.

    All endpoints are free, no API key required.
    Rate limit: be respectful, ~1 req/min per endpoint.
    """

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl = 120  # 2 min cache

    async def get_latest_news(self, limit: int = 10) -> list[dict]:
        """Get latest crypto news articles."""
        return await self._cached_get(f"/news?limit={limit}", f"news_{limit}")

    async def get_bitcoin_news(self, limit: int = 5) -> list[dict]:
        """Bitcoin-specific news."""
        return await self._cached_get(f"/news/bitcoin?limit={limit}", f"btc_news_{limit}")

    async def get_sentiment(self, topic: str = "Bitcoin") -> dict:
        """Get sentiment analysis for a topic.

        Returns: {articles: [...], overall_sentiment: "bullish"|"bearish"|"neutral"}
        """
        return await self._cached_get(
            f"/analyze?topic={topic}&limit=10", f"sentiment_{topic}"
        )

    async def get_breaking(self, limit: int = 5) -> list[dict]:
        """Get breaking crypto news."""
        return await self._cached_get(f"/news/breaking?limit={limit}", "breaking")

    async def get_market_context(self) -> dict[str, Any]:
        """Aggregate market context from multiple free sources.

        Pattern from yorkeccak/finance: multi-source aggregation.
        Returns combined sentiment + news summary for trading decisions.
        """
        context = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "btc_sentiment": "neutral",
            "news_count": 0,
            "breaking_count": 0,
            "top_headlines": [],
            "sentiment_score": 0.0,  # -1 (bearish) to +1 (bullish)
            "source": "free-crypto-news",
        }

        try:
            sentiment = await self.get_sentiment("Bitcoin")
            if isinstance(sentiment, dict):
                context["btc_sentiment"] = sentiment.get("overall_sentiment", "neutral")
                articles = sentiment.get("articles", [])
                context["news_count"] = len(articles)
                context["top_headlines"] = [
                    {"title": a.get("title", ""), "source": a.get("source", "")}
                    for a in articles[:5]
                ]
                # Convert to numeric score
                s = context["btc_sentiment"].lower()
                if "bullish" in s:
                    context["sentiment_score"] = 0.6
                elif "bearish" in s:
                    context["sentiment_score"] = -0.6
        except Exception as e:
            context["error"] = str(e)[:100]

        try:
            breaking = await self.get_breaking(3)
            if isinstance(breaking, list):
                context["breaking_count"] = len(breaking)
                for b in breaking[:3]:
                    context["top_headlines"].append({
                        "title": b.get("title", ""), "source": "BREAKING"
                    })
        except Exception:
            pass

        return context

    async def _cached_get(self, path: str, cache_key: str) -> Any:
        """GET with simple TTL cache."""
        now = time.time()
        if cache_key in self._cache:
            ts, data = self._cache[cache_key]
            if now - ts < self._cache_ttl:
                return data

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(f"{NEWS_API_BASE}{path}")
                if resp.status_code == 200:
                    data = resp.json()
                    self._cache[cache_key] = (now, data)
                    return data if isinstance(data, (list, dict)) else []
        except Exception as e:
            logger.debug("news_service.fetch_failed", path=path, error=str(e)[:100])

        # Return cached stale data if available
        if cache_key in self._cache:
            return self._cache[cache_key][1]
        return []


# ── Scratchpad — Dexter-style reasoning audit trail ──────────────────
# Source: https://github.com/virattt/dexter (scratchpad pattern)

class Scratchpad:
    """JSONL reasoning log for every scan cycle.

    From virattt/dexter: every tool call, every decision, every result
    gets logged to a timestamped JSONL file. This provides:
    - Proof of why trades were taken
    - Audit trail for review
    - Data for strategy improvement
    - Debugging breadcrumbs

    Each scan creates entries like:
    {"type":"scan_start", "timestamp":"...", "pairs":["BTCUSD"]}
    {"type":"candle_fetch", "symbol":"BTCUSD", "bars":200, "source":"tradelocker"}
    {"type":"market_structure", "symbol":"BTCUSD", "bias":"bullish", "fvg_count":3}
    {"type":"signal_generated", "symbol":"BTCUSD", "strategy":"ny_sweep_reversal", ...}
    {"type":"news_sentiment", "btc_sentiment":"bullish", "score":0.6}
    {"type":"safety_check", "circuit_breaker":"ok", "cooldown":"ok"}
    {"type":"scan_complete", "duration_ms":1200, "signals":1}
    """

    def __init__(self, base_dir: str = "data/scratchpad"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._current_file: Optional[Path] = None
        self._entries: list[dict] = []

    def start_session(self) -> str:
        """Start a new scratchpad session. Returns session ID."""
        now = datetime.now(timezone.utc)
        session_id = now.strftime("%Y%m%d_%H%M%S")
        self._current_file = self.base_dir / f"{session_id}.jsonl"
        self._entries = []
        self.log("session_start", timestamp=now.isoformat())
        return session_id

    def log(self, event_type: str, **data: Any) -> None:
        """Log a reasoning step."""
        entry = {
            "type": event_type,
            "ts": datetime.now(timezone.utc).isoformat(),
            **data,
        }
        self._entries.append(entry)

        # Write to file
        if self._current_file:
            try:
                with open(self._current_file, "a") as f:
                    f.write(json.dumps(entry) + "\n")
            except Exception:
                pass  # Non-critical

    def get_entries(self) -> list[dict]:
        """Get all entries for current session."""
        return self._entries

    def get_recent_sessions(self, count: int = 10) -> list[dict]:
        """List recent scratchpad sessions."""
        sessions = []
        try:
            files = sorted(self.base_dir.glob("*.jsonl"), reverse=True)[:count]
            for f in files:
                try:
                    lines = f.read_text().strip().split("\n")
                    first = json.loads(lines[0]) if lines else {}
                    last = json.loads(lines[-1]) if lines else {}
                    sessions.append({
                        "session_id": f.stem,
                        "entries": len(lines),
                        "started": first.get("ts"),
                        "ended": last.get("ts"),
                        "file": str(f),
                    })
                except Exception:
                    pass
        except Exception:
            pass
        return sessions

    def get_session_log(self, session_id: str) -> list[dict]:
        """Read a specific session's log."""
        path = self.base_dir / f"{session_id}.jsonl"
        if not path.exists():
            return []
        try:
            entries = []
            for line in path.read_text().strip().split("\n"):
                if line:
                    entries.append(json.loads(line))
            return entries
        except Exception:
            return []


# ── Multi-Source Price Validation ─────────────────────────────────────
# Pattern from degentic-tools/claude-code-trading-terminal: data pipeline

class PriceValidator:
    """Cross-reference prices from multiple sources.

    From claude-code-trading-terminal: never trust a single data source.
    Fetches from CoinGecko (free) to validate TradeLocker prices.
    """

    COINGECKO_IDS = {
        "BTCUSD": "bitcoin",
        "ETHUSD": "ethereum",
        "XRPUSD": "ripple",
        "LTCUSD": "litecoin",
        "ADAUSD": "cardano",
        "DOGEUSD": "dogecoin",
    }

    async def get_reference_price(self, symbol: str) -> Optional[float]:
        """Get reference price from CoinGecko (free, no key)."""
        coin_id = self.COINGECKO_IDS.get(symbol)
        if not coin_id:
            return None

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://api.coingecko.com/api/v3/simple/price",
                    params={"ids": coin_id, "vs_currencies": "usd"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get(coin_id, {}).get("usd")
        except Exception:
            return None

    def validate_price(
        self, symbol: str, broker_price: float, reference_price: float,
        max_deviation_pct: float = 2.0,
    ) -> dict[str, Any]:
        """Check if broker price deviates too much from reference."""
        if reference_price <= 0:
            return {"valid": True, "reason": "no_reference"}

        deviation = abs(broker_price - reference_price) / reference_price * 100

        return {
            "valid": deviation <= max_deviation_pct,
            "broker_price": broker_price,
            "reference_price": reference_price,
            "deviation_pct": round(deviation, 3),
            "max_allowed_pct": max_deviation_pct,
        }


# ── Singleton instances ──────────────────────────────────────────────

_news_service = NewsService()
_scratchpad = Scratchpad()
_price_validator = PriceValidator()


def get_news_service() -> NewsService:
    return _news_service

def get_scratchpad() -> Scratchpad:
    return _scratchpad

def get_price_validator() -> PriceValidator:
    return _price_validator
