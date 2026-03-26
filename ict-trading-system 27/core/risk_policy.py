"""RiskPolicyEngine — mandatory evaluation gate for every execution attempt.

NO trade reaches the broker without passing through this engine.
Every decision is auditable with config snapshot + reasoning.

Phases covered:
  Phase 2: RiskPolicyEngine with blocker/warning system
  Phase 3: Execution gate (evaluate_and_gate)
  Phase 4: Symbol validation
  Phase 6: Circuit breaker lifecycle hardening
  Phase 8: Audit trail for every decision
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


class RiskDecision:
    """Immutable result of a risk evaluation. Every field is auditable."""

    def __init__(
        self,
        approved: bool,
        adjusted_risk_pct: Optional[float],
        blockers: list[str],
        warnings: list[str],
        safety_state: dict,
        config_snapshot: dict,
        config_hash: str,
        portfolio_snapshot: dict,
        request_snapshot: dict,
        timestamp: str,
    ):
        self.approved = approved
        self.adjusted_risk_pct = adjusted_risk_pct
        self.blockers = blockers
        self.warnings = warnings
        self.safety_state = safety_state
        self.config_snapshot = config_snapshot
        self.config_hash = config_hash
        self.portfolio_snapshot = portfolio_snapshot
        self.request_snapshot = request_snapshot
        self.timestamp = timestamp

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "adjusted_risk_pct": self.adjusted_risk_pct,
            "blockers": self.blockers,
            "warnings": self.warnings,
            "safety_state": self.safety_state,
            "config_hash": self.config_hash,
            "portfolio_snapshot": self.portfolio_snapshot,
            "request_snapshot": self.request_snapshot,
            "timestamp": self.timestamp,
        }


class RiskPolicyEngine:
    """Evaluates every proposed trade against runtime config and safety state.

    This is the single enforcement point. Nothing reaches the broker
    without an approved RiskDecision from this engine.
    """

    def __init__(self):
        self._audit_log: list[dict] = []

    def evaluate(
        self,
        *,
        # Trade request
        symbol: str,
        direction: str,  # "long" / "short"
        strategy: str = "manual",
        proposed_entry: float = 0,
        stop_loss_distance: float = 0,
        proposed_risk_pct: float = 0,
        # Account state
        account_equity: float = 0,
        account_balance: float = 0,
        daily_pnl: float = 0,
        weekly_pnl: float = 0,
        account_drawdown_pct: float = 0,
        open_positions: list[dict] | None = None,
        # Runtime config (from ConfigService.get_config())
        runtime_config: dict | None = None,
        # Safety state
        circuit_breaker_status: dict | None = None,
        cooldown_status: dict | None = None,
        # Optional context
        atr: float = 0,
        session_active: bool = True,
        news_sentiment: str = "",
        source: str = "unknown",
    ) -> RiskDecision:
        """Evaluate a proposed trade. Returns approved/blocked with full reasoning."""

        now = datetime.now(timezone.utc)
        blockers: list[str] = []
        warnings: list[str] = []
        adjusted_risk = proposed_risk_pct

        # ── Load config or fail safe ────────────────────────────
        if runtime_config is None:
            blockers.append("CRITICAL: Runtime config unavailable — safe failure mode")
            runtime_config = {}

        config_json = json.dumps(runtime_config, sort_keys=True, default=str)
        config_hash = hashlib.sha256(config_json.encode()).hexdigest()[:16]

        # Extract config values with safe defaults
        allowed_symbols = runtime_config.get("allowed_symbols", [])
        risk_cfg = runtime_config.get("risk", {})
        kill_switch = runtime_config.get("kill_switch", {})
        mode = runtime_config.get("mode", "shadow")
        max_positions = risk_cfg.get("max_positions", 10)
        risk_per_trade = risk_cfg.get("risk_per_trade_pct", 0.25) / 100  # Convert from pct
        max_daily_loss = risk_cfg.get("max_daily_loss_pct", 1.5) / 100
        max_weekly_loss = risk_cfg.get("max_weekly_loss_pct", 4.0) / 100
        max_drawdown = risk_cfg.get("max_account_drawdown_pct", 18.0) / 100

        positions = open_positions or []

        # ══════════════════════════════════════════════════════════
        # MANDATORY BLOCKER CHECKS (any one = trade rejected)
        # ══════════════════════════════════════════════════════════

        # 1. Kill switch
        if kill_switch.get("active", False):
            blockers.append(f"Kill switch active: {kill_switch.get('reason', 'no reason')}")

        # 2. Circuit breaker
        cb = circuit_breaker_status or {}
        if cb.get("tripped", False):
            blockers.append(f"Circuit breaker tripped: {cb.get('consecutive_losses', 0)} consecutive losses")

        # 3. Symbol not allowed
        if allowed_symbols and symbol.upper() not in [s.upper() for s in allowed_symbols]:
            blockers.append(f"Symbol {symbol} not in allowed list: {allowed_symbols}")

        # 4. Max positions exceeded
        if len(positions) >= max_positions:
            blockers.append(f"Max positions ({max_positions}) reached. Currently: {len(positions)}")

        # 5. Daily loss breached
        if account_equity > 0 and daily_pnl < 0:
            daily_loss_pct = abs(daily_pnl) / account_equity
            if daily_loss_pct >= max_daily_loss:
                blockers.append(
                    f"Daily loss limit breached: {daily_loss_pct:.2%} >= {max_daily_loss:.2%} "
                    f"(${abs(daily_pnl):.2f} lost today)"
                )

        # 6. Weekly loss breached
        if account_equity > 0 and weekly_pnl < 0:
            weekly_loss_pct = abs(weekly_pnl) / account_equity
            if weekly_loss_pct >= max_weekly_loss:
                blockers.append(
                    f"Weekly loss limit breached: {weekly_loss_pct:.2%} >= {max_weekly_loss:.2%}"
                )

        # 7. Account drawdown breached
        if account_drawdown_pct > 0 and account_drawdown_pct / 100 >= max_drawdown:
            blockers.append(
                f"Account drawdown breached: {account_drawdown_pct:.1f}% >= {max_drawdown:.0%}"
            )

        # 8. Mode restriction
        if mode == "shadow":
            warnings.append("Mode is SHADOW — trade will be simulated only, not executed")
        elif mode == "demo":
            warnings.append("Mode is DEMO — executing on demo account")

        # 9. Cooldown
        if cooldown_status:
            active = cooldown_status.get("active_cooldowns", {})
            if symbol in active:
                remaining = active[symbol].get("remaining_seconds", 0)
                if remaining > 0:
                    blockers.append(f"Trade cooldown: {symbol} in {remaining}s cooldown")

        # ══════════════════════════════════════════════════════════
        # WARNING / ADJUSTMENT CHECKS
        # ══════════════════════════════════════════════════════════

        # Risk percentage cap
        if proposed_risk_pct > 0:
            max_risk_pct = risk_per_trade * 100  # Back to percentage for comparison
            if proposed_risk_pct > max_risk_pct:
                adjusted_risk = max_risk_pct
                warnings.append(
                    f"Risk adjusted: {proposed_risk_pct:.2f}% → {max_risk_pct:.2f}% (config limit)"
                )

        # ATR elevated
        if atr > 0 and proposed_entry > 0:
            atr_pct = atr / proposed_entry
            if atr_pct > 0.05:  # >5% of price
                warnings.append(f"EXTREME volatility: ATR is {atr_pct:.1%} of price")
            elif atr_pct > 0.02:
                warnings.append(f"HIGH volatility: ATR is {atr_pct:.1%} of price")

        # Session mismatch
        if not session_active:
            warnings.append(f"Market session closed for {symbol}")

        # Correlated exposure
        same_symbol_positions = [p for p in positions if symbol.upper() in str(p).upper()]
        if len(same_symbol_positions) >= 2:
            warnings.append(
                f"Correlated exposure: already {len(same_symbol_positions)} positions on {symbol}"
            )

        # ══════════════════════════════════════════════════════════
        # BUILD DECISION
        # ══════════════════════════════════════════════════════════

        approved = len(blockers) == 0
        safety_state = {
            "kill_switch_active": kill_switch.get("active", False),
            "circuit_breaker_tripped": cb.get("tripped", False),
            "mode": mode,
            "open_position_count": len(positions),
            "daily_pnl": daily_pnl,
            "weekly_pnl": weekly_pnl,
            "drawdown_pct": account_drawdown_pct,
        }

        decision = RiskDecision(
            approved=approved,
            adjusted_risk_pct=adjusted_risk if adjusted_risk != proposed_risk_pct else None,
            blockers=blockers,
            warnings=warnings,
            safety_state=safety_state,
            config_snapshot=runtime_config,
            config_hash=config_hash,
            portfolio_snapshot={
                "equity": account_equity,
                "balance": account_balance,
                "open_positions": len(positions),
                "daily_pnl": daily_pnl,
            },
            request_snapshot={
                "symbol": symbol,
                "direction": direction,
                "strategy": strategy,
                "proposed_entry": proposed_entry,
                "proposed_risk_pct": proposed_risk_pct,
                "source": source,
            },
            timestamp=now.isoformat(),
        )

        # Audit log
        audit_entry = {
            "timestamp": now.isoformat(),
            "result": "approved" if approved else "blocked",
            "symbol": symbol,
            "direction": direction,
            "strategy": strategy,
            "source": source,
            "mode": mode,
            "blockers": blockers,
            "warnings": warnings,
            "config_hash": config_hash,
            "equity": account_equity,
        }
        self._audit_log.append(audit_entry)

        # Keep last 500 entries
        if len(self._audit_log) > 500:
            self._audit_log = self._audit_log[-500:]

        log_fn = logger.warning if not approved else logger.info
        log_fn(
            "risk_policy.decision",
            approved=approved,
            symbol=symbol,
            direction=direction,
            blockers=len(blockers),
            warnings=len(warnings),
            config_hash=config_hash,
        )

        return decision

    def get_audit_log(self, limit: int = 50) -> list[dict]:
        """Return recent risk decisions for audit."""
        return list(reversed(self._audit_log[-limit:]))

    def validate_symbol(self, symbol: str, allowed_symbols: list[str]) -> tuple[bool, str]:
        """Phase 4: Symbol validation. Used by all execution paths."""
        if not allowed_symbols:
            return True, ""
        if symbol.upper() in [s.upper() for s in allowed_symbols]:
            return True, ""
        return False, f"Symbol {symbol} not in allowed list: {', '.join(allowed_symbols)}"


# ── Enhanced Circuit Breaker with full lifecycle ──────────────────

class HardenedCircuitBreaker:
    """Phase 6: Circuit breaker with full lifecycle metadata.

    Extends base CircuitBreaker with:
    - trip_reason, trip_source
    - reset_reason, reset_source, reset_at
    - cooldown_until
    - scope (global/symbol/strategy)
    - refuses reset if kill switch active (unless forced)
    """

    def __init__(self, max_consecutive_losses: int = 3, cooldown_minutes: int = 30):
        self.max_consecutive_losses = max_consecutive_losses
        self.cooldown_minutes = cooldown_minutes
        self.consecutive_losses = 0
        self.tripped = False
        self.total_trips = 0

        # Lifecycle metadata
        self.tripped_at: Optional[str] = None
        self.trip_reason: str = ""
        self.trip_source: str = ""
        self.reset_at: Optional[str] = None
        self.reset_reason: str = ""
        self.reset_source: str = ""
        self.cooldown_until: Optional[str] = None
        self.scope: str = "global"

        self._trip_timestamp: float = 0  # For cooldown math

    def record_trade(self, pnl: float, symbol: str = "", strategy: str = "") -> dict:
        """Record trade result. Returns event info if breaker trips."""
        event = None
        if pnl < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.max_consecutive_losses and not self.tripped:
                self.tripped = True
                self._trip_timestamp = time.time()
                now = datetime.now(timezone.utc)
                self.tripped_at = now.isoformat()
                self.trip_reason = f"{self.consecutive_losses} consecutive losses"
                self.trip_source = f"trade_on_{symbol or 'unknown'}"
                cooldown_end = datetime.fromtimestamp(
                    self._trip_timestamp + self.cooldown_minutes * 60, tz=timezone.utc
                )
                self.cooldown_until = cooldown_end.isoformat()
                self.total_trips += 1
                event = {
                    "type": "circuit_breaker_tripped",
                    "timestamp": self.tripped_at,
                    "reason": self.trip_reason,
                    "source": self.trip_source,
                    "cooldown_until": self.cooldown_until,
                }
                logger.warning("circuit_breaker.tripped", **event)
        else:
            self.consecutive_losses = 0
        return event or {}

    def is_blocked(self) -> tuple[bool, str]:
        if not self.tripped:
            return False, ""

        elapsed = time.time() - self._trip_timestamp
        remaining = (self.cooldown_minutes * 60) - elapsed

        if remaining <= 0:
            self._do_reset("cooldown_expired", "system")
            return False, ""

        return True, (
            f"Circuit breaker: {self.consecutive_losses} consecutive losses. "
            f"Resumes in {int(remaining / 60)}m {int(remaining % 60)}s"
        )

    def force_reset(
        self,
        reason: str = "manual_reset",
        source: str = "operator",
        kill_switch_active: bool = False,
        force_override: bool = False,
    ) -> dict:
        """Reset breaker. Refuses if kill switch active unless force_override."""
        if kill_switch_active and not force_override:
            return {
                "success": False,
                "reason": "Cannot reset: kill switch is active. Use force_override=true.",
            }

        self._do_reset(reason, source)
        return {
            "success": True,
            "reason": reason,
            "source": source,
            "reset_at": self.reset_at,
        }

    def _do_reset(self, reason: str, source: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.tripped = False
        self._trip_timestamp = 0
        self.consecutive_losses = 0
        self.reset_at = now
        self.reset_reason = reason
        self.reset_source = source
        self.cooldown_until = None
        logger.info("circuit_breaker.reset", reason=reason, source=source)

    def status(self) -> dict[str, Any]:
        remaining_seconds = 0
        if self.tripped and self._trip_timestamp > 0:
            elapsed = time.time() - self._trip_timestamp
            remaining_seconds = max(0, int(self.cooldown_minutes * 60 - elapsed))

        return {
            "tripped": self.tripped,
            "consecutive_losses": self.consecutive_losses,
            "max_consecutive_losses": self.max_consecutive_losses,
            "cooldown_minutes": self.cooldown_minutes,
            "remaining_seconds": remaining_seconds,
            "total_trips": self.total_trips,
            "scope": self.scope,
            # Lifecycle metadata
            "tripped_at": self.tripped_at,
            "trip_reason": self.trip_reason,
            "trip_source": self.trip_source,
            "cooldown_until": self.cooldown_until,
            "reset_at": self.reset_at,
            "reset_reason": self.reset_reason,
            "reset_source": self.reset_source,
        }


# ── Execution Gate ────────────────────────────────────────────────

class ExecutionGate:
    """Phase 3: No trade reaches broker without passing through this gate.

    Flow: request → RiskPolicyEngine evaluation → audit → broker submit/block
    """

    def __init__(self, risk_engine: RiskPolicyEngine):
        self.risk_engine = risk_engine
        self._execution_log: list[dict] = []

    async def evaluate_and_gate(
        self,
        *,
        symbol: str,
        direction: str,
        strategy: str = "manual",
        proposed_entry: float = 0,
        stop_loss_distance: float = 0,
        proposed_risk_pct: float = 0,
        runtime_config: dict | None = None,
        circuit_breaker: HardenedCircuitBreaker | None = None,
        cooldown_status: dict | None = None,
        account_equity: float = 0,
        account_balance: float = 0,
        daily_pnl: float = 0,
        weekly_pnl: float = 0,
        account_drawdown_pct: float = 0,
        open_positions: list[dict] | None = None,
        atr: float = 0,
        session_active: bool = True,
        source: str = "unknown",
    ) -> dict:
        """Evaluate and gate a trade execution attempt.

        Returns: { approved, decision, execution_id, ... }
        If approved and mode is live/demo: ready for broker submission.
        If blocked: full reasoning why.
        """

        now = datetime.now(timezone.utc)
        execution_id = f"exec_{now.strftime('%Y%m%d_%H%M%S')}_{symbol}"

        # Run risk evaluation
        decision = self.risk_engine.evaluate(
            symbol=symbol,
            direction=direction,
            strategy=strategy,
            proposed_entry=proposed_entry,
            stop_loss_distance=stop_loss_distance,
            proposed_risk_pct=proposed_risk_pct,
            runtime_config=runtime_config,
            circuit_breaker_status=circuit_breaker.status() if circuit_breaker else None,
            cooldown_status=cooldown_status,
            account_equity=account_equity,
            account_balance=account_balance,
            daily_pnl=daily_pnl,
            weekly_pnl=weekly_pnl,
            account_drawdown_pct=account_drawdown_pct,
            open_positions=open_positions,
            atr=atr,
            session_active=session_active,
            source=source,
        )

        # Determine execution result
        if decision.approved:
            mode = (runtime_config or {}).get("mode", "shadow")
            if mode == "shadow":
                result = "simulated"
            elif mode in ("demo", "live"):
                result = "ready_for_broker"
            else:
                result = "unknown_mode"
        else:
            result = "blocked"

        # Build audit record
        audit = {
            "execution_id": execution_id,
            "timestamp": now.isoformat(),
            "symbol": symbol,
            "direction": direction,
            "strategy": strategy,
            "source": source,
            "mode": (runtime_config or {}).get("mode", "shadow"),
            "result": result,
            "approved": decision.approved,
            "blockers": decision.blockers,
            "warnings": decision.warnings,
            "config_hash": decision.config_hash,
            "equity": account_equity,
            "daily_pnl": daily_pnl,
            "proposed_risk_pct": proposed_risk_pct,
            "adjusted_risk_pct": decision.adjusted_risk_pct,
        }

        self._execution_log.append(audit)
        if len(self._execution_log) > 1000:
            self._execution_log = self._execution_log[-1000:]

        logger.info(
            "execution_gate.decision",
            execution_id=execution_id,
            result=result,
            approved=decision.approved,
            blockers=len(decision.blockers),
        )

        return {
            "execution_id": execution_id,
            "approved": decision.approved,
            "result": result,
            "decision": decision.to_dict(),
            "audit": audit,
        }

    def get_execution_log(self, limit: int = 50) -> list[dict]:
        return list(reversed(self._execution_log[-limit:]))


# ── Singletons ────────────────────────────────────────────────────

_risk_engine = RiskPolicyEngine()
_circuit_breaker = HardenedCircuitBreaker()
_execution_gate = ExecutionGate(_risk_engine)


def get_risk_engine() -> RiskPolicyEngine:
    return _risk_engine

def get_hardened_breaker() -> HardenedCircuitBreaker:
    return _circuit_breaker

def get_execution_gate() -> ExecutionGate:
    return _execution_gate
