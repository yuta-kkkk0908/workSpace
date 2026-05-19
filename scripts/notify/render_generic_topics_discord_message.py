#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "topics.db"
OUT_DIR = ROOT / "prompts"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render generic-topic daily digest into Discord-ready message")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--fallback-days", type=int, default=2, help="use latest rows within N days when same-day rows are absent")
    p.add_argument("--items-per-topic", type=int, default=3, help="how many headline/url items to show per topic (2-4 recommended)")
    return p.parse_args()


def extract_headlines_from_markdown(path: Path, limit: int) -> list[tuple[str, str]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    lines = [ln.rstrip() for ln in text.splitlines()]
    in_headlines = False
    current_title = ""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        if s.lower().startswith("## headlines"):
            in_headlines = True
            continue
        if not in_headlines:
            continue
        m = re.match(r"^\d+\.\s+(.+)$", s)
        if m:
            current_title = m.group(1).strip()
            continue
        if s.startswith("- http") or s.startswith("http"):
            url = s[1:].strip() if s.startswith("- ") else s.strip()
            if url in seen:
                continue
            seen.add(url)
            out.append((current_title or "(untitled)", url))
            if len(out) >= limit:
                break
    return out


def resolve_topic_path(raw_path: str) -> Path:
    # DB may store Windows-style separators when ingested on Windows.
    normalized = (raw_path or "").replace("\\", "/")
    return ROOT / normalized


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    try:
        digest = conn.execute(
            "select topic,summary,path from topic_daily_digest where date=? order by topic",
            (args.date,),
        ).fetchall()
        links = conn.execute(
            "select distinct topic,url from topic_links where date=? order by topic,url",
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
                    select distinct t.topic, t.url
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
            raw_lines = (summary or "").splitlines()
            first_line = ""
            in_headlines = False
            for ln in raw_lines:
                s = ln.strip()
                if not s:
                    continue
                if s.lower().startswith("## headlines"):
                    in_headlines = True
                    continue
                if in_headlines and re.match(r"^\d+\.\s+", s):
                    # headline title
                    first_line = s
                    break
                if in_headlines and s.startswith("- 要約:"):
                    first_line = s.replace("- 要約:", "").strip()
                    break
            if not first_line:
                for ln in raw_lines:
                    s = ln.strip()
                    if s and not s.startswith("#") and not s.startswith("- slug:") and not s.startswith("- date:"):
                        first_line = s
                        break
            lines.append(f"[{topic}]")
            md_items = extract_headlines_from_markdown(resolve_topic_path(_path), max(1, args.items_per_topic))
            if md_items:
                for idx, (title, url) in enumerate(md_items, 1):
                    lines.append(f"  {idx}. {title}")
                    lines.append(f"     出典: {url}")
            else:
                urls = []
                seen_urls: set[str] = set()
                for u in topic_links.get(topic, []):
                    if u in seen_urls:
                        continue
                    seen_urls.add(u)
                    urls.append(u)
                    if len(urls) >= max(1, args.items_per_topic):
                        break
                for u in urls:
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
