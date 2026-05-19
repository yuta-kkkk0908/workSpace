#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_IN = ROOT / "data" / "rakuten_rss" / "board_latest.csv"
OUT_DIR = ROOT / "topics" / "investment-research" / "inbox"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Load Rakuten RSS board CSV into opening-scenario snapshot JSON")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--input", default=str(DEFAULT_IN), help="CSV path")
    return p.parse_args()


def to_float(v: str) -> float | None:
    s = (v or "").strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def main() -> int:
    args = parse_args()
    inp = Path(args.input)
    if not inp.exists():
        raise SystemExit(f"csv not found: {inp}")

    rows = []
    with inp.open("r", encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        for r in rd:
            ticker = (r.get("ticker") or r.get("code") or "").strip()
            if not ticker:
                continue
            item = {
                "ticker": ticker,
                "company": (r.get("company") or r.get("name") or "").strip(),
                "bestBid": to_float(r.get("best_bid") or r.get("bid1") or ""),
                "bestAsk": to_float(r.get("best_ask") or r.get("ask1") or ""),
                "indicativeOpen": to_float(r.get("indicative_open") or r.get("open_indicative") or ""),
            }
            rows.append(item)

    out = {
        "date": args.date,
        "source": str(inp.relative_to(ROOT)) if inp.is_relative_to(ROOT) else str(inp),
        "count": len(rows),
        "rows": rows,
    }
    out_path = OUT_DIR / f"{args.date}-board-snapshot.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out_path.relative_to(ROOT)} rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
