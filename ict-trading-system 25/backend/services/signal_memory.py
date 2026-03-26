"""Durable Signal Memory — persists dedup + versioning across restarts.

Replaces in-memory dedup with DB-backed memory that survives deploys.
Every unique setup fingerprint gets one memory record.
Repeated emissions update the record instead of creating duplicates.

Memory states: active → superseded / invalidated / expired / archived
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import SignalMemoryRecord
from backend.db.repositories.base import GenericRepository

import structlog
logger = structlog.get_logger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Fingerprint config
PRICE_ROUND_PCT = 0.001
VALIDITY_WINDOW_MINUTES = 120  # Same setup within 2 hours = same memory record
SPAM_THRESHOLD = 5             # 5+ emissions in window = spam


class DurableSignalMemory:
    """DB-backed signal memory. Source of truth for dedup decisions."""

    def __init__(self, session: AsyncSession):
        self.repo = GenericRepository(session, SignalMemoryRecord)
        self._session = session

    # ── Fingerprint ───────────────────────────────────────────

    @staticmethod
    def compute_fingerprint(
        symbol: str, direction: str, strategy: str,
        entry: float, stop_loss: float, take_profit: float,
    ) -> tuple[str, dict]:
        """Compute fingerprint + rounded levels."""
        def _round(price: float) -> float:
            if price <= 0:
                return 0
            bucket = max(price * PRICE_ROUND_PCT, 0.01)
            return round(round(price / bucket) * bucket, 6)

        r_entry = _round(entry)
        r_stop = _round(stop_loss)
        r_tp = _round(take_profit)

        raw = f"{symbol.upper()}|{direction.lower()}|{strategy.lower()}|{r_entry}|{r_stop}|{r_tp}"
        fp = hashlib.md5(raw.encode()).hexdigest()[:16]

        return fp, {"rounded_entry": r_entry, "rounded_stop": r_stop, "rounded_tp": r_tp}

    # ── Core dedup check ──────────────────────────────────────

    async def check_and_record(
        self,
        *,
        symbol: str,
        direction: str,
        strategy: str,
        source: str,
        entry: float,
        stop_loss: float,
        take_profit: float,
        classification: str = "unknown",
        score_total: float = 0,
        score_components: dict = None,
        scan_id: str = "",
    ) -> dict:
        """Check for duplicates in durable memory, record or update.

        Returns: {
            duplicate_detected, duplicate_type, memory_id, action_taken,
            emit_count, version_number, existing_signal_id, is_new
        }
        """
        now = _now()
        now_dt = datetime.now(timezone.utc)
        fp, rounded = self.compute_fingerprint(symbol, direction, strategy, entry, stop_loss, take_profit)

        # Look up existing memory record by fingerprint
        existing = await self._find_by_fingerprint(fp)

        if existing:
            # Check if within validity window
            try:
                last_seen_dt = datetime.fromisoformat(existing.last_seen_at.replace("Z", "+00:00"))
                age = (now_dt - last_seen_dt).total_seconds()
            except Exception:
                age = 99999

            within_window = age < (VALIDITY_WINDOW_MINUTES * 60)

            if within_window:
                # Same setup, within window — this is a duplicate
                new_emit_count = (existing.emit_count or 0) + 1
                new_suppress_count = existing.suppress_count or 0

                if new_emit_count >= SPAM_THRESHOLD:
                    # Spam — suppress
                    dup_type = "spam"
                    action = "suppressed"
                    new_suppress_count += 1
                elif new_emit_count >= 2:
                    # Near duplicate — version/update
                    dup_type = "near_duplicate" if new_emit_count <= 3 else "exact_duplicate"
                    action = "versioned"
                else:
                    dup_type = "exact_duplicate"
                    action = "updated"

                # Update existing record
                await self.repo.update_by_id(
                    existing.id,
                    last_seen_at=now,
                    last_emitted_scan_id=scan_id,
                    emit_count=new_emit_count,
                    suppress_count=new_suppress_count,
                    duplicate_status=dup_type,
                    classification=classification if classification != "unknown" else existing.classification,
                    score_total=score_total if score_total > 0 else existing.score_total,
                    score_snapshot=json.dumps(score_components) if score_components else existing.score_snapshot,
                    updated_at=now,
                )

                return {
                    "duplicate_detected": True,
                    "duplicate_type": dup_type,
                    "memory_id": existing.id,
                    "action_taken": action,
                    "emit_count": new_emit_count,
                    "suppress_count": new_suppress_count,
                    "version_number": existing.version_number or 1,
                    "existing_signal_id": existing.current_signal_id,
                    "fingerprint": fp,
                    "is_new": False,
                    "first_seen_at": existing.first_seen_at,
                    "last_seen_at": now,
                    "age_seconds": round(age, 1),
                }

            else:
                # Same fingerprint but outside window — new cycle
                # Supersede old record, create new version
                await self.repo.update_by_id(
                    existing.id,
                    memory_status="superseded",
                    is_active=0,
                    is_superseded=1,
                    updated_at=now,
                )

                # Create new memory record as next version
                new_version = (existing.version_number or 1) + 1
                new_record = await self.repo.create(
                    signal_fingerprint=fp,
                    symbol=symbol.upper(),
                    direction=direction.lower(),
                    strategy=strategy,
                    source=source,
                    rounded_entry=rounded["rounded_entry"],
                    rounded_stop=rounded["rounded_stop"],
                    rounded_tp=rounded["rounded_tp"],
                    classification=classification,
                    score_total=score_total,
                    score_snapshot=json.dumps(score_components) if score_components else None,
                    first_seen_at=now,
                    last_seen_at=now,
                    last_emitted_scan_id=scan_id,
                    emit_count=1,
                    suppress_count=0,
                    duplicate_status="unique",
                    parent_memory_id=existing.id,
                    version_number=new_version,
                    memory_status="active",
                    is_active=1,
                    is_superseded=0,
                    created_at=now,
                    updated_at=now,
                )

                return {
                    "duplicate_detected": False,
                    "duplicate_type": None,
                    "memory_id": new_record.id,
                    "action_taken": "new_version",
                    "emit_count": 1,
                    "suppress_count": 0,
                    "version_number": new_version,
                    "existing_signal_id": None,
                    "fingerprint": fp,
                    "is_new": True,
                    "parent_memory_id": existing.id,
                    "first_seen_at": now,
                    "last_seen_at": now,
                    "age_seconds": 0,
                }

        else:
            # Brand new setup — no prior memory
            new_record = await self.repo.create(
                signal_fingerprint=fp,
                symbol=symbol.upper(),
                direction=direction.lower(),
                strategy=strategy,
                source=source,
                rounded_entry=rounded["rounded_entry"],
                rounded_stop=rounded["rounded_stop"],
                rounded_tp=rounded["rounded_tp"],
                classification=classification,
                score_total=score_total,
                score_snapshot=json.dumps(score_components) if score_components else None,
                first_seen_at=now,
                last_seen_at=now,
                last_emitted_scan_id=scan_id,
                emit_count=1,
                suppress_count=0,
                duplicate_status="unique",
                version_number=1,
                memory_status="active",
                is_active=1,
                is_superseded=0,
                created_at=now,
                updated_at=now,
            )

            return {
                "duplicate_detected": False,
                "duplicate_type": None,
                "memory_id": new_record.id,
                "action_taken": "created",
                "emit_count": 1,
                "suppress_count": 0,
                "version_number": 1,
                "existing_signal_id": None,
                "fingerprint": fp,
                "is_new": True,
                "first_seen_at": now,
                "last_seen_at": now,
                "age_seconds": 0,
            }

    # ── Link signal to memory ─────────────────────────────────

    async def link_signal(self, memory_id: str, signal_id: str) -> None:
        """Link a created signal entity to its memory record."""
        try:
            await self.repo.update_by_id(memory_id, current_signal_id=signal_id, updated_at=_now())
        except Exception:
            pass

    # ── Queries ───────────────────────────────────────────────

    async def get_memory(self, memory_id: str) -> Optional[dict]:
        """Get one memory record."""
        r = await self.repo.get_by_id(memory_id)
        return self._to_dict(r) if r else None

    async def get_active_memories(self, symbol: str = None, limit: int = 50) -> list[dict]:
        """Get active memory records, optionally filtered by symbol."""
        try:
            records = await self.repo.list_all(limit=limit)
            results = []
            for r in records:
                if not r.is_active:
                    continue
                if symbol and r.symbol != symbol.upper():
                    continue
                results.append(self._to_dict(r))
            return results
        except Exception:
            return []

    async def get_version_history(self, memory_id: str) -> list[dict]:
        """Get version lineage for a memory record."""
        try:
            record = await self.repo.get_by_id(memory_id)
            if not record:
                return []

            history = [self._to_dict(record)]

            # Walk parent chain
            parent_id = record.parent_memory_id
            visited = {memory_id}
            while parent_id and parent_id not in visited:
                visited.add(parent_id)
                parent = await self.repo.get_by_id(parent_id)
                if parent:
                    history.append(self._to_dict(parent))
                    parent_id = parent.parent_memory_id
                else:
                    break

            history.reverse()  # oldest first
            return history
        except Exception:
            return []

    async def get_metrics(self) -> dict:
        """Get signal memory health metrics."""
        try:
            all_records = await self.repo.list_all(limit=1000)
            active = [r for r in all_records if r.is_active]
            superseded = [r for r in all_records if r.is_superseded]

            total_emits = sum(r.emit_count or 0 for r in all_records)
            total_suppressed = sum(r.suppress_count or 0 for r in all_records)

            by_symbol = {}
            for r in active:
                sym = r.symbol or "UNKNOWN"
                if sym not in by_symbol:
                    by_symbol[sym] = {"count": 0, "emits": 0, "suppressed": 0}
                by_symbol[sym]["count"] += 1
                by_symbol[sym]["emits"] += r.emit_count or 0
                by_symbol[sym]["suppressed"] += r.suppress_count or 0

            by_status = {}
            for r in all_records:
                s = r.duplicate_status or "unknown"
                by_status[s] = by_status.get(s, 0) + 1

            return {
                "total_memory_records": len(all_records),
                "active_records": len(active),
                "superseded_records": len(superseded),
                "total_emissions": total_emits,
                "total_suppressions": total_suppressed,
                "suppression_rate": round(total_suppressed / max(total_emits, 1), 4),
                "avg_emit_count": round(total_emits / max(len(all_records), 1), 2),
                "by_symbol": by_symbol,
                "by_duplicate_status": by_status,
                "durable": True,
            }
        except Exception:
            return {"total_memory_records": 0, "durable": False, "error": "memory query failed"}

    async def expire_stale(self, max_age_hours: int = 24) -> int:
        """Expire memory records older than max_age_hours."""
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
            all_records = await self.repo.list_all(limit=1000)
            expired = 0
            for r in all_records:
                if r.is_active and r.last_seen_at and r.last_seen_at < cutoff:
                    await self.repo.update_by_id(
                        r.id, memory_status="expired", is_active=0, updated_at=_now()
                    )
                    expired += 1
            return expired
        except Exception:
            return 0

    # ── Internal ──────────────────────────────────────────────

    async def _find_by_fingerprint(self, fp: str) -> Optional[SignalMemoryRecord]:
        """Find the most recent active memory record for a fingerprint."""
        try:
            records = await self.repo.list_all(limit=100)
            matches = [
                r for r in records
                if r.signal_fingerprint == fp and r.is_active
            ]
            if matches:
                # Return most recent
                matches.sort(key=lambda r: r.last_seen_at or "", reverse=True)
                return matches[0]
            return None
        except Exception:
            return None

    def _to_dict(self, r: SignalMemoryRecord) -> dict:
        score_snap = {}
        try:
            score_snap = json.loads(r.score_snapshot) if r.score_snapshot else {}
        except Exception:
            pass

        return {
            "memory_id": r.id,
            "signal_fingerprint": r.signal_fingerprint,
            "symbol": r.symbol,
            "direction": r.direction,
            "strategy": r.strategy,
            "source": r.source,
            "rounded_entry": r.rounded_entry,
            "rounded_stop": r.rounded_stop,
            "rounded_tp": r.rounded_tp,
            "classification": r.classification,
            "score_total": r.score_total,
            "score_components": score_snap,
            "first_seen_at": r.first_seen_at,
            "last_seen_at": r.last_seen_at,
            "last_emitted_scan_id": r.last_emitted_scan_id,
            "emit_count": r.emit_count,
            "suppress_count": r.suppress_count,
            "duplicate_status": r.duplicate_status,
            "current_signal_id": r.current_signal_id,
            "parent_memory_id": r.parent_memory_id,
            "version_number": r.version_number,
            "memory_status": r.memory_status,
            "is_active": bool(r.is_active),
            "is_superseded": bool(r.is_superseded),
            "invalidated_reason": r.invalidated_reason,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
            "durable": True,
        }
