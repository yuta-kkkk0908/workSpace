# TASK: Event Collection Pipeline

Goal:
Build a market event collection pipeline.

Requirements:

- collect Japanese stock market events
- support event-driven research
- store OHLCV history
- store disclosure metadata
- support future signal analysis

Data Sources:
- J-Quants
- yfinance
- TDNet
- manually curated observations

Architecture Constraints:
- use hybrid schema
- fixed columns + JSON
- avoid excessive normalization
- SQLite first
- easy local operation

Important:
Do NOT implement:
- trading execution
- broker automation
- order book replay
- real-time scalping logic

Output:
- collector modules
- DB schema
- migration scripts
- reusable interfaces
- logging