# TASK: Signal Research Design

Goal:
Design a framework for discovering repeatable event-driven trading signals.

The system should analyze:

- event type
- sector context
- market condition
- historical outcomes
- volatility behavior
- volume expansion

The objective is NOT prediction by AI alone.

The objective is:

- classify historical reactions
- identify repeatable patterns
- build human-readable scenarios

Examples:
- upward revision + strong growth market
- defense sector + geopolitical event
- AI theme + volume expansion

Important:
The output must remain explainable.

Avoid:
- black-box only approaches
- opaque scoring systems
- overfitted models

## Time Axis Policy

Signal research must separate data by when it becomes available and what it is for.

### 1. Collection data
- Examples: TDnet disclosures, Kabutan batches, intraday snapshots, price daily data.
- Use these as the input to generate or refresh signals.
- They are valid only after their collection cutoff has passed.

### 2. Decision data
- Examples: `signals`, `entry_candidates`, `opening_scenarios`.
- These must be buildable from data available at the scheduler slot.
- Morning and noon jobs must not depend on evaluation-only tables that are only completed later.

### 3. Evaluation data
- Examples: `backtest_outcomes`, quality metrics, rule dashboards.
- These are for validation, tuning, and post-facto analysis.
- They may be updated later in the day or in evening/heavy maintenance jobs.

### Slot responsibilities

- `inv-morning`
  - Build decision data from already available disclosures and prior signals.
  - Carry over previous signals if same-day evaluation data is not yet ready.
  - Do not wait for `backtest_outcomes`.
- `inv-noon`
  - Add intraday snapshots and re-evaluate ranks or gates.
  - Keep decision data usable even if evaluation data is still incomplete.
- `inv-evening` / `inv-heavy`
  - Refresh evaluation data.
  - Rebuild signals and candidates from the now-complete dataset.
  - Prepare the next morning's carry-over base.

### Rule of thumb
- If a table is required to decide what to post now, it belongs to decision data.
- If a table explains how well the idea worked after the fact, it belongs to evaluation data.
- Morning/noon posts must never go `N/C` just because evaluation data has not been populated yet.
