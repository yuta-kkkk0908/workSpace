#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
TOPICS_DIR = ROOT / "topics"
JST = timezone(timedelta(hours=9))

TOPIC_QUERIES: dict[str, list[str]] = {
    "ai-news-watch": ["AI news", "OpenAI OR Anthropic OR Google AI", "AI regulation"],
    "tech-stack-reads": ["software engineering blog", "developer tools", "infra engineering"],
    "pokemon-card-watch": ["ポケモンカード 新パック 抽選", "ポケモンカード 再販 予約", "ポケモンカード 環境デッキ"],
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Collect generic daily-watch topic notes from RSS feeds")
    p.add_argument("--date", default=date.today().isoformat())
    p.add_argument("--max-items", type=int, default=6)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def clean_text(s: str, max_len: int = 180) -> str:
    s = html.unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > max_len:
        s = s[: max_len - 1].rstrip() + "…"
    return s


def fetch_rss_items(query: str, max_items: int) -> list[tuple[str, str, str, str]]:
    q = urllib.parse.quote_plus(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=ja&gl=JP&ceid=JP:ja"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
    root = ET.fromstring(raw)
    rows: list[tuple[str, str, str, str]] = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = clean_text(item.findtext("description") or "")
        pub = clean_text(item.findtext("pubDate") or "", max_len=80)
        if not title or not link:
            continue
        rows.append((title, link, desc, pub))
        if len(rows) >= max_items:
            break
    return rows


def clean_title(t: str) -> str:
    t = re.sub(r"\s*-\s*Google ニュース$", "", t)
    return t.strip()


def write_topic_daily(topic: str, target_date: str, rows: list[tuple[str, str, str, str]], overwrite: bool) -> Path:
    inbox = TOPICS_DIR / topic / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / f"{target_date}-daily.md"
    if path.exists() and not overwrite:
        return path

    now = datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S%z")
    lines = [
        f"# {target_date} Daily",
        "",
        "## Topic",
        f"- slug: {topic}",
        f"- date: {target_date}",
        "- mode: scheduled-rss-collect",
        "- caution: 自動収集メモ。最終判断は一次情報で確認する。",
        f"- collectedAt: {now}",
        "",
        "## Headlines",
    ]
    if not rows:
        lines.append("- N/C (checked)")
    else:
        for i, (title, link, desc, pub) in enumerate(rows, 1):
            lines.append(f"{i}. {clean_title(title)}")
            if desc:
                lines.append(f"   - 要約: {desc}")
            if pub:
                lines.append(f"   - 掲載時刻: {pub}")
            lines.append(f"   - {link}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    args = parse_args()
    written = 0
    for topic, queries in TOPIC_QUERIES.items():
        merged: list[tuple[str, str, str, str]] = []
        seen: set[str] = set()
        for q in queries:
            try:
                items = fetch_rss_items(q, args.max_items)
            except Exception:
                items = []
            for title, link, desc, pub in items:
                if link in seen:
                    continue
                seen.add(link)
                merged.append((title, link, desc, pub))
                if len(merged) >= args.max_items:
                    break
            if len(merged) >= args.max_items:
                break
        path = write_topic_daily(topic, args.date, merged[: args.max_items], args.overwrite)
        print(f"wrote {path.relative_to(ROOT)} items={min(len(merged), args.max_items)}")
        written += 1
    print(f"topics_written={written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
