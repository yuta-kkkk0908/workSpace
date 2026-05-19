#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

JST_NOW = datetime.now()
ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "configs/investment-seeds-extended.json"
INBOX = ROOT / "topics/investment-research/inbox"

DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build extended rough backtest seed list from inbox files")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--seed-list", default="rough_backtest_extended")
    p.add_argument("--years", type=int, default=3, help="Lookback years from --as-of date")
    p.add_argument("--as-of", default=JST_NOW.strftime("%Y-%m-%d"))
    return p.parse_args()


def in_scope(name: str) -> bool:
    return (
        name.endswith("-market-signals.md")
        or "-backfill-" in name
        or "-april-backfill-signal-ranks.md" in name
        or "-six-month-rough-backtest-batch-" in name
    )


def main() -> int:
    args = parse_args()
    as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date()
    start = as_of - timedelta(days=365 * args.years)

    rows: list[str] = []
    for p in sorted(INBOX.glob("*.md")):
        m = DATE_PREFIX_RE.match(p.name)
        if not m:
            continue
        d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        if d < start or d > as_of:
            continue
        if not in_scope(p.name):
            continue
        rows.append(str(p.relative_to(ROOT)).replace("\\", "/"))

    data = json.loads(args.config.read_text(encoding="utf-8"))
    data["description"] = f"Extended seeds across {args.years}y window up to {args.as_of}."
    data["defaultSeedList"] = args.seed_list
    data.setdefault("seedLists", {})[args.seed_list] = rows
    args.config.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"updated {args.config}")
    print(f"seed_list={args.seed_list}")
    print(f"as_of={args.as_of}")
    print(f"start={start.isoformat()}")
    print(f"count={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
