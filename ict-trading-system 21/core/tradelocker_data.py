"""TradeLocker data service — uses official tradelocker Python client.

Provides reliable candle data, live positions, and account state.
Fixes the 404 candle issue by using the official SDK which handles
routeId and endpoint paths correctly.

Symbols: BTCUSD, NAS100, US30, EURUSD, XAUUSD (Gold), USOIL (Oil)
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

# Symbol mapping — TradeLocker instrument names may differ from our standard names
# These get resolved dynamically via the instruments endpoint
SYMBOLS = ["BTCUSD", "NAS100", "US30", "EURUSD", "XAUUSD", "USOIL"]

# Common alternative names on TradeLocker/GatesFX
SYMBOL_ALIASES = {
    "NAS100": ["NAS100", "USTEC", "NDX100", "NASDAQ", "NAS100.R"],
    "US30": ["US30", "DJ30", "DJI30", "DOWJONES", "US30.R"],
    "XAUUSD": ["XAUUSD", "GOLD", "XAUUSD.R"],
    "USOIL": ["USOIL", "USOIL.R", "WTI", "CRUDEOIL", "CL", "CRUDE"],
    "BTCUSD": ["BTCUSD", "BTC/USD"],
    "EURUSD": ["EURUSD", "EUR/USD"],
}


class TradeLockerData:
    """Reliable data from TradeLocker using the official Python client."""

    def __init__(self):
        self._tl = None
        self._instruments_cache: dict[str, Any] = {}
        self._cache_ts: float = 0

    def _get_client(self):
        """Get or create the TradeLocker client."""
        if self._tl is None:
            try:
                from tradelocker import TLAPI
                self._tl = TLAPI(
                    environment=os.environ.get("TRADELOCKER_BASE_URL", "https://demo.tradelocker.com"),
                    username=os.environ.get("TRADELOCKER_EMAIL", ""),
                    password=os.environ.get("TRADELOCKER_PASSWORD", ""),
                    server=os.environ.get("TRADELOCKER_SERVER", ""),
                )
                logger.info("tradelocker_data.connected")
            except Exception as e:
                logger.error("tradelocker_data.connect_failed", error=str(e))
                return None
        return self._tl

    def get_all_instruments(self) -> dict:
        """Get all available instruments with caching."""
        now = time.time()
        if self._instruments_cache and now - self._cache_ts < 3600:  # 1hr cache
            return self._instruments_cache

        tl = self._get_client()
        if not tl:
            return {}

        try:
            instruments = tl.get_all_instruments()
            if instruments is not None:
                self._instruments_cache = instruments
                self._cache_ts = now
            return instruments if instruments is not None else {}
        except Exception as e:
            logger.error("tradelocker_data.instruments_error", error=str(e))
            return {}

    def resolve_instrument_id(self, symbol: str) -> Optional[int]:
        """Resolve our symbol name to TradeLocker instrument ID."""
        tl = self._get_client()
        if not tl:
            return None

        # Try exact match first
        try:
            inst_id = tl.get_instrument_id_from_symbol_name(symbol)
            if inst_id:
                return int(inst_id)
        except Exception:
            pass

        # Try aliases
        for alias in SYMBOL_ALIASES.get(symbol, []):
            try:
                inst_id = tl.get_instrument_id_from_symbol_name(alias)
                if inst_id:
                    return int(inst_id)
            except Exception:
                continue

        return None

    def get_candles(self, symbol: str, resolution: str = "1h", lookback: str = "7D") -> dict[str, Any]:
        """Get candle data using official client.

        Args:
            symbol: Our symbol name (e.g., "USOIL")
            resolution: "1m", "5m", "15m", "1h", "4h", "1D"
            lookback: "1D", "5D", "1M", "3M"

        Returns: {symbol, resolution, candles: [{t, o, h, l, c, v}], count}
        """
        tl = self._get_client()
        if not tl:
            return {"symbol": symbol, "error": "broker not connected"}

        inst_id = self.resolve_instrument_id(symbol)
        if not inst_id:
            return {"symbol": symbol, "error": f"instrument not found (tried {SYMBOL_ALIASES.get(symbol, [symbol])})"}

        try:
            history = tl.get_price_history(
                instrument_id=inst_id,
                resolution=resolution,
                start_timestamp=0,
                end_timestamp=0,
                lookback_period=lookback,
            )

            if history is None or (hasattr(history, 'empty') and history.empty):
                return {"symbol": symbol, "error": "no candle data returned"}

            # Convert DataFrame to list of dicts
            candles = []
            if hasattr(history, 'iterrows'):
                for _, row in history.iterrows():
                    candles.append({
                        "t": str(row.get("t", row.name)) if hasattr(row, 'get') else str(row.name),
                        "o": float(row.get("o", row.iloc[0]) if hasattr(row, 'get') else row.iloc[0]),
                        "h": float(row.get("h", row.iloc[1]) if hasattr(row, 'get') else row.iloc[1]),
                        "l": float(row.get("l", row.iloc[2]) if hasattr(row, 'get') else row.iloc[2]),
                        "c": float(row.get("c", row.iloc[3]) if hasattr(row, 'get') else row.iloc[3]),
                        "v": float(row.get("v", 0) if hasattr(row, 'get') else 0),
                    })
            elif isinstance(history, dict):
                candles = [history]

            latest = candles[-1] if candles else {}

            return {
                "symbol": symbol,
                "resolution": resolution,
                "lookback": lookback,
                "count": len(candles),
                "latest": latest,
                "candles": candles,
            }

        except Exception as e:
            return {"symbol": symbol, "error": str(e)[:200]}

    def get_latest_price(self, symbol: str) -> Optional[float]:
        """Get latest asking price for a symbol."""
        tl = self._get_client()
        if not tl:
            return None

        inst_id = self.resolve_instrument_id(symbol)
        if not inst_id:
            return None

        try:
            return tl.get_latest_asking_price(inst_id)
        except Exception:
            return None

    def get_positions(self) -> list[dict[str, Any]]:
        """Get all open positions from TradeLocker."""
        tl = self._get_client()
        if not tl:
            return []

        try:
            positions = tl.get_all_positions()
            if positions is None or (hasattr(positions, 'empty') and positions.empty):
                return []

            result = []
            if hasattr(positions, 'iterrows'):
                for _, row in positions.iterrows():
                    pos = {}
                    for col in positions.columns:
                        val = row[col]
                        pos[col] = float(val) if isinstance(val, (int, float)) else str(val)
                    result.append(pos)
            return result
        except Exception as e:
            logger.error("tradelocker_data.positions_error", error=str(e))
            return []

    def get_account_details(self) -> dict[str, Any]:
        """Get account balance, equity, margin from TradeLocker."""
        tl = self._get_client()
        if not tl:
            return {"error": "not connected"}

        try:
            # The official client may have different methods
            # Try common approaches
            details = {}

            # Try getting account state through the internal API
            if hasattr(tl, 'get_account_details'):
                details = tl.get_account_details()
            elif hasattr(tl, '_session'):
                # Fallback to raw API
                pass

            return details if details else {"error": "method not available"}
        except Exception as e:
            return {"error": str(e)[:200]}


# Singleton
_tl_data = TradeLockerData()

def get_tradelocker_data() -> TradeLockerData:
    return _tl_data
