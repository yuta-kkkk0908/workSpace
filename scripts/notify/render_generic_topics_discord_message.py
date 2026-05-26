#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "topics.db"
OUT_DIR = ROOT / "prompts"


def normalize_headline(text: str) -> str:
    s = (text or "").strip()
    s = re.sub(r"\s*-\s*[^-]+$", "", s)
    s = re.sub(r"[^\w\u3040-\u30ff\u3400-\u9fff]+", "", s).lower()
    return s


def compact_text(text: str, limit: int = 78) -> str:
    s = re.sub(r"\s+", " ", (text or "").strip())
    if len(s) <= limit:
        return s
    return s[: limit - 1].rstrip() + "…"


def repair_mojibake_title(s: str) -> str:
    t = (s or "").strip()
    if not t:
        return t
    if ("Ã" not in t) and ("ã" not in t) and ("â" not in t):
        return t
    for src_enc in ("latin-1", "cp1252"):
        try:
            repaired = t.encode(src_enc, errors="strict").decode("utf-8", errors="strict")
            if repaired:
                return repaired
        except Exception:
            continue
    return t


def normalize_compare_text(text: str) -> str:
    s = (text or "").strip()
    s = re.sub(r"\s*-\s*[^-]+$", "", s)
    s = re.sub(r"[^\w\u3040-\u30ff\u3400-\u9fff]+", "", s).lower()
    return s


def parse_summary_entries(summary: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in (summary or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        m = re.match(r"^\d+\.\s+(.+)$", s)
        if m:
            if current:
                entries.append(current)
            current = {"title": m.group(1).strip(), "summary": "", "url": ""}
            continue
        if not current:
            continue
        if s.startswith("- 要約:"):
            current["summary"] = s.replace("- 要約:", "").strip()
        elif s.startswith("- 掲載時刻:"):
            current["pub"] = s.replace("- 掲載時刻:", "").strip()
        elif s.startswith("- http://") or s.startswith("- https://"):
            current["url"] = s[1:].strip()
        elif s.startswith("http://") or s.startswith("https://"):
            current["url"] = s
    if current:
        entries.append(current)
    return entries


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render generic-topic daily digest into Discord-ready message")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--fallback-days", type=int, default=2, help="use latest rows within N days when same-day rows are absent")
    p.add_argument("--items-per-topic", type=int, default=3, help="how many headline/url items to show per topic (2-4 recommended)")
    p.add_argument("--include-urls", action="store_true", help="include full URLs in message body (can make message long)")
    p.add_argument("--max-message-len", type=int, default=1700, help="auto-shrink items/topic to fit this length")
    p.add_argument("--max-title-age-days", type=int, default=14, help="drop entries when title date looks older than this")
    p.add_argument("--pokemon-max-age-days", type=int, default=1, help="freshness limit for pokemon-card-watch")
    return p.parse_args()


def infer_title_date(title: str, base_year: int) -> str | None:
    s = (title or "").strip()
    m = re.search(r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mo:02d}-{d:02d}"
    m = re.search(r"(\d{1,2})月(\d{1,2})日", s)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        return f"{base_year:04d}-{mo:02d}-{d:02d}"
    return None


def infer_pub_date(pub: str) -> str | None:
    s = (pub or "").strip()
    if not s:
        return None
    m = re.search(r"\b(\d{1,2})\s+([A-Za-z]{3})\s+(20\d{2})\b", s)
    if not m:
        return None
    d = int(m.group(1))
    mon = m.group(2).lower()
    y = int(m.group(3))
    mm = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }.get(mon)
    if not mm:
        return None
    return f"{y:04d}-{mm:02d}-{d:02d}"


def main() -> int:
    args = parse_args()
    base_date = datetime.strptime(args.date, "%Y-%m-%d").date()
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

    parsed: list[tuple[str, list[dict[str, str]]]] = []
    for topic, summary, _path in digest:
        entries = parse_summary_entries(summary or "")
        filtered: list[dict[str, str]] = []
        seen_norm: list[str] = []
        for e in entries:
            title = repair_mojibake_title((e.get("title") or "").strip())
            summ = (e.get("summary") or "").strip()
            if not title:
                continue
            norm = normalize_headline(title)
            if not norm:
                continue
            if any(norm == x or norm in x or x in norm for x in seen_norm):
                continue
            title_date = infer_title_date(title, base_date.year)
            pub_date = infer_pub_date((e.get("pub") or "").strip())
            date_for_age = pub_date or title_date
            if date_for_age:
                try:
                    d = datetime.strptime(date_for_age, "%Y-%m-%d").date()
                    age = (base_date - d).days
                    max_age = args.max_title_age_days
                    if topic == "pokemon-card-watch":
                        max_age = min(max_age, args.pokemon_max_age_days)
                    if age > max(0, max_age):
                        continue
                except ValueError:
                    pass
            seen_norm.append(norm)
            filtered.append(
                {
                    "title": compact_text(title, 76),
                    "summary": compact_text(summ, 90) if summ else "",
                    "url": (e.get("url") or "").strip(),
                }
            )
        parsed.append((topic, filtered))

    items_per_topic = max(1, args.items_per_topic)
    shrink_note = ""
    while True:
        lines = [
            f"汎用トピック日次 {args.date}",
            f"- トピック数: {len(digest)}",
            "",
        ]
        if carried:
            lines.insert(2, f"- 補完: 当日0件のため直近{args.fallback_days}日から繰越")
        if shrink_note:
            lines.insert(2 if not carried else 3, shrink_note)
        if not digest:
            lines.append("- 変化なし（N/C）")
        else:
            for topic, entries in parsed:
                picked = entries[:items_per_topic]
                lines.append(f"[{topic}]")
                if not picked:
                    lines.append("  - 要約データなし")
                for idx, p in enumerate(picked, start=1):
                    lines.append(f"  {idx}) {p['title']}")
                    t_norm = normalize_compare_text(p["title"])
                    s_norm = normalize_compare_text(p["summary"])
                    is_duplicate_summary = (
                        not s_norm
                        or s_norm == t_norm
                        or (t_norm and s_norm and (t_norm in s_norm or s_norm in t_norm))
                    )
                    if p["summary"] and not is_duplicate_summary:
                        lines.append(f"     要約: {p['summary']}")
                    if args.include_urls and p["url"]:
                        # Keep URL clickable while suppressing preview card.
                        lines.append(f"     URL: <{p['url']}>")
                if not args.include_urls:
                    lines.append(f"  出典: Google News RSS（{len(picked)}件）")
                lines.append("")
        msg = "\n".join(lines).rstrip() + "\n"
        if len(msg) <= args.max_message_len or items_per_topic <= 1:
            break
        items_per_topic -= 1
        shrink_note = f"- 自動圧縮: 文字数上限のため表示件数を{items_per_topic}件/トピックへ調整"

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
