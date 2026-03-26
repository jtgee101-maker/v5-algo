"""Operator Feed Service — memory-aware signal feed.

Decides what belongs in the main operator feed vs history.
Collapses versions, suppresses noise, detects conflicts.

The operator feed is where capital deployment decisions begin.
It must be clean by construction, not by frontend filtering.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import TradeSignalRecord, SignalMemoryRecord
from backend.db.repositories.base import GenericRepository

import structlog
logger = structlog.get_logger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Feed config
STALE_HOURS = 24
CONFLICT_WINDOW_MINUTES = 120


class OperatorFeedService:
    """Produces a clean, memory-aware operator signal feed."""

    def __init__(self, session: AsyncSession):
        self.signal_repo = GenericRepository(session, TradeSignalRecord)
        self.memory_repo = GenericRepository(session, SignalMemoryRecord)
        self._session = session

    async def get_operator_feed(
        self,
        *,
        main_feed: bool = True,
        include_history: bool = False,
        include_superseded: bool = False,
        include_repeat_noise: bool = False,
        actionable_only: bool = False,
        candidates_only: bool = False,
        symbol: str = None,
        status: str = None,
        limit: int = 50,
    ) -> dict:
        """Get the memory-aware operator feed.

        Default: clean main feed only (latest versions, no noise, no superseded).
        Optional: include history, superseded, repeat noise for debugging.
        """
        # Fetch raw signals
        signals = await self.signal_repo.list_all(limit=min(limit * 3, 500))
        # Fetch all active memory records
        memories = await self._load_memory_index()

        # Enrich each signal with memory metadata
        enriched = []
        for sig in signals:
            enriched_sig = self._enrich_signal(sig, memories)

            # Apply filters
            if symbol and sig.symbol != symbol.upper():
                continue
            if status and sig.status != status:
                continue

            enriched.append(enriched_sig)

        # Detect conflicts across the feed
        self._detect_conflicts(enriched)

        # Apply feed rules
        if main_feed:
            feed = [s for s in enriched if s["show_in_main_feed"]]
            if not include_superseded:
                feed = [s for s in feed if not s["is_superseded"]]
            if not include_repeat_noise:
                feed = [s for s in feed if not s["repeat_noise"]]
        else:
            feed = enriched

        if actionable_only:
            feed = [s for s in feed if s.get("classification") == "actionable"]
        if candidates_only:
            feed = [s for s in feed if s.get("classification") == "candidate"]

        # Sort: review_priority desc, then score desc, then newest first
        feed.sort(key=lambda s: (
            s.get("review_priority", 0),
            s.get("score_total", 0),
        ), reverse=True)

        feed = feed[:limit]

        # Compute summary
        all_classifications = [s.get("classification", "unknown") for s in enriched]
        summary = {
            "total_signals": len(enriched),
            "main_feed_count": sum(1 for s in enriched if s["show_in_main_feed"]),
            "superseded_count": sum(1 for s in enriched if s["is_superseded"]),
            "repeat_noise_count": sum(1 for s in enriched if s["repeat_noise"]),
            "conflict_count": sum(1 for s in enriched if s.get("conflicting_duplicate")),
            "actionable_count": all_classifications.count("actionable"),
            "candidate_count": all_classifications.count("candidate"),
            "review_required_count": sum(1 for s in enriched if s.get("review_required")),
        }

        return {
            "signals": feed,
            "count": len(feed),
            "summary": summary,
            "filters_applied": {
                "main_feed": main_feed,
                "include_history": include_history,
                "include_superseded": include_superseded,
                "include_repeat_noise": include_repeat_noise,
                "actionable_only": actionable_only,
                "candidates_only": candidates_only,
                "symbol": symbol,
                "status": status,
            },
            "timestamp": _now(),
        }

    def _enrich_signal(self, sig: TradeSignalRecord, memories: dict) -> dict:
        """Enrich a signal record with memory-aware feed metadata."""
        # Parse json_payload for intelligence data
        payload = {}
        try:
            payload = json.loads(sig.json_payload) if sig.json_payload else {}
        except Exception:
            pass

        confluence_tags = []
        try:
            confluence_tags = json.loads(sig.confluence_tags) if sig.confluence_tags else []
        except Exception:
            pass

        memory_id = payload.get("memory_id")
        memory = memories.get(memory_id) if memory_id else None

        # Determine feed metadata
        is_current_version = True
        is_superseded = False
        show_in_main_feed = True
        repeat_noise = False
        review_required = payload.get("review_required", False)
        version_number = payload.get("version_number", 1)
        emit_count = 1
        classification = payload.get("classification", "unknown")
        score_total = payload.get("score_total", sig.confidence or 0)

        if memory:
            is_current_version = (memory.get("current_signal_id") == sig.id)
            is_superseded = memory.get("is_superseded", False) or not is_current_version
            version_number = memory.get("version_number", 1)
            emit_count = memory.get("emit_count", 1)
            classification = memory.get("classification") or classification
            score_total = memory.get("score_total") or score_total

            # Determine if repeat noise
            dup_status = memory.get("duplicate_status", "unique")
            if dup_status in ("exact_duplicate", "spam"):
                repeat_noise = True
            if emit_count >= 4 and not is_current_version:
                repeat_noise = True

            # Determine if should show in main feed
            if is_superseded:
                show_in_main_feed = False
            if repeat_noise:
                show_in_main_feed = False
            if classification in ("rejected", "invalid"):
                show_in_main_feed = False
            if not memory.get("is_active", True):
                show_in_main_feed = False

            review_required = (
                review_required
                or emit_count >= 3
                or dup_status == "near_duplicate"
            )

        # Staleness check
        is_stale = False
        try:
            if sig.timestamp:
                created = datetime.fromisoformat(sig.timestamp.replace("Z", "+00:00"))
                age_hours = (datetime.now(timezone.utc) - created).total_seconds() / 3600
                is_stale = age_hours > STALE_HOURS
                if is_stale:
                    show_in_main_feed = False
        except Exception:
            pass

        # Review priority scoring (higher = more urgent)
        review_priority = 0
        if classification == "actionable":
            review_priority = 90
        elif classification == "candidate":
            review_priority = 60
        elif classification == "low_confidence":
            review_priority = 30
        if review_required:
            review_priority += 5
        if is_stale:
            review_priority -= 20

        # Materially updated check
        materially_updated = (
            version_number > 1
            and is_current_version
            and not repeat_noise
        )

        return {
            # Signal core data
            "id": sig.id,
            "symbol": sig.symbol,
            "side": sig.side,
            "strategy_name": sig.strategy_name,
            "entry_price": sig.entry_price,
            "stop_price": sig.stop_price,
            "take_profit_1": sig.take_profit_1,
            "confidence": sig.confidence,
            "risk_score": sig.risk_score,
            "structure_score": sig.structure_score,
            "status": sig.status,
            "timestamp": sig.timestamp,
            "approved_by": sig.approved_by,
            "approved_at": sig.approved_at,
            "rejected_by": sig.rejected_by,
            "rejected_at": sig.rejected_at,
            "rejection_reason": sig.rejection_reason,
            "confluence_tags": confluence_tags,
            # Intelligence data
            "classification": classification,
            "score_total": score_total,
            "why_tradable": payload.get("why_tradable", []),
            "why_not_tradable": payload.get("why_not_tradable", []),
            # Memory-aware feed fields
            "memory_id": memory_id,
            "version_number": version_number,
            "is_current_version": is_current_version,
            "is_superseded": is_superseded,
            "show_in_main_feed": show_in_main_feed,
            "repeat_noise": repeat_noise,
            "materially_updated": materially_updated,
            "review_required": review_required,
            "review_priority": review_priority,
            "emit_count": emit_count,
            "is_stale": is_stale,
            "first_seen_at": memory.get("first_seen_at") if memory else sig.timestamp,
            "last_seen_at": memory.get("last_seen_at") if memory else sig.timestamp,
            # Conflict (set by _detect_conflicts)
            "conflicting_duplicate": False,
            "conflict_reason": None,
            "conflict_group_id": None,
        }

    def _detect_conflicts(self, enriched: list[dict]) -> None:
        """Detect conflicting duplicates in the feed.

        Conflict = same symbol + overlapping time window + opposing direction.
        """
        # Group active signals by symbol
        by_symbol: dict[str, list[dict]] = {}
        for sig in enriched:
            if sig.get("is_stale") or sig.get("status") in ("rejected", "expired"):
                continue
            sym = sig.get("symbol", "")
            by_symbol.setdefault(sym, []).append(sig)

        for sym, sigs in by_symbol.items():
            if len(sigs) < 2:
                continue

            # Check for opposing directions within time window
            for i, s1 in enumerate(sigs):
                for s2 in sigs[i + 1:]:
                    side1 = (s1.get("side") or "").lower()
                    side2 = (s2.get("side") or "").lower()

                    # Opposing directions?
                    opposing = (
                        (side1 in ("buy", "long") and side2 in ("sell", "short"))
                        or (side1 in ("sell", "short") and side2 in ("buy", "long"))
                    )

                    if not opposing:
                        continue

                    # Within time window?
                    try:
                        t1 = datetime.fromisoformat((s1.get("timestamp") or "").replace("Z", "+00:00"))
                        t2 = datetime.fromisoformat((s2.get("timestamp") or "").replace("Z", "+00:00"))
                        gap = abs((t2 - t1).total_seconds()) / 60
                    except Exception:
                        gap = 0

                    if gap <= CONFLICT_WINDOW_MINUTES:
                        conflict_id = f"conflict_{sym}_{min(s1['id'], s2['id'])}"
                        reason = f"Opposing {side1}/{side2} signals for {sym} within {int(gap)}min"

                        s1["conflicting_duplicate"] = True
                        s1["conflict_reason"] = reason
                        s1["conflict_group_id"] = conflict_id
                        s1["review_required"] = True
                        s1["review_priority"] = max(s1.get("review_priority", 0), 95)

                        s2["conflicting_duplicate"] = True
                        s2["conflict_reason"] = reason
                        s2["conflict_group_id"] = conflict_id
                        s2["review_required"] = True
                        s2["review_priority"] = max(s2.get("review_priority", 0), 95)

    async def _load_memory_index(self) -> dict[str, dict]:
        """Load all memory records into a lookup dict."""
        try:
            records = await self.memory_repo.list_all(limit=500)
            index = {}
            for r in records:
                score_snap = {}
                try:
                    score_snap = json.loads(r.score_snapshot) if r.score_snapshot else {}
                except Exception:
                    pass

                index[r.id] = {
                    "memory_id": r.id,
                    "signal_fingerprint": r.signal_fingerprint,
                    "symbol": r.symbol,
                    "direction": r.direction,
                    "classification": r.classification,
                    "score_total": r.score_total,
                    "first_seen_at": r.first_seen_at,
                    "last_seen_at": r.last_seen_at,
                    "emit_count": r.emit_count or 1,
                    "suppress_count": r.suppress_count or 0,
                    "duplicate_status": r.duplicate_status,
                    "current_signal_id": r.current_signal_id,
                    "version_number": r.version_number or 1,
                    "memory_status": r.memory_status,
                    "is_active": bool(r.is_active),
                    "is_superseded": bool(r.is_superseded),
                }
            return index
        except Exception:
            return {}
