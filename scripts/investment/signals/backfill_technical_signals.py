#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill technical_daily signals for recent trading days")
    p.add_argument("--days", type=int, default=40, help="number of recent trading days")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--python", default=sys.executable)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"db not found: {args.db}")
    conn = sqlite3.connect(args.db)
    try:
        days = [r[0] for r in conn.execute("SELECT DISTINCT date FROM facts_price_daily ORDER BY date DESC LIMIT ?", (args.days,)).fetchall()]
    finally:
        conn.close()
    if not days:
        raise SystemExit("no trade days found")

    script = ROOT / "scripts" / "investment" / "signals" / "generate_technical_signals.py"
    ok = 0
    ng = 0
    # old -> new for deterministic replacement
    for d in sorted(days):
        rc = subprocess.run([args.python, str(script), "--date", d], cwd=ROOT).returncode
        if rc == 0:
            ok += 1
        else:
            ng += 1
    print(f"backfill_technical_signals done days={len(days)} ok={ok} ng={ng}")
    return 0 if ng == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
