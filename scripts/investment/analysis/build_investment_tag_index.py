#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOPIC = ROOT / "topics/investment-research"
OUT_JSON = TOPIC / "tag-index.json"
OUT_MD = TOPIC / "tag-index.md"
DEFAULT_DB = ROOT / "data" / "investment.db"
JST = timezone(timedelta(hours=9))


def tags_for_signal(row: sqlite3.Row) -> list[str]:
    tags: set[str] = {"src:signals"}
    st = (row["signal_type"] or "").strip().lower()
    tags.add(f"sig:{st}" if st else "sig:other")
    exp = (row["expected_direction"] or "").lower()
    if exp.startswith("up"):
        tags.add("dir:long")
    elif exp.startswith("down"):
        tags.add("dir:short")
    else:
        tags.add("dir:unknown")
    lr = (row["long_rank"] or "").upper()
    sr = (row["short_rank"] or "").upper()
    if lr:
        tags.add(f"rank:long_{lr.lower()}")
    if sr:
        tags.add(f"rank:short_{sr.lower()}")
    if (row["gate_status"] or "").lower() == "pass":
        tags.add("q:gate_pass")
    return sorted(tags)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--limit-days", type=int, default=30)
    args = p.parse_args()
    if not args.db.exists():
        raise SystemExit(f"db not found: {args.db}")
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        dates = [r[0] for r in conn.execute("SELECT DISTINCT date FROM signals ORDER BY date DESC LIMIT ?", (max(1, args.limit_days),)).fetchall()]
        items = []
        for ds in sorted(dates):
            rows = conn.execute(
                """
                SELECT signal_id,date,ticker,company,signal_type,long_rank,short_rank,expected_direction,gate_status,url
                FROM signals WHERE date=?
                ORDER BY signal_id
                """,
                (ds,),
            ).fetchall()
            for r in rows:
                items.append(
                    {
                        "id": f"{r['date']}::{r['signal_id']}",
                        "date": r["date"],
                        "title": f"{r['ticker'] or ''} {r['company'] or ''}".strip(),
                        "ticker": r["ticker"] or "",
                        "company": r["company"] or "",
                        "signalType": r["signal_type"] or "",
                        "longSignalRank": r["long_rank"] or "",
                        "shortSignalRank": r["short_rank"] or "",
                        "expectedDirection": r["expected_direction"] or "",
                        "tags": tags_for_signal(r),
                        "sourceUrl": r["url"] or "",
                    }
                )
    finally:
        conn.close()
    tag_counts = Counter(tag for item in items for tag in item["tags"])
    by_tag: dict[str, list[str]] = defaultdict(list)
    for item in items:
        for t in item["tags"]:
            by_tag[t].append(item["id"])
    index = {
        "generatedAt": datetime.now(JST).isoformat(timespec="seconds"),
        "topic": "investment-research",
        "itemCount": len(items),
        "tagCounts": dict(sorted(tag_counts.items())),
        "items": items,
        "byTag": {k: v for k, v in sorted(by_tag.items())},
    }
    OUT_JSON.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    top_tags = sorted(index["tagCounts"].items(), key=lambda x: (-x[1], x[0]))[:30]
    lines = [
        "# Investment Tag Index",
        "",
        f"- generatedAt: {index['generatedAt']}",
        f"- itemCount: {index['itemCount']}",
        "",
        "## Top Tags",
    ]
    lines.extend(f"- `{tag}`: {count}" for tag, count in top_tags)
    lines.extend(["", "## Recent Items"])
    for item in index["items"][-30:]:
        lines.append(f"- {item['date']} {item['title']}: {', '.join(f'`{t}`' for t in item['tags'][:12])}")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT_JSON.relative_to(ROOT)} items={index['itemCount']}")


if __name__ == "__main__":
    main()
