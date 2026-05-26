# AGENTS.md

## Project Goal

This repository is a personal investment research platform.

The purpose is NOT high-frequency trading or fully automated trading.

The purpose is:

- collect market events
- observe sector reactions
- analyze historical price behavior
- build repeatable trading scenarios
- improve discretionary decision quality

The system is a decision-support platform.

---

## Important Constraints

DO NOT optimize for:

- ultra low latency
- order book reconstruction
- tick-by-tick replay
- scalping systems
- fully automated execution

Those are intentionally out of scope.

---

## Core Research Philosophy

The platform focuses on:

- event-driven signals
- sector rotation
- market context
- historical reaction patterns
- repeatable scenarios

The goal is to discover:

"Under what conditions does a market event statistically create directional edge?"

---

## Data Philosophy

Use hybrid schema design:

- fixed columns for core searchable fields
- flexible JSON for experimental features and observations

Avoid over-normalization.

Prefer:
- simple tables
- reusable views
- iterative schema evolution

Do not create excessive tables unless clearly necessary.

---

## Current Priority

Current priority is NOT prediction accuracy.

Current priority is:

1. historical data accumulation
2. signal classification
3. scenario extraction
4. feature discovery
5. repeatable research workflow

---

## Human Observation

Human observations are important research assets.

Allow storage of:

- qualitative observations
- market mood
- sector sentiment
- discretionary notes

These observations may later become quantitative features.

---

## Technical Direction

Prioritize:

- maintainability
- long-term operation
- simple architecture
- recoverability
- iterative improvement

Avoid premature optimization.