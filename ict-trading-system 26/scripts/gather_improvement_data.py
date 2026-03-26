"""Gather improvement data from logs, reviews, and metrics.

Usage:
  python scripts/gather_improvement_data.py --period daily
  python scripts/gather_improvement_data.py --period weekly
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path


def gather_daily(date: str | None = None) -> dict:
    """Gather data for daily improvement analysis."""
    if date is None:
        date = datetime.utcnow().strftime("%Y-%m-%d")

    data: dict = {
        "period": "daily",
        "date": date,
        "signals": [],
        "trades": [],
        "errors": [],
        "health_events": [],
        "throttle_events": [],
    }

    # Collect signals
    signals_dir = Path("data/signals")
    if signals_dir.exists():
        for f in signals_dir.glob(f"signal_*_{date.replace('-', '')}*.json"):
            with open(f) as fp:
                data["signals"].append(json.load(fp))

    # Collect trade results
    trades_dir = Path("data/trades")
    if trades_dir.exists():
        for f in trades_dir.glob(f"trade_{date}*.jsonl"):
            with open(f) as fp:
                for line in fp:
                    if line.strip():
                        data["trades"].append(json.loads(line))

    # Collect errors from logs
    logs_dir = Path("logs")
    if logs_dir.exists():
        for log_file in logs_dir.glob("*.jsonl"):
            with open(log_file) as fp:
                for line in fp:
                    if line.strip():
                        try:
                            entry = json.loads(line)
                            entry_date = entry.get("timestamp", "")[:10]
                            if entry_date == date:
                                level = entry.get("level", "")
                                if level in ("error", "critical", "warning"):
                                    data["errors"].append(entry)
                                if "throttle" in str(entry).lower():
                                    data["throttle_events"].append(entry)
                                if "safe_mode" in str(entry).lower() or "kill_switch" in str(entry).lower():
                                    data["health_events"].append(entry)
                        except json.JSONDecodeError:
                            pass

    return data


def gather_weekly(week: str | None = None) -> dict:
    """Gather data for weekly improvement analysis."""
    if week is None:
        now = datetime.utcnow()
        week = now.strftime("%Y-W%W")

    # Get all dates in the week
    year, week_num = week.split("-W")
    start_of_week = datetime.strptime(f"{year}-W{week_num}-1", "%Y-W%W-%w")
    dates = [(start_of_week + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

    data: dict = {
        "period": "weekly",
        "week": week,
        "dates": dates,
        "daily_data": [],
        "reviews": [],
    }

    for date in dates:
        daily = gather_daily(date)
        if daily["signals"] or daily["trades"]:
            data["daily_data"].append(daily)

    # Collect any existing reviews
    reviews_dir = Path("data/reviews")
    if reviews_dir.exists():
        for f in reviews_dir.glob(f"daily_{year}*.json"):
            with open(f) as fp:
                data["reviews"].append(json.load(fp))

    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Gather improvement data")
    parser.add_argument("--period", choices=["daily", "weekly"], default="daily")
    parser.add_argument("--date", type=str, default=None, help="Date (YYYY-MM-DD) or week (YYYY-WNN)")
    args = parser.parse_args()

    if args.period == "daily":
        data = gather_daily(args.date)
    else:
        data = gather_weekly(args.date)

    output_dir = Path("data/improvement_input")
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    output_file = output_dir / f"improvement_data_{args.period}_{timestamp}.json"

    with open(output_file, "w") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"Gathered {args.period} data → {output_file}")
    print(f"  Signals: {len(data.get('signals', []))}")
    print(f"  Trades: {len(data.get('trades', []))}")
    print(f"  Errors: {len(data.get('errors', []))}")


if __name__ == "__main__":
    main()
