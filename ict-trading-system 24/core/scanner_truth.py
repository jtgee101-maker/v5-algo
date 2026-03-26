"""Scanner Truth Engine — market-data truth, scan lifecycle, debounce.

Ensures:
- Every symbol classified: live | fallback | synthetic | unavailable
- Scan runs tracked: started, completed, success/failure, live count
- Repeated scans debounced via cooldown window
- Last successful scan never overwritten by failures
"""

from __future__ import annotations

import time as _time
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


class DataSourceClassifier:
    """Classifies how each symbol's data was obtained."""

    LIVE_SOURCES = {"tradelocker", "tradelocker-raw"}
    FALLBACK_SOURCES = {"coingecko", "yahoo", "free"}

    @staticmethod
    def classify_symbol(symbol, source, candle_count=0, has_error=False):
        src = (source or "").lower()
        if has_error or src in ("none", "", "error"):
            status = "unavailable"
        elif src in DataSourceClassifier.LIVE_SOURCES:
            status = "live"
        elif src in DataSourceClassifier.FALLBACK_SOURCES:
            status = "fallback"
        elif src == "synthetic":
            status = "synthetic"
        else:
            status = "fallback"

        valid = status in ("live", "fallback") and candle_count > 0 and not has_error
        reason = None
        if not valid:
            if has_error: reason = "Data fetch error"
            elif candle_count == 0: reason = "No candle data"
            elif status == "synthetic": reason = "Synthetic data only"
            elif status == "unavailable": reason = "Source unavailable"

        return {
            "symbol": symbol, "data_source": source, "source_status": status,
            "candles_count": candle_count, "market_data_valid": valid,
            "market_data_reason": reason,
        }

    @staticmethod
    def classify_scan(symbol_results):
        live = sum(1 for s in symbol_results if s["source_status"] == "live")
        fallback = sum(1 for s in symbol_results if s["source_status"] == "fallback")
        synthetic = sum(1 for s in symbol_results if s["source_status"] == "synthetic")
        unavail = sum(1 for s in symbol_results if s["source_status"] == "unavailable")
        total = len(symbol_results)

        all_synth = (synthetic + unavail) == total and total > 0
        any_live = live > 0

        if live == total: scan_status = "live"
        elif live > 0: scan_status = "partial_live"
        elif fallback > 0: scan_status = "fallback_only"
        else: scan_status = "unavailable"

        return {
            "live_symbols_count": live, "fallback_symbols_count": fallback,
            "synthetic_symbols_count": synthetic, "unavailable_symbols_count": unavail,
            "total_symbols": total, "all_synthetic": all_synth,
            "any_live": any_live, "scan_status": scan_status,
        }


class ScanRunManager:
    """Tracks scan lifecycle with debounce and last-successful truth."""

    SCAN_COOLDOWN_SECONDS = 30
    SCAN_REUSE_WINDOW_SECONDS = 60

    def __init__(self):
        self._runs = []
        self._last_successful = None
        self._last_live_data = None
        self._last_attempted = None
        self._running = False

    def can_scan(self):
        """Returns (can_scan, reuse_or_cooldown_info)."""
        now = _time.time()
        if self._running:
            return False, {"reused_recent_scan": False, "cooldown_reason": "Scan in progress"}

        if self._last_attempted:
            elapsed = now - self._last_attempted.get("_epoch", 0)
            if elapsed < self.SCAN_COOLDOWN_SECONDS:
                if self._last_successful:
                    age = now - self._last_successful.get("_epoch", 0)
                    if age < self.SCAN_REUSE_WINDOW_SECONDS:
                        return False, {
                            "reused_recent_scan": True,
                            "reused_scan_id": self._last_successful.get("scan_id"),
                            "reused_age_seconds": round(age, 1),
                            "cooldown_reason": f"Reusing scan ({age:.0f}s old)",
                        }
                return False, {
                    "reused_recent_scan": False,
                    "cooldown_reason": f"Cooldown: {self.SCAN_COOLDOWN_SECONDS - elapsed:.0f}s remaining",
                }
        return True, None

    def start_scan(self, scan_id):
        now = datetime.now(timezone.utc)
        run = {
            "scan_id": scan_id, "started_at": now.isoformat(),
            "completed_at": None, "success": False,
            "scan_status": "running", "live_symbols_count": 0,
            "any_live": False, "error_summary": None,
            "signals_generated": 0, "duplicates_suppressed": 0,
            "_epoch": _time.time(),
        }
        self._running = True
        self._last_attempted = run
        self._runs.append(run)
        if len(self._runs) > 100:
            self._runs = self._runs[-100:]
        return run

    def complete_scan(self, scan_id, success, scan_truth, signals_gen=0, dupes_suppressed=0, error=None):
        now = datetime.now(timezone.utc)
        run = next((r for r in reversed(self._runs) if r["scan_id"] == scan_id), self._last_attempted or {})
        run.update({
            "completed_at": now.isoformat(), "success": success,
            "scan_status": scan_truth.get("scan_status", "unknown"),
            "live_symbols_count": scan_truth.get("live_symbols_count", 0),
            "any_live": scan_truth.get("any_live", False),
            "signals_generated": signals_gen, "duplicates_suppressed": dupes_suppressed,
            "error_summary": error, "_epoch": _time.time(),
        })
        self._running = False
        if success:
            self._last_successful = {k: v for k, v in run.items() if not k.startswith("_")}
            self._last_successful["_epoch"] = run["_epoch"]
            if scan_truth.get("any_live"):
                self._last_live_data = self._last_successful.copy()
        return run

    def get_last_scan_info(self):
        def _clean(r):
            return {k: v for k, v in r.items() if not k.startswith("_")} if r else None
        return {
            "last_attempted": _clean(self._last_attempted),
            "last_successful": _clean(self._last_successful),
            "last_live_data": _clean(self._last_live_data),
            "scan_running": self._running,
            "total_runs": len(self._runs),
        }


_classifier = DataSourceClassifier()
_scan_manager = ScanRunManager()

def get_data_classifier(): return _classifier
def get_scan_manager(): return _scan_manager
