#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import date
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], allow_fail: bool = False) -> int:
    print('[run]', ' '.join(cmd))
    rc = subprocess.run(cmd, cwd=ROOT).returncode
    if rc != 0 and allow_fail:
        return 0
    return rc


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Scheduler orchestration for AIOS ops')
    p.add_argument('--slot', required=True, choices=['night', 'inv-morning', 'inv-noon', 'inv-evening', 'inv-scenario'])
    p.add_argument('--date', default=date.today().isoformat())
    p.add_argument('--python', default=sys.executable)
    p.add_argument('--backtest', action='store_true', help='disable non-backtest side effects and today-dependent checks')
    return p.parse_args()


def run_investment_cycle(py: str, d: str, backtest: bool = False) -> int:
    rc = 0
    # 1) Python-only collection from external sources (raw temp artifacts in inbox)
    rc |= run([py, 'scripts/investment/collect/collect_kabutan_surprise_signals.py', '--date', d, '--discover-latest', '20', '--max-pages', '28'], allow_fail=True)
    rc |= run([py, 'scripts/investment/collect/collect_kabutan_short_signals.py', '--date', d, '--discover-latest', '20', '--max-pages', '28'], allow_fail=True)
    # 2) Build daily market-signals from collected artifacts (no stale carry-over by default)
    rc |= run([py, 'scripts/investment/signals/build_market_signals_from_batches.py', '--date', d, '--lookback-days', '2', '--max-signals', '6', '--max-long', '3', '--max-short', '3'], allow_fail=True)
    # 3) Fallback only when builder could not produce a valid file
    rc |= run([py, 'scripts/investment/signals/prepare_morning_market_signals.py', '--date', d, '--fallback-days', '1'], allow_fail=True)
    # 4) Persist signals first (DB-first downstream)
    rc |= run([py, 'scripts/data/init_investment_db.py'])
    rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
    # 5) Validate/derive and persist candidates
    rc |= run([py, 'scripts/investment/signals/check_investment_signal_missing.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/signals/generate_entry_candidates.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
    rc |= run([py, 'scripts/data/build_today_brief_from_db.py', '--date', d])
    if not backtest:
        rc |= run([py, 'scripts/notify/render_market_signals_discord_message.py', '--date', d], allow_fail=True)
    return rc


def run_rule_repro_refresh(py: str, d: str) -> int:
    """Refresh rule reproducibility artifacts so scenario generation can use win-rate context."""
    rc = 0
    # 1) Expand outcomes for the day (cache-only to keep scheduler cost stable)
    rc |= run(
        [
            py,
            'scripts/investment/backtest/fill_market_outcomes.py',
            '--date',
            d,
            '--seed-list',
            'rough_backtest_light',
            '--cache-only',
        ],
        allow_fail=True,
    )
    # 2) Build rule analysis artifacts
    rc |= run([py, 'scripts/investment/analysis/analyze_market_outcomes.py', '--date', d, '--db-only'], allow_fail=True)
    rc |= run(
        [
            py,
            'scripts/investment/analysis/rule_check_market_outcomes.py',
            '--date',
            d,
            '--seed-list',
            'rough_backtest_light',
            '--min-count',
            '8',
            '--db-only',
        ],
        allow_fail=True,
    )
    rc |= run([py, 'scripts/investment/analysis/analyze_long_rule_reproducibility.py', '--date', d, '--min-count', '8'], allow_fail=True)
    rc |= run([py, 'scripts/investment/analysis/classify_short_readiness.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/analysis/analyze_short_chart_windows.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/analysis/analyze_short_rebound_risk.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/analysis/classify_short_conviction.py', '--date', d], allow_fail=True)
    # 3) Dashboard + history
    rc |= run([py, 'scripts/investment/analysis/generate_rule_dashboard.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/analysis/update_rule_history.py', '--date', d], allow_fail=True)
    return rc


def run_investment_cycle_morning(py: str, d: str, backtest: bool = False) -> int:
    """Morning: refresh sources + rebuild signals with overnight context."""
    rc = 0
    rc |= run([py, 'scripts/investment/collect/collect_kabutan_surprise_signals.py', '--date', d, '--discover-latest', '20', '--max-pages', '24'], allow_fail=True)
    rc |= run([py, 'scripts/investment/collect/collect_kabutan_short_signals.py', '--date', d, '--discover-latest', '20', '--max-pages', '24'], allow_fail=True)
    rc |= run([py, 'scripts/investment/signals/build_market_signals_from_batches.py', '--date', d, '--lookback-days', '2', '--max-signals', '6', '--max-long', '3', '--max-short', '3'], allow_fail=True)
    rc |= run([py, 'scripts/data/init_investment_db.py'])
    rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
    rc |= run([py, 'scripts/investment/signals/check_investment_signal_missing.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/signals/generate_entry_candidates.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
    rc |= run([py, 'scripts/data/build_today_brief_from_db.py', '--date', d])
    rc |= run([py, 'scripts/investment/signals/check_signal_quality.py', '--date', d], allow_fail=True)
    if not backtest:
        rc |= run([py, 'scripts/notify/render_market_signals_discord_message.py', '--date', d], allow_fail=True)
    return rc


def run_investment_cycle_noon(py: str, d: str, backtest: bool = False) -> int:
    """Noon: avoid heavy recollection; focus on re-ranking/re-candidates from intraday state."""
    rc = 0
    rc |= run([py, 'scripts/investment/signals/reevaluate_market_signals.py', '--date', d, '--fallback-days', '1'], allow_fail=True)
    rc |= run([py, 'scripts/data/init_investment_db.py'])
    rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
    rc |= run([py, 'scripts/investment/signals/generate_entry_candidates.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
    rc |= run([py, 'scripts/data/build_today_brief_from_db.py', '--date', d])
    rc |= run([py, 'scripts/investment/signals/check_signal_quality.py', '--date', d], allow_fail=True)
    if not backtest and os.getenv('DISCORD_SCENARIOS_BOT_TOKEN') and os.getenv('DISCORD_SCENARIO_CHANNEL_ID'):
        rc |= run([py, 'scripts/notify/sync_scenario_replies_bot.py', '--limit', '100'], allow_fail=True)
    if not backtest:
        rc |= run([py, 'scripts/notify/render_market_signals_discord_message.py', '--date', d], allow_fail=True)
    return rc


def run_investment_cycle_evening(py: str, d: str, backtest: bool = False) -> int:
    """Evening: include technical context after close and final re-evaluation."""
    rc = 0
    rc |= run([py, 'scripts/investment/collect/collect_kabutan_surprise_signals.py', '--date', d, '--discover-latest', '16', '--max-pages', '20'], allow_fail=True)
    rc |= run([py, 'scripts/investment/collect/collect_kabutan_short_signals.py', '--date', d, '--discover-latest', '16', '--max-pages', '20'], allow_fail=True)
    # Daily backtest outcome refresh so DB is not dependent on weekly-only updates.
    rc |= run([py, 'scripts/investment/backtest/fill_market_outcomes.py', '--date', d, '--seed-list', 'rough_backtest_full'], allow_fail=True)
    rc |= run([py, 'scripts/investment/signals/build_market_signals_from_batches.py', '--date', d, '--lookback-days', '2', '--max-signals', '6', '--max-long', '3', '--max-short', '3'], allow_fail=True)
    rc |= run([py, 'scripts/investment/backtest/fill_technical_context.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/signals/reevaluate_market_signals.py', '--date', d, '--fallback-days', '1'], allow_fail=True)
    rc |= run([py, 'scripts/data/init_investment_db.py'])
    rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
    rc |= run([py, 'scripts/investment/signals/generate_entry_candidates.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
    rc |= run([py, 'scripts/data/build_today_brief_from_db.py', '--date', d])
    rc |= run([py, 'scripts/investment/signals/check_signal_quality.py', '--date', d], allow_fail=True)
    # Strengthen next scenario quality by refreshing rule reproducibility artifacts nightly/evening.
    rc |= run_rule_repro_refresh(py, d)
    # Daily operational hint: refresh exit timing analysis from accumulated trades.
    rc |= run([py, 'scripts/investment/backtest/analyze_exit_timing.py', '--out-date', d, '--mode', 'all'], allow_fail=True)
    # Daily mode comparison: backtest/watch/live performance snapshot.
    rc |= run([py, 'scripts/investment/backtest/analyze_paper_trade_stats.py', '--out-date', d, '--mode', 'all'], allow_fail=True)
    # Render short Discord message for paper stats.
    if not backtest:
        rc |= run([py, 'scripts/notify/render_paper_stats_discord_message.py', '--date', d, '--fallback-days', '3'], allow_fail=True)
    # Daily watch->trade promotion candidates from accumulated watch entries.
    rc |= run([py, 'scripts/investment/backtest/analyze_watch_promotion.py', '--out-date', d, '--ladder'], allow_fail=True)
    # Daily consolidated review snapshot for trade/watch quality gap.
    rc |= run([py, 'scripts/investment/backtest/generate_trade_watch_weekly_review.py', '--out-date', d], allow_fail=True)
    if not backtest and os.getenv('DISCORD_SCENARIOS_BOT_TOKEN') and os.getenv('DISCORD_SCENARIO_CHANNEL_ID'):
        rc |= run([py, 'scripts/notify/sync_scenario_replies_bot.py', '--limit', '100'], allow_fail=True)
    if not backtest:
        rc |= run([py, 'scripts/notify/render_market_signals_discord_message.py', '--date', d], allow_fail=True)
    return rc


def main() -> int:
    args = parse_args()
    py = args.python
    d = args.date
    rc = 0

    if args.slot == 'night':
        # Whole repository health + DB ingest for today.
        rc |= run([py, 'scripts/data/init_ops_db.py'])
        rc |= run([py, 'scripts/data/ingest_ops_logs.py'], allow_fail=True)
        if not args.backtest:
            rc |= run([py, 'scripts/check_daily_missing.py', '--date', 'today', '--days', '7'], allow_fail=True)
            rc |= run([py, 'scripts/investment/collect/collect_generic_daily_topics.py', '--date', d, '--overwrite'], allow_fail=True)
        rc |= run([py, 'scripts/data/init_topics_db.py'])
        rc |= run([py, 'scripts/data/ingest_topics_db.py', '--date', d])
        rc |= run([py, 'scripts/data/build_today_topics_brief_from_db.py', '--date', d], allow_fail=True)
        if not args.backtest:
            rc |= run([py, 'scripts/notify/render_generic_topics_discord_message.py', '--date', d], allow_fail=True)
        rc |= run([py, 'scripts/data/init_needs_db.py'])
        rc |= run([py, 'scripts/data/ingest_needs_db.py', '--date', d], allow_fail=True)
        rc |= run([py, 'scripts/build_needs_ai_queue.py', '--limit', '20'], allow_fail=True)
        rc |= run([py, 'scripts/data/init_investment_db.py'])
        rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
        rc |= run([py, 'scripts/data/build_today_brief_from_db.py', '--date', d], allow_fail=True)
        # Investment pass at night as well.
        rc |= run_investment_cycle(py, d, backtest=args.backtest)
        # Refresh reproducibility artifacts in the nightly window as well.
        rc |= run_rule_repro_refresh(py, d)
        # Night lightweight technical context refresh (best-effort).
        rc |= run([py, 'scripts/investment/backtest/fill_technical_context.py', '--date', d], allow_fail=True)
        # Night mandatory: technical check + rank re-evaluation, then refresh derived outputs.
        rc |= run([py, 'scripts/investment/signals/reevaluate_market_signals.py', '--date', d, '--fallback-days', '3'], allow_fail=True)
        rc |= run([py, 'scripts/data/init_investment_db.py'])
        rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
        rc |= run([py, 'scripts/investment/signals/generate_entry_candidates.py', '--date', d], allow_fail=True)
        rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
        rc |= run([py, 'scripts/data/build_today_brief_from_db.py', '--date', d], allow_fail=True)
        if not args.backtest:
            rc |= run([py, 'scripts/notify/render_market_signals_discord_message.py', '--date', d], allow_fail=True)

    if args.slot == 'inv-morning':
        rc |= run_investment_cycle_morning(py, d, backtest=args.backtest)

    if args.slot == 'inv-noon':
        rc |= run_investment_cycle_noon(py, d, backtest=args.backtest)

    if args.slot == 'inv-evening':
        rc |= run_investment_cycle_evening(py, d, backtest=args.backtest)

    if args.slot == 'inv-scenario':
        # JP market is closed on weekends.
        if datetime.strptime(d, "%Y-%m-%d").weekday() >= 5:
            print(f"[skip] inv-scenario weekend: {d}")
            return rc
        rc |= run([py, 'scripts/investment/collect/load_rakuten_board_snapshot.py', '--date', d], allow_fail=True)
        rc |= run(
            [
                py,
                'scripts/investment/signals/build_opening_scenarios.py',
                '--date',
                d,
                '--fallback-days',
                '3',
                '--auto-relax-gate',
                '--allow-unknown-winrate',
                '--soft-gate',
                '--adaptive-side-minimum',
            ],
            allow_fail=True,
        )
        rc |= run([py, 'scripts/investment/signals/build_execution_plan.py', '--date', d, '--fallback-days', '3'], allow_fail=True)
        # Persist scenario/execution artifacts to DB in the same slot.
        rc |= run([py, 'scripts/data/init_investment_db.py'])
        rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
        rc |= run([py, 'scripts/investment/analysis/cleanup_investment_inbox.py', '--date', d, '--keep-days', '14'], allow_fail=True)
        if not args.backtest:
            rc |= run([py, 'scripts/notify/render_opening_scenarios_discord_message.py', '--date', d], allow_fail=True)
            # If Bot credentials exist, post one-scenario-per-message directly.
            if os.getenv('DISCORD_SCENARIOS_BOT_TOKEN') and os.getenv('DISCORD_SCENARIO_CHANNEL_ID'):
                rc |= run([py, 'scripts/notify/post_scenarios_bot.py', '--date', d, '--fallback-days', '3', '--max-posts', '12'], allow_fail=True)

    return rc


if __name__ == '__main__':
    raise SystemExit(main())
