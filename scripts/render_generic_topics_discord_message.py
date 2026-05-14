#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "topics.db"
OUT_DIR = ROOT / "prompts"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render generic-topic daily digest into Discord-ready message")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--fallback-days", type=int, default=2, help="use latest rows within N days when same-day rows are absent")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    try:
        digest = conn.execute(
            "select topic,summary,path from topic_daily_digest where date=? order by topic",
            (args.date,),
        ).fetchall()
        links = conn.execute(
            "select topic,url from topic_links where date=? order by topic,url",
            (args.date,),
        ).fetchall()
        carried = 0
        if not digest and args.fallback_days > 0:
            digest = conn.execute(
                """
                with latest as (
                  select topic, max(date) as picked_date
                  from topic_daily_digest
                  where date <= ?
                    and date >= date(?, '-' || ? || ' days')
                  group by topic
                )
                select d.topic, d.summary, d.path
                from topic_daily_digest d
                join latest l
                  on d.topic = l.topic
                 and d.date = l.picked_date
                order by d.topic
                """,
                (args.date, args.date, args.fallback_days),
            ).fetchall()
            if digest:
                carried = 1
                links = conn.execute(
                    """
                    with latest as (
                      select topic, max(date) as picked_date
                      from topic_links
                      where date <= ?
                        and date >= date(?, '-' || ? || ' days')
                      group by topic
                    )
                    select t.topic, t.url
                    from topic_links t
                    join latest l
                      on t.topic = l.topic
                     and t.date = l.picked_date
                    order by t.topic, t.url
                    """,
                    (args.date, args.date, args.fallback_days),
                ).fetchall()
    finally:
        conn.close()

    topic_links: dict[str, list[str]] = {}
    for t, u in links:
        topic_links.setdefault(t, []).append(u)

    lines = [
        f"汎用トピック日次 {args.date}",
        f"- トピック数: {len(digest)}",
        "",
    ]
    if carried:
        lines.insert(2, f"- 補完: 当日0件のため直近{args.fallback_days}日から繰越")
    if not digest:
        lines.append("- 変化なし（N/C）")
    else:
        for topic, summary, _path in digest:
            first = (summary or "").splitlines()
            first_line = ""
            for ln in first:
                s = ln.strip()
                if s and not s.startswith("#"):
                    first_line = s
                    break
            lines.append(f"[{topic}] {first_line}")
            urls = topic_links.get(topic, [])
            for u in urls[:2]:
                lines.append(f"  出典: {u}")
            lines.append("")

    msg = "\n".join(lines).rstrip() + "\n"
    out_txt = OUT_DIR / "generic-topics-discord-message.txt"
    out_md = OUT_DIR / "generic-topics-discord-message.md"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_txt.write_text(msg, encoding="utf-8")
    out_md.write_text("```text\n" + msg + "```\n", encoding="utf-8")
    print(f"wrote {out_txt.relative_to(ROOT)}")
    print(f"wrote {out_md.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
