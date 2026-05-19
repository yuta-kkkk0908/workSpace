#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(cmd: list[str], allow_fail: bool = False) -> int:
    print("[run]", " ".join(cmd))
    rc = subprocess.run(cmd, cwd=ROOT).returncode
    if rc != 0 and allow_fail:
        return 0
    return rc


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run fixed operations by Japanese keyword")
    p.add_argument("keyword", help="点検 / 点検補完 / 話題補完 / ニーズ補完 / 投資補完 / 全部")
    p.add_argument("--date", default=date.today().isoformat(), help="YYYY-MM-DD")
    p.add_argument("--python", default=sys.executable)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    kw = args.keyword.strip()
    py = args.python
    d = args.date
    rc = 0

    if kw == "点検":
        rc |= run([py, "scripts/check_daily_missing.py", "--date", "today", "--days", "7", "--check-db", "--check-discord-posts", "--warn-only-soft"], allow_fail=True)
        rc |= run([py, "scripts/check_scheduler_health.py", "--mode", "daily", "--hours", "48"], allow_fail=True)
        return rc

    if kw == "話題補完":
        rc |= run([py, "scripts/investment/collect/collect_generic_daily_topics.py", "--date", d, "--overwrite"], allow_fail=True)
        rc |= run([py, "scripts/data/init_topics_db.py"])
        rc |= run([py, "scripts/data/ingest_topics_db.py", "--date", d], allow_fail=True)
        return rc

    if kw == "ニーズ補完":
        rc |= run([py, "scripts/data/init_needs_db.py"])
        rc |= run([py, "scripts/data/ingest_needs_db.py", "--date", d], allow_fail=True)
        rc |= run([py, "scripts/build_needs_ai_queue.py", "--limit", "20"], allow_fail=True)
        return rc

    if kw == "投資補完":
        return run([py, "scripts/run_ops_scheduler.py", "--slot", "inv-evening", "--date", d], allow_fail=False)

    if kw in ("点検補完", "全部"):
        return run([py, "scripts/run_ops_scheduler.py", "--slot", "night", "--date", d], allow_fail=False)

    print(f"unknown keyword: {kw}")
    print("supported: 点検, 点検補完, 話題補完, ニーズ補完, 投資補完, 全部")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

