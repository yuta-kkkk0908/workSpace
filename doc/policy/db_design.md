# TASK: Database Design

Design a simple and maintainable database structure.

Requirements:

- hybrid schema
- minimal core tables
- JSON support for flexible features
- reusable SQL views
- easy historical analysis

Avoid:
- excessive normalization
- deeply coupled table structures
- premature optimization

Core fields should include:
- ticker
- datetime
- event type
- OHLCV
- sector
- market context
- result metrics

Flexible observations belong in JSON.

Views should support:
- signal analysis
- sector analysis
- event outcome comparison