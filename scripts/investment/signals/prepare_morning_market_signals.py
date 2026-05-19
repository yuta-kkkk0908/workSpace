#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INBOX = ROOT / "topics" / "investment-research" / "inbox"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Prepare lightweight morning market-signals for the target date")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--fallback-days", type=int, default=3)
    return p.parse_args()


def find_latest_signals(date_str: str, fallback_days: int) -> tuple[Path | None, str | None]:
    base = datetime.strptime(date_str, "%Y-%m-%d").date()
    for i in range(1, max(0, fallback_days) + 1):
        d = (base - timedelta(days=i)).isoformat()
        p = INBOX / f"{d}-market-signals.md"
        if p.exists():
            return p, d
    return None, None


def rewrite_for_date(text: str, date_str: str, src_date: str) -> str:
    ymd = date_str.replace("-", "")
    src_ymd = src_date.replace("-", "")

    out = text
    out = re.sub(r"^#\s+\d{4}-\d{2}-\d{2}\s+Market Signals", f"# {date_str} Market Signals", out, flags=re.M)
    out = re.sub(r"(- date:\s*)\d{4}-\d{2}-\d{2}", rf"\g<1>{date_str}", out)
    out = re.sub(rf"signal_{src_ymd}_(\d+)", rf"signal_{ymd}_\1", out)
    note = [
        "",
        "## Morning Lightweight Notes",
        f"- generatedAt: {date_str} 07:30 JST",
        f"- sourceCarryOverDate: {src_date}",
        "- note: 当日朝の軽量収集モード。前日シグナルを土台に外部要因・寄り前確認で更新する。",
        "- caution: 板・気配・売建可否は未確認。08:10シナリオ時に人手確認を前提とする。",
    ]
    if "## Morning Lightweight Notes" not in out:
        out = out.rstrip() + "\n" + "\n".join(note) + "\n"
    return out


def main() -> int:
    args = parse_args()
    dst = INBOX / f"{args.date}-market-signals.md"
    if dst.exists():
        print(f"exists: {dst.relative_to(ROOT)}")
        return 0

    src, src_date = find_latest_signals(args.date, args.fallback_days)
    if not src or not src_date:
        # Create minimal empty template if no historical file is found.
        dst.write_text(
            "\n".join(
                [
                    f"# {args.date} Market Signals",
                    "",
                    "## Topic",
                    "- slug: investment-research",
                    f"- date: {args.date}",
                    "- mode: collect-and-update",
                    "- caution: 売買助言ではなく、材料整理と確認観点。",
                    "",
                    "## Morning Lightweight Notes",
                    f"- generatedAt: {args.date} 07:30 JST",
                    "- sourceCarryOverDate: none",
                    "- note: 当日朝の軽量収集モード。前日シグナルが無いため、N/Cで開始。",
                    "",
                    "## Signals",
                    "- N/C",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"wrote minimal: {dst.relative_to(ROOT)}")
        return 0

    text = src.read_text(encoding="utf-8")
    dst.write_text(rewrite_for_date(text, args.date, src_date), encoding="utf-8")
    print(f"wrote from carry-over: {dst.relative_to(ROOT)} source={src.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
