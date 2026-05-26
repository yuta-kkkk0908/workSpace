#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[1]
# Phase-2 step1 (+25% class): expand collection breadth before weekly re-tune.
KABUTAN_DISCOVER_LATEST = "35"
KABUTAN_MAX_PAGES_NIGHT = "50"
KABUTAN_MAX_PAGES_MORNING = "45"
KABUTAN_MAX_PAGES_EVENING = "35"
KABUTAN_SLEEP_SEC = "1.6"
KABUTAN_JITTER_SEC = "0.6"
KABUTAN_RETRIES = "3"
KABUTAN_RETRY_WAIT_SEC = "2.0"
TDNET_LOOKBACK_DAYS = "7"
WATCH_PROMOTION_MIN_AVG_TURNOVER_MIL = "700"
LOCK_DIR = ROOT / "tmp" / "scheduler-locks"
LOCK_STALE_SEC = 6 * 60 * 60
SIGNAL_UNCHANGED_STREAK_FILE = ROOT / "prompts" / ".signal-unchanged-streak.txt"


def run(cmd: list[str], allow_fail: bool = False) -> int:
    print('[run]', ' '.join(cmd))
    rc = subprocess.run(cmd, cwd=ROOT).returncode
    if rc != 0 and allow_fail:
        return 0
    return rc


def read_int_file(path: Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip() or "0")
    except Exception:
        return 0


def kabutan_collection_profile(slot: str) -> tuple[str, str]:
    """
    Raise collection breadth when signal unchanged streak grows.
    streak>=2: boost max-pages/discover-latest to recover from DATA_THIN.
    """
    streak = read_int_file(SIGNAL_UNCHANGED_STREAK_FILE)
    base_pages = {
        "night": KABUTAN_MAX_PAGES_NIGHT,
        "inv-morning": KABUTAN_MAX_PAGES_MORNING,
        "inv-evening": KABUTAN_MAX_PAGES_EVENING,
    }.get(slot, KABUTAN_MAX_PAGES_NIGHT)
    discover = KABUTAN_DISCOVER_LATEST
    pages = base_pages
    if streak >= 2:
        discover = "40"
        pages = str(max(int(base_pages), 56))
        print(f"[boost] collection profile enabled slot={slot} unchanged_streak={streak} discover={discover} max_pages={pages}")
    return discover, pages


