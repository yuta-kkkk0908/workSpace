#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "topics.db"
DEFAULT_OUT = ROOT / "prompts" / "today-topics-db-brief.md"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build compact non-investment topic brief from DB")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--out", default=str(DEFAULT_OUT))
    return p.parse_args()


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    try:
        digest = conn.execute(
            "select topic,summary,path from topic_daily_digest where date=? order by topic",
            (args.date,),
        ).fetchall()
        link_counts = dict(
            conn.execute(
                "select topic,count(*) from topic_links where date=? group by topic",
                (args.date,),
            ).fetchall()
        )
    finally:
        conn.close()

    lines: list[str] = []
    lines.append(f"# Topics DB Brief {args.date}")
    lines.append("")
    lines.append("この内容を参考に、非投資トピックの「今日の情報」を要約してください。")
    lines.append("")
    if not digest:
        lines.append("- no topic daily rows")
    else:
        for topic, summary, path in digest:
            lines.append(f"## {topic}")
            lines.append(f"- path: {path}")
            lines.append(f"- links: {link_counts.get(topic, 0)}")
            lines.append("- summary:")
            lines.append(f"  - {(summary or '').replace(chr(10), ' / ')[:500]}")
            lines.append("")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

