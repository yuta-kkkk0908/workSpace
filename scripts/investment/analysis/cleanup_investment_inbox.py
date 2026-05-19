#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INBOX = ROOT / "topics" / "investment-research" / "inbox"
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-")

# Keep source-like logs longer; generated derivatives are safe to prune.
GENERATED_PATTERNS = [
    "entry-candidates.",
    "opening-scenarios.",
    "rule-check-",
    "rule-dashboard",
    "rough-backtest-outcomes-",
    "rough-backtest-stratified-analysis",
    "cross-factor-read",
    "unknown-priority-queue",
    "short-readiness-",
    "short-watch-report",
    "short-chart-window-",
    "short-rebound-risk-",
    "short-conviction-",
    "quality-report",
    "generated-inventory",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Cleanup generated investment inbox files older than retention days.")
    p.add_argument("--keep-days", type=int, default=14)
    p.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="Reference date YYYY-MM-DD")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def is_generated(name: str) -> bool:
    return any(p in name for p in GENERATED_PATTERNS)


def main() -> int:
    args = parse_args()
    ref = datetime.strptime(args.date, "%Y-%m-%d").date()
    cutoff = ref - timedelta(days=max(0, args.keep_days))
    removed = 0
    kept = 0

    for p in sorted(INBOX.glob("*")):
        if not p.is_file():
            continue
        m = DATE_RE.match(p.name)
        if not m:
            continue
        if not is_generated(p.name):
            kept += 1
            continue
        d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        if d >= cutoff:
            kept += 1
            continue
        if args.dry_run:
            print(f"DRY-RUN remove {p.relative_to(ROOT)}")
        else:
            p.unlink(missing_ok=True)
            print(f"removed {p.relative_to(ROOT)}")
        removed += 1

    print(f"cleanup_done keep_days={args.keep_days} cutoff={cutoff.isoformat()} removed={removed} kept={kept}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
