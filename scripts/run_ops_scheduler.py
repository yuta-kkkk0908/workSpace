#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
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
    # Lightweight collection step (night-safe):
    # collect incremental external signal candidates before signal synthesis.
    rc |= run([py, 'scripts/collect_kabutan_surprise_signals.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/collect_kabutan_short_signals.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/prepare_morning_market_signals.py', '--date', d, '--fallback-days', '3'], allow_fail=True)
    rc |= run([py, 'scripts/check_investment_signal_missing.py', '--date', d], allow_fail=True)
    rc |= run([py, 'scripts/generate_entry_candidates.py', '--date', d, '--fallback-days', '3'], allow_fail=True)
    rc |= run([py, 'scripts/init_investment_db.py'])
    rc |= run([py, 'scripts/ingest_investment_db.py', '--date', d])
    rc |= run([py, 'scripts/build_today_brief_from_db.py', '--date', d])
    if not backtest:
        rc |= run([py, 'scripts/render_market_signals_discord_message.py', '--date', d, '--fallback-days', '3'], allow_fail=True)
    return rc


def main() -> int:
    args = parse_args()
    py = args.python
    d = args.date
    rc = 0

    if args.slot == 'night':
        # Whole repository health + DB ingest for today.
        if not args.backtest:
            rc |= run([py, 'scripts/check_daily_missing.py', '--date', 'today', '--days', '7'], allow_fail=True)
        rc |= run([py, 'scripts/init_topics_db.py'])
        rc |= run([py, 'scripts/ingest_topics_db.py', '--date', d])
        rc |= run([py, 'scripts/build_today_topics_brief_from_db.py', '--date', d], allow_fail=True)
        if not args.backtest:
            rc |= run([py, 'scripts/render_generic_topics_discord_message.py', '--date', d], allow_fail=True)
        rc |= run([py, 'scripts/init_needs_db.py'])
        rc |= run([py, 'scripts/ingest_needs_db.py', '--date', d], allow_fail=True)
        rc |= run([py, 'scripts/build_needs_ai_queue.py', '--limit', '20'], allow_fail=True)
        rc |= run([py, 'scripts/init_investment_db.py'])
        rc |= run([py, 'scripts/ingest_investment_db.py', '--date', d])
        rc |= run([py, 'scripts/build_today_brief_from_db.py', '--date', d], allow_fail=True)
        # Investment pass at night as well.
        rc |= run_investment_cycle(py, d, backtest=args.backtest)
        # Night lightweight technical context refresh (best-effort).
        rc |= run([py, 'scripts/fill_technical_context.py', '--date', d], allow_fail=True)
        # Night mandatory: technical check + rank re-evaluation, then refresh derived outputs.
        rc |= run([py, 'scripts/reevaluate_market_signals.py', '--date', d, '--fallback-days', '3'], allow_fail=True)
        rc |= run([py, 'scripts/generate_entry_candidates.py', '--date', d, '--fallback-days', '3'], allow_fail=True)
        rc |= run([py, 'scripts/init_investment_db.py'])
        rc |= run([py, 'scripts/ingest_investment_db.py', '--date', d])
        rc |= run([py, 'scripts/build_today_brief_from_db.py', '--date', d], allow_fail=True)
        if not args.backtest:
            rc |= run([py, 'scripts/render_market_signals_discord_message.py', '--date', d, '--fallback-days', '3'], allow_fail=True)

    if args.slot in {'inv-morning', 'inv-noon', 'inv-evening'}:
        rc |= run_investment_cycle(py, d, backtest=args.backtest)

    if args.slot == 'inv-scenario':
        rc |= run([py, 'scripts/load_rakuten_board_snapshot.py', '--date', d], allow_fail=True)
        rc |= run([py, 'scripts/build_opening_scenarios.py', '--date', d, '--fallback-days', '3'], allow_fail=True)
        if not args.backtest:
            rc |= run([py, 'scripts/render_opening_scenarios_discord_message.py', '--date', d, '--fallback-days', '3'], allow_fail=True)

    return rc


if __name__ == '__main__':
    raise SystemExit(main())
