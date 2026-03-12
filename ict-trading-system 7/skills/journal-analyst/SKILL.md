---
name: journal-analyst
description: "Creates daily and weekly trading reviews with performance analytics. Use this skill when working on: trade journaling, win/loss analysis, strategy performance attribution, regime classification, drawdown analysis, execution quality reports, signal quality scoring, parameter tuning recommendations, or any post-trade analytics. Also trigger when the user asks about recent performance, wants to understand what happened in a session, or needs data to decide on strategy changes."
---

# Journal Analyst Agent Skill

## Role
You are the post-trade reviewer. After every session (and weekly), you produce structured
analytics that drive system improvement. You answer: what worked, what failed, what regime
dominated, and what should be tuned.

## Daily Review: `data/reviews/daily_{date}.json`

Produced after each NY session closes. Contains:

### 1. Session Summary
- Date, session hours, symbols active
- Total signals generated vs trades taken vs trades rejected (with reasons)
- Net P&L ($ and %), max intraday drawdown
- Regime classification for the day (trend/reversal/chop/news-driven)

### 2. Per-Trade Analysis
For each trade:
- Strategy ID and version
- Signal confidence score vs actual outcome
- Entry quality: slippage, timing
- Exit quality: hit target / stopped out / manual close
- R-multiple achieved
- Confluence tags that were present
- Screenshot reference (candle window around entry/exit, if available)

### 3. Strategy Attribution
- P&L by strategy_id
- Win rate by strategy_id
- Average R by strategy_id
- Signal count vs trade count vs win count by strategy_id

### 4. Structure Quality
- How many structure labels were generated
- False signal rate (signals that would have lost if traded)
- Structure detection accuracy (did the labeled events correspond to real price behavior?)

### 5. Risk Compliance
- Were all throttle rules followed?
- Any near-breaches of limits?
- Position sizing accuracy (intended vs actual)

### 6. Execution Quality
- Average slippage per trade
- Fill rate
- Latency stats
- Any broker issues encountered

## Weekly Review: `data/reviews/weekly_{week}.json`

Aggregates daily reviews plus:

### 1. Strategy Scoreboard
| Strategy | Trades | Win% | Avg R | Expectancy | Profit Factor | Max DD |
|---|---|---|---|---|---|---|

### 2. Regime Analysis
- What regime dominated this week?
- Which strategies performed best/worst in that regime?
- Did the system correctly identify the regime?

### 3. Confidence Calibration
- Bin trades by confidence score (0.6-0.7, 0.7-0.8, 0.8-0.9, 0.9-1.0)
- Actual win rate per bin
- If high-confidence trades lose more than expected, flag calibration drift

### 4. Self-Healing Events
- List all infra self-healing events (re-auth, resync, safe mode)
- List all risk self-healing events (throttle activations, lockouts)
- Outcome of each event

### 5. Recommendations
Based on the data, propose (as suggestions, NOT auto-applied):
- Parameter adjustments with reasoning
- Strategy variant ideas to test
- Instruments to add or drop
- Session window adjustments
- Confidence threshold adjustments

## Implementation: `core/agents/journal_analyst.py`

```python
class JournalAnalyst:
    async def generate_daily_review(self, date: str) -> DailyReview:
        trades = await self.load_trades(date)
        signals = await self.load_signals(date)
        health = await self.load_session_health(date)
        account = await self.load_account_snapshots(date)
        
        return DailyReview(
            session_summary=self.build_session_summary(trades, signals),
            per_trade=self.analyze_trades(trades, signals),
            strategy_attribution=self.attribute_by_strategy(trades),
            structure_quality=self.evaluate_structure(signals),
            risk_compliance=self.check_risk_compliance(trades, account),
            execution_quality=self.evaluate_execution(trades, health),
        )
    
    async def generate_weekly_review(self, week: str) -> WeeklyReview:
        daily_reviews = await self.load_daily_reviews(week)
        return WeeklyReview(
            scoreboard=self.build_scoreboard(daily_reviews),
            regime_analysis=self.analyze_regimes(daily_reviews),
            calibration=self.check_calibration(daily_reviews),
            healing_events=self.summarize_healing(daily_reviews),
            recommendations=self.generate_recommendations(daily_reviews),
        )
```

## Confidence Calibration Check

This is critical for the prediction-market-style scoring:

```python
def check_calibration(self, trades: list[TradeResult]) -> CalibrationReport:
    bins = defaultdict(list)
    for t in trades:
        bin_key = round(t.confidence, 1)  # 0.6, 0.7, 0.8, 0.9
        bins[bin_key].append(t.is_winner)
    
    report = {}
    for conf_bin, outcomes in bins.items():
        actual_win_rate = sum(outcomes) / len(outcomes)
        expected_win_rate = conf_bin  # confidence should approximate win probability
        drift = actual_win_rate - expected_win_rate
        report[conf_bin] = {
            "n_trades": len(outcomes),
            "actual_win_rate": actual_win_rate,
            "expected_win_rate": expected_win_rate,
            "drift": drift,
            "calibrated": abs(drift) < 0.10
        }
    return CalibrationReport(bins=report)
```

## Output Formats
- Daily reviews: `data/reviews/daily_YYYY-MM-DD.json`
- Weekly reviews: `data/reviews/weekly_YYYY-WNN.json`
- All match schemas in `schemas/review_report.json`
