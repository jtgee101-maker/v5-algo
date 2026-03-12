"""Instrument Mapper — resolves symbol names to TradeLocker instrument IDs.

Replaces the hardcoded instrument_id=0 in the pipeline.
Caches instrument metadata from the broker for fast lookups.
"""

from __future__ import annotations

from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


class InstrumentMapper:
    """Maps human-readable symbol names to broker instrument IDs and specs."""

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        self._loaded = False

    async def load_from_broker(self, broker_client: Any) -> None:
        """Fetch all instruments from broker and build lookup cache."""
        try:
            instruments = await broker_client.get_instruments()
            for inst in instruments:
                name = inst.get("name", "")
                self._cache[name] = {
                    "instrument_id": inst.get("tradableInstrumentId", 0),
                    "name": name,
                    "tick_size": float(inst.get("tickSize", 0.01)),
                    "tick_value": float(inst.get("tickValue", 1.0)),
                    "min_lot": float(inst.get("minQty", 0.01)),
                    "max_lot": float(inst.get("maxQty", 100.0)),
                    "lot_step": float(inst.get("lotStep", 0.01)),
                    "margin_rate": float(inst.get("marginRate", 0.01)),
                    "trading_status": inst.get("tradingStatus", "UNKNOWN"),
                    "raw": inst,
                }
            self._loaded = True
            logger.info("instrument_mapper.loaded", count=len(self._cache))
        except Exception as e:
            logger.error("instrument_mapper.load_failed", error=str(e))

    def load_from_config(self, symbol_map: dict[str, dict]) -> None:
        """Load from a manual config mapping (for testing/offline use)."""
        for symbol, specs in symbol_map.items():
            self._cache[symbol] = specs
        self._loaded = True

    def get_instrument_id(self, symbol: str) -> Optional[int]:
        """Get the broker instrument ID for a symbol."""
        entry = self._cache.get(symbol)
        if entry:
            return entry.get("instrument_id")
        # Try case-insensitive and partial match
        for name, data in self._cache.items():
            if symbol.lower() in name.lower() or name.lower() in symbol.lower():
                return data.get("instrument_id")
        logger.warning("instrument_mapper.not_found", symbol=symbol)
        return None

    def get_tick_size(self, symbol: str) -> float:
        """Get tick size for a symbol."""
        entry = self._cache.get(symbol, {})
        return float(entry.get("tick_size", 0.01))

    def get_tick_value(self, symbol: str) -> float:
        """Get tick value for a symbol."""
        entry = self._cache.get(symbol, {})
        return float(entry.get("tick_value", 1.0))

    def get_min_lot(self, symbol: str) -> float:
        """Get minimum lot size for a symbol."""
        entry = self._cache.get(symbol, {})
        return float(entry.get("min_lot", 0.01))

    def get_max_lot(self, symbol: str) -> float:
        """Get maximum lot size for a symbol."""
        entry = self._cache.get(symbol, {})
        return float(entry.get("max_lot", 100.0))

    def get_specs(self, symbol: str) -> dict[str, Any]:
        """Get all specs for a symbol."""
        return self._cache.get(symbol, {})

    def is_tradable(self, symbol: str) -> bool:
        """Check if instrument is currently tradable."""
        entry = self._cache.get(symbol, {})
        return entry.get("trading_status") == "TRADING"

    @property
    def symbols(self) -> list[str]:
        """List all known symbols."""
        return list(self._cache.keys())

    @property
    def loaded(self) -> bool:
        return self._loaded
