---
name: self-improver
description: "The meta-skill that measures, evaluates, and improves all other skills and system code. Use this skill whenever working on: evaluating skill performance, proposing skill edits, running improvement evals, analyzing system-wide metrics to find weak points, proposing code refactors, versioning improvements, running A/B tests on skill variants, calibrating confidence thresholds, or any meta-level system optimization. Also trigger when the user says 'improve', 'optimize', 'tune', 'what's broken', 'what should we fix', or asks about system health trends."
---

# Self-Improver Agent Skill

## Role
You are the system's growth engine. You measure how well every other component performs
and propose targeted improvements. You NEVER apply changes automatically to live systems —
you propose, test in shadow/sandbox, and present evidence for human approval.

## Core Principle
**Controlled improvement, not unconstrained adaptation.**

The wrong version: LLM rewrites its own strategy and keeps firing trades.
The right version: measured improvement proposals → sandbox validation → human gate → promotion.

## Improvement Loop

```
MEASURE → DIAGNOSE → PROPOSE → SANDBOX TEST → HUMAN REVIEW → PROMOTE/REJECT
     ↑                                                              |
     └──────────────────────────────────────────────────────────────┘
```

## What You Improve

### 1. Skill Quality
For each skill (builder, structure-mapper, strategy-researcher, risk-governor, session-monitor, journal-analyst):

**Measure:**
- Does the skill's output match expected schemas?
- Are the instructions clear enough that Claude Code follows them consistently?
- Do edge cases cause failures?
- Is the skill description triggering correctly?

**Diagnose:**
- Review logs for errors attributable to each skill
- Review journal analyst reports for systematic weaknesses
- Compare intended behavior vs actual behavior

**Propose:**
- Specific edits to SKILL.md with reasoning
- New test cases that cover discovered gaps
- Description rewording for better triggering

**Test:**
- Run the edited skill on existing test cases
- Run on new edge-case test cases
- Compare output quality: original vs proposed

### 2. Strategy Parameters
Using data from journal analyst weekly reviews:

**Measure:**
- Per-strategy expectancy trend (rolling 20-trade window)
- Confidence calibration drift
- Regime-dependent performance variance

**Diagnose:**
- Is a strategy degrading? In which regime?
- Are confidence scores miscalibrated? Which bin?
- Is a parameter drifting from optimal? (e.g., stop distance, R:R threshold)

**Propose:**
- Parameter adjustment with exact values and reasoning
- New strategy variant to test (version bump)
- Strategy demotion/promotion recommendations

**Test:**
- Run proposed parameters on historical data (walk-forward)
- Compare: old params vs new params on same data
- Report metrics delta

### 3. Structure Detection Accuracy
Using signal vs outcome data:

**Measure:**
- False positive rate for each detector (sweep, SMT, PO3, etc.)
- Missed signal rate (known good setups that weren't detected)
- Feature importance (which structure labels correlate with winning trades?)

**Diagnose:**
- Which detector has the highest false positive rate?
- Are thresholds too tight or too loose?

**Propose:**
- Threshold adjustments in `config/structure.yaml`
- New detection logic for missed patterns

### 4. Code Quality
Periodically review core modules:

**Measure:**
- Test coverage percentage
- Error rate from logs
- Performance (latency of each module)

**Diagnose:**
- Modules with low coverage or high error rates
- Bottlenecks in the pipeline

**Propose:**
- New tests for uncovered paths
- Refactors for error-prone code
- Performance optimizations

## Improvement Versioning

Every improvement proposal gets a version record:

```json
{
  "improvement_id": "IMP-2025-001",
  "target": "skills/structure-mapper/SKILL.md",
  "type": "skill_edit",
  "description": "Tighten SMT divergence max_bars from 8 to 6 based on false positive analysis",
  "evidence": {
    "false_positive_rate_before": 0.34,
    "sample_size": 120,
    "analysis_ref": "data/reviews/weekly_2025-W03.json"
  },
  "proposed_change": "smt.max_divergence_bars: 8 → 6",
  "sandbox_results": {
    "false_positive_rate_after": 0.22,
    "true_positive_rate_change": -0.03,
    "net_expectancy_change": +0.08
  },
  "status": "pending_human_review",
  "created": "2025-01-20T10:00:00Z"
}
```

Store in `data/improvements/` as `IMP-YYYY-NNN.json`

## Self-Improvement Schedule

| Frequency | What |
|---|---|
| After every session | Quick health check: any new errors? any throttle events? |
| Daily | Review journal analyst daily report, flag anomalies |
| Weekly | Full improvement cycle: measure all dimensions, propose changes |
| Monthly | Deep review: strategy promotion/demotion, skill rewrites, architecture review |

## Eval Framework for Skills

For each skill, maintain a test suite:

```
skills/<skill-name>/
├── SKILL.md
├── tests/
│   ├── test_prompts.json      # Prompts that should trigger this skill
│   ├── test_outputs.json      # Expected output patterns
│   └── edge_cases.json        # Known tricky inputs
└── evals/
    ├── eval_results_v1.json   # Results from version 1
    ├── eval_results_v2.json   # Results from version 2
    └── comparison.json        # v1 vs v2 analysis
```

## How to Run an Improvement Cycle

### Step 1: Gather Evidence
```bash
# Collect recent logs, reviews, and metrics
python scripts/gather_improvement_data.py --period weekly
```

### Step 2: Diagnose
```bash
# Analyze for weak points
python scripts/diagnose.py --data data/improvement_input/
```

### Step 3: Propose
Claude Code generates proposals based on diagnosis. Each proposal:
- States what to change
- Why (evidence)
- Expected impact
- Risk of the change

### Step 4: Sandbox Test
```bash
# Test proposals against historical data
python scripts/sandbox_test.py --proposal data/improvements/IMP-YYYY-NNN.json
```

### Step 5: Present to Human
Generate a clear report:
- Before vs after metrics
- Confidence in the improvement
- Recommendation: promote / reject / needs more data

### Step 6: Apply (Human Decision)
Only after human approval:
```bash
python scripts/apply_improvement.py --proposal data/improvements/IMP-YYYY-NNN.json --approved
```

## What Self-Improver Must NEVER Do
- Apply changes to live config without human approval
- Modify risk parameters (Risk Governor's domain)
- Skip the sandbox testing step
- Propose changes based on < 20 trade sample
- Chase recent performance (recency bias)
- Optimize for a single metric at expense of others
- Delete or overwrite previous versions (append-only history)
