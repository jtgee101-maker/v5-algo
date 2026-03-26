"""Diagnose system weaknesses from gathered improvement data.

Reads the output of gather_improvement_data.py and produces a structured
diagnosis report highlighting areas that need attention.

Usage:
  python scripts/diagnose.py --data data/improvement_input/latest.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def diagnose(data: dict) -> dict:
    """Analyze gathered data and produce a diagnosis report."""
    report: dict = {
        "period": data.get("period", "unknown"),
        "issues": [],
        "metrics": {},
        "recommendations": [],
    }

    signals = data.get("signals", [])
    trades = data.get("trades", [])
    errors = data.get("errors", [])
    health_events = data.get("health_events", [])
    throttle_events = data.get("throttle_events", [])

    # ── Error Analysis ─────────────────────────────────────────────────
    if errors:
        error_types = Counter()
        for e in errors:
            error_types[e.get("event", "unknown")] += 1

        report["metrics"]["error_count"] = len(errors)
        report["metrics"]["error_types"] = dict(error_types)

        if len(errors) > 10:
            report["issues"].append({
                "severity": "high",
                "category": "errors",
                "description": f"High error count: {len(errors)} errors",
                "detail": f"Top error types: {error_types.most_common(3)}",
            })

    # ── Signal Quality ─────────────────────────────────────────────────
    if signals:
        confidences = []
        rejections = 0
        rejection_reasons = Counter()

        for s in signals:
            sig = s.get("signal", {})
            decision = s.get("risk_decision", {})

            if sig.get("confidence"):
                confidences.append(sig["confidence"])

            if not decision.get("approved", True):
                rejections += 1
                reason = decision.get("rejection_reason", "unknown")
                rejection_reasons[reason] += 1

        if confidences:
            avg_confidence = sum(confidences) / len(confidences)
            report["metrics"]["avg_signal_confidence"] = round(avg_confidence, 3)
            report["metrics"]["signal_count"] = len(signals)
            report["metrics"]["rejection_count"] = rejections
            report["metrics"]["rejection_rate"] = round(rejections / len(signals), 3) if signals else 0

            if avg_confidence < 0.60:
                report["issues"].append({
                    "severity": "medium",
                    "category": "signal_quality",
                    "description": f"Low average confidence: {avg_confidence:.2f}",
                    "detail": "Structure detection may be producing weak signals",
                })

            if rejections / len(signals) > 0.7:
                report["issues"].append({
                    "severity": "medium",
                    "category": "signal_quality",
                    "description": f"High rejection rate: {rejections}/{len(signals)}",
                    "detail": f"Top reasons: {rejection_reasons.most_common(3)}",
                })

    # ── Trade Performance ──────────────────────────────────────────────
    if trades:
        wins = [t for t in trades if t.get("status") == "closed_win"]
        losses = [t for t in trades if t.get("status") == "closed_loss"]

        win_rate = len(wins) / len(trades) if trades else 0
        report["metrics"]["trade_count"] = len(trades)
        report["metrics"]["win_rate"] = round(win_rate, 3)

        # R-multiple analysis
        r_multiples = [t.get("r_multiple", 0) for t in trades if t.get("r_multiple") is not None]
        if r_multiples:
            avg_r = sum(r_multiples) / len(r_multiples)
            report["metrics"]["avg_r_multiple"] = round(avg_r, 3)

            if avg_r < 0:
                report["issues"].append({
                    "severity": "high",
                    "category": "performance",
                    "description": f"Negative average R-multiple: {avg_r:.2f}",
                    "detail": "System is losing more than it wins on average",
                })

        # Strategy breakdown
        by_strategy = defaultdict(list)
        for t in trades:
            by_strategy[t.get("strategy_id", "unknown")].append(t)

        strategy_perf = {}
        for strat_id, strat_trades in by_strategy.items():
            strat_wins = [t for t in strat_trades if t.get("status") == "closed_win"]
            strat_wr = len(strat_wins) / len(strat_trades) if strat_trades else 0
            strategy_perf[strat_id] = {
                "trades": len(strat_trades),
                "win_rate": round(strat_wr, 3),
            }
        report["metrics"]["by_strategy"] = strategy_perf

    # ── Health Events ──────────────────────────────────────────────────
    if health_events:
        report["metrics"]["health_events"] = len(health_events)
        if len(health_events) > 3:
            report["issues"].append({
                "severity": "high",
                "category": "infrastructure",
                "description": f"{len(health_events)} health events detected",
                "detail": "Check safe mode triggers, kill switch events, and data feed issues",
            })

    if throttle_events:
        report["metrics"]["throttle_events"] = len(throttle_events)
        report["issues"].append({
            "severity": "medium",
            "category": "risk",
            "description": f"{len(throttle_events)} throttle events triggered",
            "detail": "Drawdown staircase was activated",
        })

    # ── Generate Recommendations ───────────────────────────────────────
    for issue in report["issues"]:
        if issue["category"] == "signal_quality" and "confidence" in issue["description"]:
            report["recommendations"].append(
                "Review structure detection thresholds — tighten to produce fewer but higher-quality signals"
            )
        if issue["category"] == "performance" and "R-multiple" in issue["description"]:
            report["recommendations"].append(
                "Review stop placement and target levels — average loser may be too large"
            )
        if issue["category"] == "infrastructure":
            report["recommendations"].append(
                "Audit broker connection stability and data feed health"
            )

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose system weaknesses")
    parser.add_argument("--data", type=str, required=True, help="Path to improvement data JSON")
    args = parser.parse_args()

    with open(args.data) as f:
        data = json.load(f)

    report = diagnose(data)

    output_dir = Path("data/improvements")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / f"diagnosis_{data.get('period', 'unknown')}_{Path(args.data).stem}.json"
    with open(output_file, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Diagnosis complete → {output_file}")
    print(f"  Issues found: {len(report['issues'])}")
    for issue in report["issues"]:
        print(f"    [{issue['severity'].upper()}] {issue['description']}")
    print(f"  Recommendations: {len(report['recommendations'])}")
    for rec in report["recommendations"]:
        print(f"    → {rec}")


if __name__ == "__main__":
    main()