@contextmanager
def slot_lock(slot: str):
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = LOCK_DIR / f"{slot}.lock"
    now = datetime.now().timestamp()
    acquired = False
    try:
        try:
            os.mkdir(lock_path)
            acquired = True
        except FileExistsError:
            # stale lock cleanup
            try:
                st = lock_path.stat()
                if (now - st.st_mtime) > LOCK_STALE_SEC:
                    for p in lock_path.glob("*"):
                        p.unlink(missing_ok=True)
                    os.rmdir(lock_path)
                    os.mkdir(lock_path)
                    acquired = True
            except FileNotFoundError:
                os.mkdir(lock_path)
                acquired = True
        if not acquired:
            print(f"[skip] slot lock exists: {slot}")
            yield False
            return
        meta = {"slot": slot, "pid": os.getpid(), "started_at": datetime.now().isoformat(timespec="seconds")}
        (lock_path / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        yield True
    finally:
        if acquired:
            try:
                for p in lock_path.glob("*"):
                    p.unlink(missing_ok=True)
                os.rmdir(lock_path)
            except FileNotFoundError:
                pass


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Scheduler orchestration for AIOS ops')
    p.add_argument('--slot', required=True, choices=['night', 'inv-morning', 'inv-noon', 'inv-evening', 'inv-scenario'])
    p.add_argument('--date', default=date.today().isoformat())
    p.add_argument('--python', default=sys.executable)
    p.add_argument('--backtest', action='store_true', help='disable non-backtest side effects and today-dependent checks')
    return p.parse_args()


def run_investment_cycle(py: str, d: str, backtest: bool = False) -> int:
    rc = 0
    discover_latest, max_pages = kabutan_collection_profile("night")
    # 1) Python-only collection from external sources (raw temp artifacts in inbox)
    rc |= run([py, 'scripts/investment/collect/collect_kabutan_surprise_signals.py', '--date', d, '--discover-latest', discover_latest, '--max-pages', max_pages, '--sleep', KABUTAN_SLEEP_SEC, '--jitter', KABUTAN_JITTER_SEC, '--retries', KABUTAN_RETRIES, '--retry-wait', KABUTAN_RETRY_WAIT_SEC], allow_fail=True)
    rc |= run([py, 'scripts/investment/collect/collect_kabutan_short_signals.py', '--date', d, '--discover-latest', discover_latest, '--max-pages', max_pages, '--sleep', KABUTAN_SLEEP_SEC, '--jitter', KABUTAN_JITTER_SEC, '--retries', KABUTAN_RETRIES, '--retry-wait', KABUTAN_RETRY_WAIT_SEC], allow_fail=True)
    # 2) Build daily market-signals from collected artifacts (no stale carry-over by default)
    rc |= run([py, 'scripts/investment/signals/build_market_signals_from_batches.py', '--date', d, '--lookback-days', '2', '--max-signals', '6', '--max-long', '3', '--max-short', '3'], allow_fail=True)
    # 3) Fallback only when builder could not produce a valid file
    rc |= run([py, 'scripts/investment/signals/prepare_morning_market_signals.py', '--date', d, '--fallback-days', '1'], allow_fail=True)
    # 4) Persist signals first (DB-first downstream)
    rc |= run([py, 'scripts/data/init_investment_db.py'])
    rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
    # 5) Validate/derive and persist candidates
    rc |= run([py, 'scripts/investment/signals/check_investment_signal_missing.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/signals/generate_technical_signals.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/signals/generate_entry_candidates.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
    rc |= run([py, 'scripts/data/build_today_brief_from_db.py', '--date', d])
    if not backtest:
        rc |= run([py, 'scripts/notify/render_market_signals_discord_message.py', '--date', d, '--slot', 'inv-noon'], allow_fail=True)
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
    discover_latest, max_pages = kabutan_collection_profile("inv-morning")
    rc |= run([py, 'scripts/investment/collect/collect_tdnet_disclosures.py', '--date', d, '--lookback-days', TDNET_LOOKBACK_DAYS], allow_fail=True)
    rc |= run([py, 'scripts/investment/collect/collect_kabutan_surprise_signals.py', '--date', d, '--discover-latest', discover_latest, '--max-pages', max_pages, '--sleep', KABUTAN_SLEEP_SEC, '--jitter', KABUTAN_JITTER_SEC, '--retries', KABUTAN_RETRIES, '--retry-wait', KABUTAN_RETRY_WAIT_SEC], allow_fail=True)
    rc |= run([py, 'scripts/investment/collect/collect_kabutan_short_signals.py', '--date', d, '--discover-latest', discover_latest, '--max-pages', max_pages, '--sleep', KABUTAN_SLEEP_SEC, '--jitter', KABUTAN_JITTER_SEC, '--retries', KABUTAN_RETRIES, '--retry-wait', KABUTAN_RETRY_WAIT_SEC], allow_fail=True)
    rc |= run([py, 'scripts/investment/signals/build_market_signals_from_batches.py', '--date', d, '--lookback-days', '2', '--max-signals', '6', '--max-long', '3', '--max-short', '3'], allow_fail=True)
    rc |= run([py, 'scripts/data/init_investment_db.py'])
    rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
    rc |= run([py, 'scripts/investment/signals/check_investment_signal_missing.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/signals/generate_technical_signals.py', '--date', d], allow_fail=True)
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
    rc |= run([py, 'scripts/investment/collect/collect_tdnet_disclosures.py', '--date', d, '--lookback-days', TDNET_LOOKBACK_DAYS], allow_fail=True)
    rc |= run([py, 'scripts/investment/signals/reevaluate_market_signals.py', '--date', d, '--fallback-days', '1'], allow_fail=True)
    rc |= run([py, 'scripts/data/init_investment_db.py'])
    rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
    rc |= run([py, 'scripts/investment/signals/generate_technical_signals.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/signals/generate_entry_candidates.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
    rc |= run([py, 'scripts/data/build_today_brief_from_db.py', '--date', d])
    rc |= run([py, 'scripts/investment/signals/check_signal_quality.py', '--date', d], allow_fail=True)
    if not backtest:
        # sync_scenario_replies_bot.py loads .env by itself.
        rc |= run([py, 'scripts/notify/sync_scenario_replies_bot.py', '--limit', '100'], allow_fail=True)
    if not backtest:
        rc |= run([py, 'scripts/notify/render_market_signals_discord_message.py', '--date', d], allow_fail=True)
    return rc


def run_investment_cycle_evening(py: str, d: str, backtest: bool = False) -> int:
    """Evening: include technical context after close and final re-evaluation."""
    rc = 0
    discover_latest, max_pages = kabutan_collection_profile("inv-evening")
    rc |= run([py, 'scripts/investment/collect/collect_tdnet_disclosures.py', '--date', d, '--lookback-days', TDNET_LOOKBACK_DAYS], allow_fail=True)
    rc |= run([py, 'scripts/investment/collect/collect_kabutan_surprise_signals.py', '--date', d, '--discover-latest', discover_latest, '--max-pages', max_pages, '--sleep', KABUTAN_SLEEP_SEC, '--jitter', KABUTAN_JITTER_SEC, '--retries', KABUTAN_RETRIES, '--retry-wait', KABUTAN_RETRY_WAIT_SEC], allow_fail=True)
    rc |= run([py, 'scripts/investment/collect/collect_kabutan_short_signals.py', '--date', d, '--discover-latest', discover_latest, '--max-pages', max_pages, '--sleep', KABUTAN_SLEEP_SEC, '--jitter', KABUTAN_JITTER_SEC, '--retries', KABUTAN_RETRIES, '--retry-wait', KABUTAN_RETRY_WAIT_SEC], allow_fail=True)
    # Daily backtest outcome refresh so DB is not dependent on weekly-only updates.
    rc |= run([py, 'scripts/investment/backtest/fill_market_outcomes.py', '--date', d, '--seed-list', 'rough_backtest_full'], allow_fail=True)
    rc |= run([py, 'scripts/investment/signals/build_market_signals_from_batches.py', '--date', d, '--lookback-days', '2', '--max-signals', '6', '--max-long', '3', '--max-short', '3'], allow_fail=True)
    rc |= run([py, 'scripts/investment/backtest/fill_technical_context.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/signals/reevaluate_market_signals.py', '--date', d, '--fallback-days', '1'], allow_fail=True)
    rc |= run([py, 'scripts/data/init_investment_db.py'])
    rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
    rc |= run([py, 'scripts/investment/signals/generate_technical_signals.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/signals/generate_entry_candidates.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
    rc |= run([py, 'scripts/data/build_today_brief_from_db.py', '--date', d])
    rc |= run([py, 'scripts/investment/signals/check_signal_quality.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/investment/analysis/report_signal_pipeline_kpi.py', '--date', d], allow_fail=True)
    # Strengthen next scenario quality by refreshing rule reproducibility artifacts nightly/evening.
    rc |= run_rule_repro_refresh(py, d)
    # Daily operational hint: refresh exit timing analysis from accumulated trades.
    rc |= run([py, 'scripts/investment/backtest/analyze_exit_timing.py', '--out-date', d, '--mode', 'all'], allow_fail=True)
    # Daily mode comparison: backtest/watch/live performance snapshot.
    rc |= run([py, 'scripts/investment/backtest/analyze_paper_trade_stats.py', '--out-date', d, '--mode', 'all'], allow_fail=True)
    # Keep watch outcomes fresh before promotion analysis.
    rc |= run([py, 'scripts/investment/backtest/fill_paper_trade_outcomes.py', '--mode', 'watch', '--as-of', d], allow_fail=True)
    # Render short Discord message for paper stats.
    if not backtest:
        rc |= run([py, 'scripts/notify/render_paper_stats_discord_message.py', '--date', d, '--fallback-days', '3'], allow_fail=True)
    # Daily watch->trade promotion candidates from accumulated watch entries.
    rc |= run(
        [
            py,
            'scripts/investment/backtest/analyze_watch_promotion.py',
            '--out-date',
            d,
            '--ladder',
            '--min-avg-turnover-mil',
            WATCH_PROMOTION_MIN_AVG_TURNOVER_MIL,
        ],
        allow_fail=True,
    )
    # Daily technical-signal effectiveness snapshot (recent 30 trading days).
    rc |= run([py, 'scripts/investment/analysis/analyze_technical_signal_performance.py', '--out-date', d, '--window-days', '30', '--min-samples', '5'], allow_fail=True)
    # Daily consolidated review snapshot for trade/watch quality gap.
    rc |= run([py, 'scripts/investment/backtest/generate_trade_watch_weekly_review.py', '--out-date', d], allow_fail=True)
    if not backtest:
        # sync_scenario_replies_bot.py loads .env by itself.
        rc |= run([py, 'scripts/notify/sync_scenario_replies_bot.py', '--limit', '100'], allow_fail=True)
    if not backtest:
        rc |= run([py, 'scripts/notify/render_market_signals_discord_message.py', '--date', d], allow_fail=True)
    return rc


def main() -> int:
    args = parse_args()
    py = args.python
    d = args.date
    rc = 0

    with slot_lock(args.slot) as ok_to_run:
        if not ok_to_run:
            return 0

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
                rc |= run(
                    [
                        py,
                        'scripts/notify/render_generic_topics_discord_message.py',
                        '--date',
                        d,
                        '--items-per-topic',
                        '3',
                        '--include-urls',
                        '--max-message-len',
                        '3400',
                    ],
                    allow_fail=True,
                )
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
            rc |= run([py, 'scripts/investment/signals/generate_technical_signals.py', '--date', d], allow_fail=True)
            rc |= run([py, 'scripts/investment/signals/generate_entry_candidates.py', '--date', d], allow_fail=True)
            rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
            rc |= run([py, 'scripts/data/build_today_brief_from_db.py', '--date', d], allow_fail=True)
            rc |= run([py, 'scripts/investment/analysis/report_signal_pipeline_kpi.py', '--date', d], allow_fail=True)
            rc |= run([py, 'scripts/investment/analysis/report_weekly_tuning_review.py', '--date', d, '--window-days', '7'], allow_fail=True)
            rc |= run([py, 'scripts/investment/analysis/decide_collection_intensity.py', '--date', d, '--window-days', '3'], allow_fail=True)
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
            rc |= run(
                [
                    py,
                    'scripts/investment/collect/collect_credit_status_auto.py',
                    '--date',
                    d,
                    '--fallback-days',
                    '1',
                    '--max-tickers',
                    '50',
                ],
                allow_fail=True,
            )
            rc |= run([py, 'scripts/investment/analysis/report_credit_auto_quality.py', '--date', d], allow_fail=True)
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
            rc |= run([py, 'scripts/investment/analysis/report_rule_thin_diagnostics.py', '--date', d], allow_fail=True)
            rc |= run([py, 'scripts/investment/signals/build_execution_plan.py', '--date', d, '--fallback-days', '3'], allow_fail=True)
            rc |= run([py, 'scripts/investment/signals/fill_execution_plan_metrics.py', '--start-date', d, '--end-date', d], allow_fail=True)
            # Accumulate watch-mode paper rows for watch->trade promotion analysis.
            # Use tier=all to keep a larger shadow sample while watch-only volume is still small.
            rc |= run([py, 'scripts/investment/backtest/register_paper_trades.py', '--date', d, '--mode', 'watch', '--tier', 'all', '--max-trades', '12', '--fallback-days', '3'], allow_fail=True)
            # Persist scenario/execution artifacts to DB in the same slot.
            rc |= run([py, 'scripts/data/init_investment_db.py'])
            rc |= run([py, 'scripts/data/ingest_investment_db.py', '--date', d])
            rc |= run([py, 'scripts/investment/analysis/cleanup_investment_inbox.py', '--date', d, '--keep-days', '14'], allow_fail=True)
            if not args.backtest:
                rc |= run([py, 'scripts/notify/render_opening_scenarios_discord_message.py', '--date', d], allow_fail=True)
                # post_scenarios_bot.py loads .env by itself.
                rc |= run([py, 'scripts/notify/post_scenarios_bot.py', '--date', d, '--fallback-days', '3', '--max-posts', '12'], allow_fail=True)

    return rc


if __name__ == '__main__':
    raise SystemExit(main())
