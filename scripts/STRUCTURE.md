# Scripts Structure

## Root (shared orchestrators / compatibility shims)
- `run_ops_scheduler.py`: slot-based scheduler entrypoint (night / inv-morning / inv-noon / inv-evening / inv-scenario)
- `run_pipeline.py`: investment collection pipeline (`daily` / `deep`)
- `run_investment_automation.py`: legacy wrapper for morning/night automation
- Legacy shims kept for backwards compatibility:
  - `check_daily_missing.py`, `check_scheduler_health.py`, `check_needs_freshness.py`
  - `new_topic.py`, `validate_topics.py`, `diff_topic.py`, `export_sample_topic.py`
  - `build_needs_ai_queue.py`, `apply_needs_triage.py`
  - `extract_margin_context.py`

## `scripts/monitoring/`
- `check_daily_missing.py`: daily missing-file check
- `check_scheduler_health.py`: scheduler health / duplicate alert check
- `check_needs_freshness.py`: needs freshness check
- `check_daily_missing_toast.ps1`: Windows toast notification wrapper

## `scripts/topic_tools/`
- `new_topic.py`, `validate_topics.py`, `diff_topic.py`, `export_sample_topic.py`

## `scripts/needs/`
- `build_needs_ai_queue.py`, `apply_needs_triage.py`

## `scripts/investment/manual/`
- `extract_margin_context.py`

## `scripts/data/`
- DB init/ingest and DB-based brief generation
- `init_*_db.py`, `ingest_*_db.py`, `build_today_*_brief_from_db.py`

## `scripts/notify/`
- Discord message renderers (`render_*_discord_message.py`)
- Discord posting wrappers (`post_*_discord.ps1`)

## `scripts/ops/`
- Task Scheduler wrappers and logged execution helpers
- `register_tasks.ps1`, `invoke_logged_task.ps1`, `run_*_and_post.ps1`

## `scripts/investment/collect/`
- source collection scripts (Kabutan, Rakuten board snapshot, generic daily topic collector)

## `scripts/investment/signals/`
- signal generation / reevaluation / entry-candidate / scenario and quality checks

## `scripts/investment/backtest/`
- outcomes fill, paper-trade registration/outcomes/reporting, backtest suite

## `scripts/investment/analysis/`
- rule-check, reproducibility, cross-factor and other analysis utilities
