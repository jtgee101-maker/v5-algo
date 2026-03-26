"""Bootstrap demo data — seeds the database with realistic test records.

Creates: 1 account, 5 market states, 6 signals (various statuses),
3 trades, 2 risk events, 1 incident, 2 journal entries, 2 agent runs.

Usage:
  python scripts/bootstrap_demo_data.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

from backend.db.session import create_tables_sync, sync_engine
from backend.db.base import Base
from backend.db.models import (
    Account, AgentRunRecord, ConfigChangeRecord, IncidentRecord,
    JournalEntryRecord, MarketStateRecord, RiskEventRecord,
    TradeSignalRecord, ApprovedOrderRecord, TradeResultRecord,
)

from sqlalchemy.orm import Session


def seed():
    create_tables_sync()

    now = datetime.now(timezone.utc)

    with Session(sync_engine) as session:
        # ── Account ──────────────────────────────────────────────
        acct = Account(
            id="acct_demo_1",
            broker_name="gatesfx",
            account_name="Demo 5000",
            account_type="demo",
            mode="shadow",
            balance=5000.0,
            equity=5042.50,
            margin_used=120.0,
            free_margin=4922.50,
            drawdown_pct=1.8,
            status="connected",
            currency="USD",
            updated_at=now.isoformat(),
        )
        session.merge(acct)

        # ── Market States ────────────────────────────────────────
        for i, sym in enumerate(["NAS100", "US30", "EURUSD", "BTCUSD", "NAS100"]):
            ts = (now - timedelta(minutes=5 * i)).isoformat()
            session.merge(MarketStateRecord(
                id=f"ms_{i+1}",
                symbol=sym,
                timestamp=ts,
                session_name="ny_killzone" if i < 3 else "ny",
                session_active=1,
                overnight_range_high=18450.5 + i * 10,
                overnight_range_low=18320.2 + i * 5,
                prior_day_high=18490.0,
                prior_day_low=18280.0,
                asia_high=18390.1,
                asia_low=18335.0,
                weekly_high=18520.0,
                weekly_low=18140.0,
                psych_level_nearest=18400.0,
                smt_flag=1 if i < 2 else 0,
                po3_phase="manipulated" if i == 0 else "idle",
                sweep_detected=1 if i < 2 else 0,
                displacement_detected=1 if i == 0 else 0,
                bias="bullish" if i % 2 == 0 else "bearish",
                structure_score=0.78 - i * 0.05,
                json_payload="{}",
            ))

        # ── Signals ──────────────────────────────────────────────
        signal_data = [
            ("sig_1", "NAS100", "ny_sweep_reversal", "v1", "buy", 0.78, 18245.5, 18210.0, 18290.0, 18340.0, "pending"),
            ("sig_2", "EURUSD", "ny_sweep_reversal", "v1", "buy", 0.74, 1.0875, 1.0864, 1.0890, 1.0905, "pending"),
            ("sig_3", "US30", "ny_sweep_reversal", "v1", "sell", 0.82, 38950.0, 38985.0, 38900.0, 38850.0, "approved"),
            ("sig_4", "NAS100", "ny_sweep_reversal", "v1", "buy", 0.71, 18402.0, 18386.0, 18436.0, None, "executed"),
            ("sig_5", "BTCUSD", "ny_sweep_reversal", "v1", "sell", 0.65, 67500.0, 67800.0, 67100.0, None, "rejected"),
            ("sig_6", "EURUSD", "ny_sweep_reversal", "v1", "buy", 0.68, 1.0830, 1.0818, 1.0845, None, "expired"),
        ]
        for sid, sym, strat, ver, side, conf, entry, stop, tp1, tp2, status in signal_data:
            ts = (now - timedelta(minutes=30 + signal_data.index((sid, sym, strat, ver, side, conf, entry, stop, tp1, tp2, status)) * 15)).isoformat()
            session.merge(TradeSignalRecord(
                id=sid, symbol=sym, strategy_name=strat, strategy_version=ver,
                timestamp=ts, side=side, confidence=conf,
                expected_value=round(conf * 0.3, 3),
                entry_price=entry, stop_price=stop,
                take_profit_1=tp1, take_profit_2=tp2,
                risk_score=0.12, structure_score=conf - 0.05,
                confluence_tags=json.dumps(["pdh_sweep", "smt_bullish"]),
                status=status,
                expires_at=(now + timedelta(minutes=15)).isoformat() if status == "pending" else None,
                approved_by="operator@local" if status in ("approved", "executed") else None,
                approved_at=ts if status in ("approved", "executed") else None,
                rejected_by="operator@local" if status == "rejected" else None,
                rejected_at=ts if status == "rejected" else None,
                rejection_reason="Below confidence threshold" if status == "rejected" else None,
                json_payload="{}",
            ))

        # ── Approved Order + Trade Result ────────────────────────
        session.merge(ApprovedOrderRecord(
            id="ao_1", signal_id="sig_4", account_id="acct_demo_1",
            symbol="NAS100", side="buy", order_type="limit",
            entry_price=18402.0, stop_price=18386.0, take_profit=18436.0,
            quantity=0.5, risk_pct=0.25, status="filled",
            created_at=(now - timedelta(minutes=45)).isoformat(),
        ))
        session.merge(TradeResultRecord(
            id="tr_1", approved_order_id="ao_1", account_id="acct_demo_1",
            external_trade_id="broker_123", symbol="NAS100",
            strategy_name="ny_sweep_reversal", status="closed",
            entry_price=18402.0, exit_price=18438.0,
            stop_price=18386.0, take_profit=18436.0,
            quantity=0.5, pnl=18.0, pnl_pct=0.36,
            fees=0.0, slippage=0.8,
            opened_at=(now - timedelta(minutes=45)).isoformat(),
            closed_at=(now - timedelta(minutes=28)).isoformat(),
        ))

        # ── Risk Events ──────────────────────────────────────────
        session.merge(RiskEventRecord(
            id="risk_1", account_id="acct_demo_1",
            event_type="daily_loss_throttle", severity="warning",
            message="Risk reduced by 25% after 5% drawdown threshold",
            triggered_at=(now - timedelta(hours=2)).isoformat(),
            auto_action_taken="reduced_risk",
        ))
        session.merge(RiskEventRecord(
            id="risk_2", account_id="acct_demo_1",
            event_type="spread_skip", severity="info",
            message="Trade skipped: EURUSD spread exceeded 15% of ATR",
            triggered_at=(now - timedelta(hours=1)).isoformat(),
        ))

        # ── Incidents ────────────────────────────────────────────
        session.merge(IncidentRecord(
            id="inc_1",
            title="Broker auth token refresh failed",
            category="broker_auth",
            severity="high",
            source="monitor_agent",
            status="resolved",
            summary="JWT expired during market sync; auto-refreshed on retry.",
            details="First refresh attempt failed; second attempt succeeded after 3s backoff.",
            created_at=(now - timedelta(hours=3)).isoformat(),
            resolved_at=(now - timedelta(hours=3, seconds=-10)).isoformat(),
        ))

        # ── Journal ──────────────────────────────────────────────
        session.merge(JournalEntryRecord(
            id="jr_1", trade_result_id="tr_1",
            strategy_name="ny_sweep_reversal", symbol="NAS100",
            session_name="ny_killzone",
            summary="Clean PDL sweep reversal with SMT confirmation. Entry on FVG retest.",
            lesson="Best entries came after reclaim candle close, not first touch.",
            tags=json.dumps(["winner", "smt", "pdl_sweep"]),
            created_by="journal_agent",
            created_at=(now - timedelta(minutes=20)).isoformat(),
        ))
        session.merge(JournalEntryRecord(
            id="jr_2",
            strategy_name="ny_sweep_reversal", symbol="EURUSD",
            session_name="ny",
            summary="Signal expired before approval. Spread was wide at entry time.",
            lesson="Consider auto-approving high-confidence signals above 0.80 in demo mode.",
            tags=json.dumps(["expired", "spread_issue"]),
            created_by="journal_agent",
            created_at=(now - timedelta(minutes=10)).isoformat(),
        ))

        # ── Agent Runs ───────────────────────────────────────────
        session.merge(AgentRunRecord(
            id="ar_1", agent_name="monitor_agent", run_type="scheduled",
            status="completed",
            input_summary="Checked broker auth, market sync, signal queue",
            output_summary="No critical incidents; 1 stale data warning",
            started_at=(now - timedelta(minutes=5)).isoformat(),
            completed_at=(now - timedelta(minutes=5, seconds=-3)).isoformat(),
        ))
        session.merge(AgentRunRecord(
            id="ar_2", agent_name="journal_agent", run_type="scheduled",
            status="completed",
            input_summary="Reviewed 3 closed trades from today",
            output_summary="Created 2 journal entries; 1 winner, 1 expired signal",
            started_at=(now - timedelta(minutes=3)).isoformat(),
            completed_at=(now - timedelta(minutes=3, seconds=-5)).isoformat(),
        ))

        session.commit()
        print("Demo data seeded successfully.")
        print(f"  Account: {acct.id}")
        print(f"  Market states: 5")
        print(f"  Signals: 6 (2 pending, 1 approved, 1 executed, 1 rejected, 1 expired)")
        print(f"  Trades: 1")
        print(f"  Risk events: 2")
        print(f"  Incidents: 1")
        print(f"  Journal entries: 2")
        print(f"  Agent runs: 2")


if __name__ == "__main__":
    seed()
