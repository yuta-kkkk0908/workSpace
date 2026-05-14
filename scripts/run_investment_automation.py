#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], allow_fail: bool = False) -> int:
    print('[run]', ' '.join(cmd))
    rc = subprocess.run(cmd, cwd=ROOT).returncode
    if rc != 0 and allow_fail:
        return 0
    return rc


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Windows-friendly investment automation runner')
    p.add_argument('--date', default=date.today().isoformat())
    p.add_argument('--mode', choices=['night', 'morning', 'both'], default='night')
    p.add_argument('--python', default=sys.executable)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    py = args.python
    d = args.date
    rc = 0

    if args.mode in ('night', 'both'):
        rc |= run([py, 'scripts/check_daily_missing.py', '--date', 'today', '--days', '7'], allow_fail=True)
        rc |= run([py, 'scripts/check_investment_signal_missing.py', '--date', d])
        rc |= run([py, 'scripts/generate_entry_candidates.py', '--date', d])
        rc |= run([py, 'scripts/init_investment_db.py'])
        rc |= run([py, 'scripts/ingest_investment_db.py', '--date', d])

    if args.mode in ('morning', 'both'):
        y = (date.fromisoformat(d) - timedelta(days=1)).isoformat()
        rc |= run([py, 'scripts/check_daily_missing.py', '--date', y, '--days', '1'], allow_fail=True)
        rc |= run([py, 'scripts/init_investment_db.py'])
        rc |= run([py, 'scripts/ingest_investment_db.py', '--date', y])

    return rc


if __name__ == '__main__':
    raise SystemExit(main())
