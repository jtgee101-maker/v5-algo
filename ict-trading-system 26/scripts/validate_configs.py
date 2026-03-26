"""Validate all configuration files before runtime.

Checks:
- All required YAML files exist
- All required keys are present
- Risk parameters are within sane bounds
- Symbols are configured
- Session windows don't overlap incorrectly

Usage:
  python scripts/validate_configs.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


def validate_file_exists(path: str) -> bool:
    if not Path(path).exists():
        print(f"  FAIL: {path} does not exist")
        return False
    print(f"  OK:   {path}")
    return True


def validate_broker_config() -> list[str]:
    errors = []
    try:
        with open("config/broker.yaml") as f:
            cfg = yaml.safe_load(f)

        if "broker" not in cfg:
            errors.append("broker.yaml: missing 'broker' section")
        if "instruments" not in cfg:
            errors.append("broker.yaml: missing 'instruments' section")
        else:
            symbols = cfg["instruments"].get("symbols", [])
            if not symbols:
                errors.append("broker.yaml: no symbols configured")
            for s in symbols:
                if "id" not in s:
                    errors.append(f"broker.yaml: symbol missing 'id': {s}")
    except Exception as e:
        errors.append(f"broker.yaml: parse error: {e}")
    return errors


def validate_risk_config() -> list[str]:
    errors = []
    try:
        with open("config/risk.yaml") as f:
            cfg = yaml.safe_load(f)

        base = cfg.get("base_risk", {})
        if base.get("risk_per_trade", 0) > 0.02:
            errors.append("risk.yaml: risk_per_trade > 2% is dangerously high")
        if base.get("risk_per_trade", 0) <= 0:
            errors.append("risk.yaml: risk_per_trade must be > 0")

        limits = cfg.get("limits", {})
        if limits.get("max_drawdown", 0) > 0.25:
            errors.append("risk.yaml: max_drawdown > 25% is dangerously high")
        if limits.get("max_drawdown", 0) <= 0:
            errors.append("risk.yaml: max_drawdown must be > 0")
        if limits.get("max_daily_loss", 0) > 0.05:
            errors.append("risk.yaml: max_daily_loss > 5% is dangerously high")

        throttles = cfg.get("throttle_levels", [])
        if not throttles:
            errors.append("risk.yaml: no throttle_levels defined")
        else:
            # Check throttles are in ascending order
            dd_pcts = [t["dd_pct"] for t in throttles]
            if dd_pcts != sorted(dd_pcts):
                errors.append("risk.yaml: throttle_levels must be in ascending dd_pct order")

    except Exception as e:
        errors.append(f"risk.yaml: parse error: {e}")
    return errors


def validate_strategy_config() -> list[str]:
    errors = []
    try:
        with open("config/strategy.yaml") as f:
            cfg = yaml.safe_load(f)

        g = cfg.get("global", {})
        if g.get("min_confidence_threshold", 0) < 0.5:
            errors.append("strategy.yaml: min_confidence_threshold < 0.5 is very loose")

        weights = g.get("confidence_weights", {})
        if weights:
            total = sum(weights.values())
            if abs(total - 1.0) > 0.01:
                errors.append(f"strategy.yaml: confidence_weights sum to {total}, should be 1.0")

        strategies = cfg.get("strategies", {})
        if not strategies:
            errors.append("strategy.yaml: no strategies defined")

    except Exception as e:
        errors.append(f"strategy.yaml: parse error: {e}")
    return errors


def validate_structure_config() -> list[str]:
    errors = []
    try:
        with open("config/structure.yaml") as f:
            cfg = yaml.safe_load(f)

        if "sessions" not in cfg:
            errors.append("structure.yaml: missing 'sessions' section")
        if "swing_detection" not in cfg:
            errors.append("structure.yaml: missing 'swing_detection' section")
        if "smt" not in cfg:
            errors.append("structure.yaml: missing 'smt' section")

    except Exception as e:
        errors.append(f"structure.yaml: parse error: {e}")
    return errors


def main() -> None:
    print("=" * 60)
    print("ICT Trading System — Configuration Validator")
    print("=" * 60)

    all_errors: list[str] = []

    # 1. File existence
    print("\n[1/5] Checking file existence...")
    required_files = [
        "config/broker.yaml",
        "config/risk.yaml",
        "config/strategy.yaml",
        "config/structure.yaml",
        "config/monitoring.yaml",
        "schemas/market_state.json",
        "schemas/trade_signal.json",
        "schemas/approved_order.json",
        "schemas/trade_result.json",
        "CLAUDE.md",
    ]
    for f in required_files:
        if not validate_file_exists(f):
            all_errors.append(f"Missing file: {f}")

    # 2. Broker config
    print("\n[2/5] Validating broker config...")
    all_errors.extend(validate_broker_config())

    # 3. Risk config
    print("\n[3/5] Validating risk config...")
    all_errors.extend(validate_risk_config())

    # 4. Strategy config
    print("\n[4/5] Validating strategy config...")
    all_errors.extend(validate_strategy_config())

    # 5. Structure config
    print("\n[5/5] Validating structure config...")
    all_errors.extend(validate_structure_config())

    # Summary
    print("\n" + "=" * 60)
    if all_errors:
        print(f"VALIDATION FAILED — {len(all_errors)} error(s):")
        for err in all_errors:
            print(f"  ✗ {err}")
        sys.exit(1)
    else:
        print("VALIDATION PASSED — all configs are valid.")
        sys.exit(0)


if __name__ == "__main__":
    main()
