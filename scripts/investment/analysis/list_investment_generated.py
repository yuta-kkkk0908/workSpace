#!/usr/bin/env python3
"""List generated investment-research files without moving them.

This is a safe first step before reorganizing generated outputs. It classifies
known machine-generated files in inbox so humans can distinguish source logs
from derived artifacts.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
JST = timezone(timedelta(hours=9))
INBOX = ROOT / "topics/investment-research/inbox"
DEFAULT_MD = ROOT / "topics/investment-research/inbox/{date}-generated-inventory.md"
DEFAULT_JSON = ROOT / "topics/investment-research/inbox/{date}-generated-inventory.json"

GENERATED_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"rough-backtest-outcomes", "outcome"),
    (r"rough-backtest-win-loss-aggregation", "aggregation"),
    (r"rough-backtest-stratified-analysis", "analysis"),
    (r"cross-factor-read", "analysis"),
    (r"unknown-priority-queue", "triage"),
    (r"context-(data|summary)|-context-(data|summary)", "context"),
    (r"rule-check", "rule"),
    (r"long-rule-reproducibility", "rule"),
    (r"short-", "short"),
    (r"daily-rule-brief|rule-dashboard", "rule"),
    (r"quality-report", "quality"),
    (r"seed-list-comparison", "comparison"),
    (r"generated-inventory", "inventory"),
)


def classify(path: Path) -> str:
    name = path.name
    for pattern, kind in GENERATED_PATTERNS:
        if re.search(pattern, name):
            return kind
    return "source_or_manual"


def main() -> int:
    parser = argparse.ArgumentParser(description="List generated investment-research inbox files.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    parser.add_argument("--output-md", type=Path, default=None)
    parser.add_argument("--output-json", type=Path, default=None)
    args = parser.parse_args()

    files = sorted(p for p in INBOX.glob("*") if p.is_file())
    rows = [
        {
            "path": p.relative_to(ROOT).as_posix(),
            "name": p.name,
            "kind": classify(p),
            "sizeBytes": p.stat().st_size,
        }
        for p in files
    ]
    counts = Counter(row["kind"] for row in rows)
    output_json = args.output_json or Path(str(DEFAULT_JSON).format(date=args.date))
    output_md = args.output_md or Path(str(DEFAULT_MD).format(date=args.date))
    output_json.write_text(json.dumps({
        "createdAt": datetime.now(JST).replace(microsecond=0).isoformat(),
        "mode": "generated-inventory",
        "caution": "Classification is filename-based. Files are not moved.",
        "counts": dict(counts),
        "rows": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        f"# {args.date} Investment Generated Inventory",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {args.date}",
        "- mode: generated-inventory",
        "- caution: filenameベースの分類。ファイル移動はしない。",
        "",
        "## Summary",
    ]
    for kind, count in counts.most_common():
        lines.append(f"- {kind}: {count}")
    for kind in sorted(counts):
        lines.extend(["", f"## {kind}"])
        for row in [r for r in rows if r["kind"] == kind]:
            lines.append(f"- {row['path']} ({row['sizeBytes']} bytes)")
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {output_md.relative_to(ROOT)} files={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
