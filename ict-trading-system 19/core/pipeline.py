"""Main Pipeline — DB-first persistence + approval-aware execution.

Every MarketState, TradeSignal, ApprovedOrder, and TradeResult is persisted
to the database. If manual_approval_required=True, signals go to 'pending'
and must be approved via the API before execution proceeds.

JSON artifacts are secondary logging only.

Usage:
  python -m core.pipeline --mode shadow
  python -m core.pipeline --mode demo
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog
import yaml

from core.execution.client import TradeLockerClient
from core.execution.mapper import InstrumentMapper
from core.market_structure.engine import MarketStructureEngine
from core.market_structure.session import SessionDetector
from core.strategy.engine import StrategyEngine
from core.models import ApprovedOrder, Candle, MarketState, SessionName, TradeSignal
from core.risk.engine import RiskEngine

logger = structlog.get_logger(__name__)


class AccountTracker:
    """Tracks daily/weekly P&L and trade counts."""

    def __init__(self) -> None:
        self.peak_equity: float = 0.0
        self.session_start_equity: float = 0.0
        self.week_start_equity: float = 0.0
        self.trades_today: int = 0
        self.daily_pnl: float = 0.0
        self.weekly_pnl: float = 0.0
        self._last_reset_date: Optional[str] = None
        self._last_reset_week: Optional[str] = None

    def update(self, equity: float) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        week = datetime.now(timezone.utc).strftime("%Y-W%W")
        if self._last_reset_date != today:
            self.session_start_equity = equity
            self.trades_today = 0
            self.daily_pnl = 0.0
            self._last_reset_date = today
        if self._last_reset_week != week:
            self.week_start_equity = equity
            self.weekly_pnl = 0.0
            self._last_reset_week = week
        if equity > self.peak_equity:
            self.peak_equity = equity
        if self.session_start_equity > 0:
            self.daily_pnl = (equity - self.session_start_equity) / self.session_start_equity
        if self.week_start_equity > 0:
            self.weekly_pnl = (equity - self.week_start_equity) / self.week_start_equity

    def record_trade(self) -> None:
        self.trades_today += 1


class TradingPipeline:
    """Orchestrates the full trading pipeline with DB-first persistence."""

    def __init__(self, mode: str = "shadow", manual_approval: bool = True):
        assert mode in ("shadow", "demo", "live"), f"Invalid mode: {mode}"
        self.mode = mode
        self.manual_approval = manual_approval
        self.broker = TradeLockerClient()
        self.mapper = InstrumentMapper()
        self.risk = RiskEngine()
        self.session_detector = SessionDetector()
        self.market_engine = MarketStructureEngine()
        self.strategy_engine = StrategyEngine()
        self.tracker = AccountTracker()
        self.running = False
        self.account_id = "acct_demo_1"  # Primary account ID

        with open("config/broker.yaml") as f:
            broker_config = yaml.safe_load(f)
        self.symbols = [s["id"] for s in broker_config["instruments"]["symbols"]]

        self._candle_cache: dict[str, list[Candle]] = {}
        logger.info("pipeline.initialized", mode=mode, manual_approval=manual_approval,
                     symbols=self.symbols)

    async def start(self) -> None:
        logger.info("pipeline.starting", mode=self.mode)
        self.running = True
        await self.broker.connect()
        await self.mapper.load_from_broker(self.broker)
        await self._sync_account_state()
        self.market_engine.reset_session_state()
        self.strategy_engine.reset_daily_counts()

        try:
            while self.running:
                await self._tick()

                # Check for approved signals waiting for execution
                if self.mode != "shadow" and self.manual_approval:
                    await self._execute_approved_signals()

                await asyncio.sleep(5)
        except KeyboardInterrupt:
            logger.info("pipeline.interrupted")
        finally:
            await self.stop()

    async def stop(self) -> None:
        self.running = False
        await self.broker.disconnect()
        logger.info("pipeline.stopped")

    # ── Main Loop ─────────────────────────────────────────────────────

    async def _tick(self) -> None:
        try:
            utc_now = datetime.now(timezone.utc)
            if not self.session_detector.is_ny_active(utc_now):
                return
            if self.session_detector.is_weekend(utc_now):
                return

            await self._sync_account_state()

            # Expire stale pending signals
            await self._expire_stale_signals()

            for symbol in self.symbols:
                await self._process_symbol(symbol, utc_now)

        except Exception as e:
            logger.error("pipeline.tick_error", error=str(e), exc_info=True)

    async def _process_symbol(self, symbol: str, utc_now: datetime) -> None:
        try:
            instrument_id = self.mapper.get_instrument_id(symbol)
            if instrument_id is None:
                logger.warning("pipeline.no_instrument_id", symbol=symbol)
                return

            candles_1m = await self._fetch_candles(instrument_id, symbol, "1m")
            if len(candles_1m) < 30:
                return

            prior_day = await self._get_prior_day_candles(instrument_id, symbol)
            asia_candles = self._filter_session_candles(candles_1m, "asia", utc_now)
            pre_ny = self._filter_pre_ny_candles(candles_1m, utc_now)

            # Engine A: Market Structure
            market_state = self.market_engine.build_state(
                symbol=symbol, candles_1m=candles_1m,
                prior_day_candles=prior_day, asia_candles=asia_candles,
                pre_ny_candles=pre_ny,
                tick_size=self.mapper.get_tick_size(symbol), utc_now=utc_now,
            )

            # PERSIST market state to DB
            await self._persist_market_state(market_state, utc_now)

            # Engine B: Strategy Decision
            signals = self.strategy_engine.evaluate(market_state)
            if not signals:
                return

            # Engine C: Risk Gate + PERSIST signals
            tick_v = self.mapper.get_tick_value(symbol)
            tick_s = self.mapper.get_tick_size(symbol)
            session_active = self.session_detector.is_ny_active(utc_now)

            for signal in signals:
                order = self.risk.evaluate(
                    signal=signal, tick_value=tick_v, tick_size=tick_s,
                    min_lot=self.mapper.get_min_lot(symbol),
                    max_lot=self.mapper.get_max_lot(symbol),
                    session_active=session_active,
                )

                # PERSIST signal to DB (status depends on approval + risk)
                signal_id = await self._persist_signal(signal, order)

                # Log risk events
                if not order.approved and order.rejection_reason:
                    await self._persist_risk_event(
                        f"signal_rejected_{order.rejection_reason}",
                        "info",
                        f"Signal rejected: {order.rejection_detail}",
                    )

                # JSON artifact (secondary)
                self._log_signal_json(signal, order)

                # Immediate execution path (no manual approval)
                if order.approved and not self.manual_approval and self.mode != "shadow":
                    await self._execute_signal(
                        signal, order, instrument_id, signal_id
                    )

        except Exception as e:
            logger.error("pipeline.process_symbol_error", symbol=symbol, error=str(e))
            await self._create_incident(
                "Pipeline processing error",
                "pipeline_error", "high", "pipeline",
                f"Error processing {symbol}: {str(e)}",
            )

    # ── Approval-Aware Execution ──────────────────────────────────────

    async def _execute_approved_signals(self) -> None:
        """Check DB for approved signals and execute them."""
        try:
            from backend.db.session import AsyncSessionLocal
            from backend.services.pipeline_persistence import PipelinePersistence

            async with AsyncSessionLocal() as session:
                persistence = PipelinePersistence(session)

                for symbol in self.symbols:
                    approved = await persistence.get_approved_signals(symbol=symbol)
                    for sig_record in approved:
                        instrument_id = self.mapper.get_instrument_id(sig_record.symbol)
                        if instrument_id is None:
                            continue

                        await self._execute_from_db_signal(
                            sig_record, instrument_id, persistence
                        )

                await persistence.commit()

        except Exception as e:
            logger.error("pipeline.execute_approved_error", error=str(e))

    async def _execute_from_db_signal(
        self, sig_record, instrument_id: int, persistence
    ) -> None:
        """Execute a single approved signal from the database."""
        if self.mode == "shadow":
            return

        side = sig_record.side
        is_dry_run = self.mode != "live"

        # Persist order record before sending
        order_id = await persistence.persist_approved_order(
            signal_id=sig_record.id,
            account_id=self.account_id,
            order_dict={
                "symbol": sig_record.symbol,
                "direction": "long" if side == "buy" else "short",
                "entry_type": "limit",
                "entry_price": sig_record.entry_price,
                "stop_price": sig_record.stop_price,
                "targets": [{"price": sig_record.take_profit_1}] if sig_record.take_profit_1 else [],
                "position_size": 0.5,  # From risk engine sizing
                "risk_pct_actual": sig_record.risk_score or 0.0025,
                "instrument_id": instrument_id,
            },
        )

        result = await self.broker.place_order(
            instrument_id=instrument_id,
            side=side,
            quantity=0.5,
            stop_loss=sig_record.stop_price,
            take_profit=sig_record.take_profit_1,
            dry_run=is_dry_run,
        )

        # Mark signal as executed
        await persistence.mark_signal_executed(sig_record.id)

        # Persist trade result
        await persistence.persist_trade_result(
            order_id=order_id,
            account_id=self.account_id,
            result_dict={
                "symbol": sig_record.symbol,
                "strategy_name": sig_record.strategy_name,
                "status": "open",
                "entry_price": sig_record.entry_price,
                "stop_price": sig_record.stop_price,
                "take_profit": sig_record.take_profit_1,
                "quantity": 0.5,
                "opened_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        self.tracker.record_trade()
        self.strategy_engine.record_trade(sig_record.strategy_name)

        logger.info("pipeline.executed_approved_signal",
                     signal_id=sig_record.id, symbol=sig_record.symbol,
                     dry_run=is_dry_run)

    async def _execute_signal(
        self, signal: TradeSignal, order: ApprovedOrder,
        instrument_id: int, signal_id: str,
    ) -> None:
        """Direct execution path (when manual approval is off)."""
        if self.mode == "shadow":
            return

        try:
            from backend.db.session import AsyncSessionLocal
            from backend.services.pipeline_persistence import PipelinePersistence

            async with AsyncSessionLocal() as session:
                persistence = PipelinePersistence(session)

                order_id = await persistence.persist_approved_order(
                    signal_id=signal_id,
                    account_id=self.account_id,
                    order_dict=order.model_dump(mode="json"),
                )

                side = "buy" if order.direction == "long" else "sell"
                is_dry_run = self.mode != "live"

                result = await self.broker.place_order(
                    instrument_id=instrument_id,
                    side=side,
                    quantity=order.position_size,
                    stop_loss=order.stop_price,
                    take_profit=order.targets[0].price if order.targets else None,
                    dry_run=is_dry_run,
                )

                await persistence.mark_signal_executed(signal_id)
                await persistence.persist_trade_result(
                    order_id=order_id,
                    account_id=self.account_id,
                    result_dict={
                        "symbol": signal.symbol,
                        "strategy_name": signal.strategy_id,
                        "status": "open",
                        "entry_price": signal.entry_price,
                        "stop_price": signal.stop_price,
                        "quantity": order.position_size,
                        "opened_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                await persistence.commit()

        except Exception as e:
            logger.error("pipeline.execute_signal_error", error=str(e))

        self.tracker.record_trade()
        self.strategy_engine.record_trade(signal.strategy_id)
        logger.info("pipeline.order_result", symbol=signal.symbol,
                     dry_run=self.mode != "live")

    # ── DB Persistence Helpers ────────────────────────────────────────

    async def _persist_market_state(self, state: MarketState, utc_now: datetime) -> None:
        try:
            from backend.db.session import AsyncSessionLocal
            from backend.services.pipeline_persistence import PipelinePersistence

            async with AsyncSessionLocal() as session:
                persistence = PipelinePersistence(session)
                await persistence.persist_market_state(
                    symbol=state.symbol,
                    timestamp=utc_now,
                    session_name=state.session.value,
                    session_active=state.session.value in ("ny", "ny_killzone"),
                    market_state_dict=state.model_dump(mode="json"),
                )
                await persistence.commit()
        except Exception as e:
            logger.error("pipeline.persist_market_state_error", error=str(e))

    async def _persist_signal(
        self, signal: TradeSignal, order: ApprovedOrder
    ) -> str:
        """Persist signal to DB. Returns signal record ID."""
        try:
            from backend.db.session import AsyncSessionLocal
            from backend.services.pipeline_persistence import PipelinePersistence

            async with AsyncSessionLocal() as session:
                persistence = PipelinePersistence(session)
                signal_id = await persistence.persist_signal(
                    signal_dict=signal.model_dump(mode="json"),
                    risk_approved=order.approved,
                    risk_rejection_reason=order.rejection_reason,
                    manual_approval_required=self.manual_approval,
                )
                await persistence.commit()
                return signal_id
        except Exception as e:
            logger.error("pipeline.persist_signal_error", error=str(e))
            return ""

    async def _persist_risk_event(
        self, event_type: str, severity: str, message: str
    ) -> None:
        try:
            from backend.db.session import AsyncSessionLocal
            from backend.services.pipeline_persistence import PipelinePersistence

            async with AsyncSessionLocal() as session:
                persistence = PipelinePersistence(session)
                await persistence.persist_risk_event(
                    self.account_id, event_type, severity, message,
                )
                await persistence.commit()
        except Exception as e:
            logger.error("pipeline.persist_risk_event_error", error=str(e))

    async def _create_incident(
        self, title: str, category: str, severity: str, source: str, summary: str
    ) -> None:
        try:
            from backend.db.session import AsyncSessionLocal
            from backend.services.pipeline_persistence import PipelinePersistence

            async with AsyncSessionLocal() as session:
                persistence = PipelinePersistence(session)
                await persistence.create_incident(title, category, severity, source, summary)
                await persistence.commit()
        except Exception as e:
            logger.error("pipeline.create_incident_error", error=str(e))

    async def _expire_stale_signals(self) -> None:
        try:
            from backend.db.session import AsyncSessionLocal
            from backend.services.pipeline_persistence import PipelinePersistence

            async with AsyncSessionLocal() as session:
                persistence = PipelinePersistence(session)
                count = await persistence.expire_stale_signals()
                await persistence.commit()
                if count > 0:
                    logger.info("pipeline.signals_expired", count=count)
        except Exception as e:
            logger.error("pipeline.expire_signals_error", error=str(e))

    # ── Account Sync ──────────────────────────────────────────────────

    async def _sync_account_state(self) -> None:
        try:
            state = await self.broker.get_account_state()
            positions = await self.broker.get_positions()
            equity = float(state.get("equity", 0))
            self.tracker.update(equity)

            open_pos = []
            for p in positions:
                sym = str(p.get("instrumentId", ""))
                entry_px = float(p.get("avgPrice", 0))
                sl = float(p.get("stopLoss", 0))
                qty = float(p.get("qty", 0))
                if sl > 0 and entry_px > 0 and equity > 0:
                    risk_dist = abs(entry_px - sl)
                    tick_v = self.mapper.get_tick_value(sym)
                    tick_s = self.mapper.get_tick_size(sym)
                    ticks = risk_dist / tick_s if tick_s > 0 else 0
                    risk_pct = (ticks * tick_v * qty) / equity
                else:
                    risk_pct = 0.0025
                open_pos.append({"symbol": sym, "risk_pct": risk_pct, "direction": p.get("side", "")})

            dd_pct = max(0.0, (self.tracker.peak_equity - equity) / self.tracker.peak_equity) if self.tracker.peak_equity > 0 else 0.0

            self.risk.update_state(
                equity=equity, open_positions=open_pos,
                daily_pnl_pct=self.tracker.daily_pnl,
                weekly_pnl_pct=self.tracker.weekly_pnl,
                account_dd_pct=dd_pct, trades_today=self.tracker.trades_today,
            )

            # Persist account state to DB
            try:
                from backend.db.session import AsyncSessionLocal
                from backend.services.pipeline_persistence import PipelinePersistence
                async with AsyncSessionLocal() as session:
                    persistence = PipelinePersistence(session)
                    await persistence.update_account(
                        self.account_id,
                        balance=float(state.get("balance", 0)),
                        equity=equity,
                        margin_used=float(state.get("marginUsed", 0)),
                        free_margin=float(state.get("freeMargin", 0)),
                        drawdown_pct=round(dd_pct * 100, 2),
                        status="connected",
                        mode=self.mode,
                    )
                    await persistence.commit()
            except Exception:
                pass  # Account DB update is non-critical

        except Exception as e:
            logger.error("pipeline.sync_failed", error=str(e))

    # ── Candle Fetching ───────────────────────────────────────────────

    async def _fetch_candles(self, instrument_id: int, symbol: str, tf: str = "1m") -> list[Candle]:
        try:
            candles = await self.broker.get_candles(instrument_id, tf, count=500)
            self._candle_cache[f"{symbol}_{tf}"] = candles
            return candles
        except Exception as e:
            logger.error("pipeline.fetch_candles_error", symbol=symbol, error=str(e))
            return self._candle_cache.get(f"{symbol}_{tf}", [])

    async def _get_prior_day_candles(self, instrument_id: int, symbol: str) -> list[Candle]:
        try:
            candles_1h = await self.broker.get_candles(instrument_id, "1h", count=48)
            today = datetime.now(timezone.utc).date()
            return [c for c in candles_1h if c.timestamp.date() < today]
        except Exception:
            return []

    def _filter_session_candles(self, candles: list[Candle], session: str, utc_now: datetime) -> list[Candle]:
        try:
            start, end = self.session_detector.get_session_range_times(SessionName(session), utc_now)
            return [c for c in candles if start <= c.timestamp <= end]
        except Exception:
            return []

    def _filter_pre_ny_candles(self, candles: list[Candle], utc_now: datetime) -> list[Candle]:
        try:
            ny_start, _ = self.session_detector.get_session_range_times(SessionName.NY, utc_now)
            return [c for c in candles if c.timestamp < ny_start]
        except Exception:
            return []

    # ── JSON Artifact (secondary) ─────────────────────────────────────

    def _log_signal_json(self, signal: TradeSignal, order: ApprovedOrder) -> None:
        """Secondary JSON logging — DB is source of truth."""
        try:
            log_dir = Path("data/signals")
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = signal.timestamp.strftime("%Y%m%dT%H%M%S")
            record = {
                "signal": signal.model_dump(mode="json"),
                "risk_decision": order.model_dump(mode="json"),
                "pipeline_mode": self.mode,
            }
            with open(log_dir / f"signal_{signal.symbol}_{ts}.json", "w") as f:
                json.dump(record, f, indent=2, default=str)
        except Exception:
            pass  # JSON logging is non-critical


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="ICT Trading Pipeline")
    parser.add_argument("--mode", choices=["shadow", "demo", "live"], default="shadow")
    parser.add_argument("--no-manual-approval", action="store_true")
    args = parser.parse_args()

    structlog.configure(processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ])

    # Ensure DB tables exist
    from backend.db.session import create_tables_sync
    create_tables_sync()

    pipeline = TradingPipeline(
        mode=args.mode,
        manual_approval=not args.no_manual_approval,
    )
    asyncio.run(pipeline.start())


if __name__ == "__main__":
    main()
