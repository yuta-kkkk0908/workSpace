#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
TOPICS_DIR = ROOT / "topics"
JST = timezone(timedelta(hours=9))
POKEMON_WATCH_CONFIG = TOPICS_DIR / "pokemon-card-watch" / "watch-sources.json"

TOPIC_QUERIES: dict[str, list[str]] = {
    "ai-news-watch": [
        "AI news",
        "OpenAI OR Anthropic OR Google AI",
        "AI regulation",
        "LLM API release notes",
        "AI policy safety governance",
    ],
    "tech-stack-reads": [
        "software engineering blog",
        "developer tools",
        "infra engineering",
        "platform engineering incident postmortem",
        "SRE reliability engineering",
    ],
    "pokemon-card-watch": [
        "ポケモンカード 新パック 抽選",
        "ポケモンカード 再販 予約",
        "ポケモンカード 環境デッキ",
        "ポケモンカード 発売日 予約",
        "ポケモンカード ポケモンセンターオンライン 抽選",
        "ポケモンカード 公式 ニュース",
        "ポケモンカードゲーム トレーナーズウェブサイト",
        "ポケモンセンターオンライン ポケモンカード",
        # diversify media surfaces
        "site:4gamer.net ポケモンカード",
        "site:dengekionline.com ポケモンカード",
        "site:gamewith.jp ポケモンカード",
        "site:famitsu.com ポケモンカード",
    ],
}

TOPIC_EXCLUDE_KEYWORDS: dict[str, list[str]] = {
    # Exclude Pokemon TCG Pocket (ポケポケ) app articles from physical card watch.
    "pokemon-card-watch": ["ポケポケ", "ポケモンカードアプリ", "pokemon tcg pocket", "pokepoke"],
}

TOPIC_EXCLUDE_SOURCE_KEYWORDS: dict[str, list[str]] = {
    "pokemon-card-watch": ["yahoo", "news.yahoo", "매일", "머니", "韓国", "中国", "英語版"],
}

TOPIC_REQUIRE_KEYWORDS_ANY: dict[str, list[str]] = {
    "pokemon-card-watch": ["ポケモンカード", "ポケカ", "pokemon card", "pokemon tcg"],
}

TOPIC_MAX_ITEM_AGE_HOURS: dict[str, int] = {
    "pokemon-card-watch": 72,
}

TOPIC_MIN_DISTINCT_SOURCES: dict[str, int] = {
    "pokemon-card-watch": 2,
}

TOPIC_MAX_ITEMS_PER_SOURCE: dict[str, int] = {
    "pokemon-card-watch": 1,
}


@dataclass(frozen=True)
class RssItem:
    title: str
    link: str
    desc: str
    pub: str
    source: str


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Collect generic daily-watch topic notes from RSS feeds")
    p.add_argument("--date", default=date.today().isoformat())
    p.add_argument("--max-items", type=int, default=6)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def load_pokemon_watch_config() -> dict:
    if not POKEMON_WATCH_CONFIG.exists():
        return {}
    try:
        return json.loads(POKEMON_WATCH_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def clean_text(s: str, max_len: int = 180) -> str:
    s = html.unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > max_len:
        s = s[: max_len - 1].rstrip() + "…"
    return s


def repair_mojibake_title(s: str) -> str:
    t = (s or "").strip()
    if not t:
        return t
    # Typical UTF-8 -> latin1/cp1252 mojibake fragments.
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


def fetch_rss_items(query: str, max_items: int) -> list[RssItem]:
    q = urllib.parse.quote_plus(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=ja&gl=JP&ceid=JP:ja"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
    root = ET.fromstring(raw)
    rows: list[RssItem] = []
    for item in root.findall(".//item"):
        title = repair_mojibake_title((item.findtext("title") or "").strip())
        link = (item.findtext("link") or "").strip()
        desc = clean_text(item.findtext("description") or "")
        pub = clean_text(item.findtext("pubDate") or "", max_len=80)
        source = clean_text(item.findtext("source") or "", max_len=80)
        if not title or not link:
            continue
        rows.append(RssItem(title=title, link=link, desc=desc, pub=pub, source=source or "unknown"))
        if len(rows) >= max_items:
            break
    return rows


def is_excluded(topic: str, title: str, desc: str) -> bool:
    words = TOPIC_EXCLUDE_KEYWORDS.get(topic) or []
    if not words:
        return False
    text = f"{title} {desc}".lower()
    return any(w.lower() in text for w in words)


def is_required_match(topic: str, title: str, desc: str) -> bool:
    words = TOPIC_REQUIRE_KEYWORDS_ANY.get(topic) or []
    if not words:
        return True
    text = f"{title} {desc}".lower()
    return any(w.lower() in text for w in words)


def is_excluded_source(topic: str, source: str) -> bool:
    words = TOPIC_EXCLUDE_SOURCE_KEYWORDS.get(topic) or []
    if not words:
        return False
    s = (source or "").lower()
    return any(w.lower() in s for w in words)


def parse_pubdate(pub: str) -> datetime:
    s = (pub or "").strip()
    if not s:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    # Typical RFC2822 from Google News RSS
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def clean_title(t: str) -> str:
    t = re.sub(r"\s*-\s*Google ニュース$", "", t)
    return t.strip()


def within_age_limit(topic: str, pub: str, now_utc: datetime) -> bool:
    max_hours = TOPIC_MAX_ITEM_AGE_HOURS.get(topic)
    if not max_hours:
        return True
    dt = parse_pubdate(pub)
    age_h = (now_utc - dt).total_seconds() / 3600.0
    return age_h <= max_hours


def select_diverse_items(topic: str, rows: list[RssItem], max_items: int) -> list[RssItem]:
    if not rows:
        return []
    per_source_cap = TOPIC_MAX_ITEMS_PER_SOURCE.get(topic, max_items)
    counts: dict[str, int] = {}
    picked: list[RssItem] = []
    for row in rows:
        src = (row.source or "unknown").strip().lower()
        if counts.get(src, 0) >= per_source_cap:
            continue
        picked.append(row)
        counts[src] = counts.get(src, 0) + 1
        if len(picked) >= max_items:
            break
    need_sources = TOPIC_MIN_DISTINCT_SOURCES.get(topic, 1)
    if len({(r.source or "unknown").strip().lower() for r in picked}) >= need_sources:
        return picked
    # Do not backfill from the same source repeatedly.
    # Keep partial diverse set if available; otherwise keep only top 1 recency item.
    return picked if picked else rows[:1]


def infer_sales_type(text: str) -> str:
    t = text.lower()
    if "抽選" in t:
        return "抽選"
    if "受注" in t:
        return "受注"
    if "再販" in t:
        return "再販"
    if "予約" in t:
        return "予約"
    return "一般"


def infer_deck_status(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["大会", "入賞", "優勝", "結果", "実績"]):
        return "実績あり"
    return "注目"


def split_pokemon_rows(rows: list[RssItem]) -> tuple[list[RssItem], list[RssItem]]:
    sales_kw = ["抽選", "予約", "再販", "受注", "販売", "発売", "当選"]
    deck_kw = ["環境", "デッキ", "メタ", "tier", "大会", "入賞", "レシピ", "考察"]
    sales: list[RssItem] = []
    decks: list[RssItem] = []
    for row in rows:
        text = f"{row.title} {row.desc}".lower()
        if any(k.lower() in text for k in sales_kw):
            sales.append(row)
        if any(k.lower() in text for k in deck_kw):
            decks.append(row)
    return sales, decks


def pick_recent_winner_decks(rows: list[RssItem], now_utc: datetime, within_days: int = 7) -> list[RssItem]:
    winner_kw = ["優勝", "大会", "チャンピオン", "入賞", "results", "winner"]
    picked: list[RssItem] = []
    for row in rows:
        text = f"{row.title} {row.desc}".lower()
        if not any(k.lower() in text for k in winner_kw):
            continue
        dt = parse_pubdate(row.pub)
        age_d = (now_utc - dt).total_seconds() / 86400.0
        if age_d > within_days:
            continue
        picked.append(row)
    return picked


def write_topic_daily(topic: str, target_date: str, rows: list[RssItem], overwrite: bool) -> Path:
    inbox = TOPICS_DIR / topic / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / f"{target_date}-daily.md"
    if path.exists() and not overwrite:
        return path

    now = datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S%z")
    lines: list[str] = [
        f"# {target_date} Daily",
        "",
        "## Topic",
        f"- slug: {topic}",
        f"- date: {target_date}",
        "- mode: scheduled-rss-collect",
        "- caution: 自動収集メモ。最終判断は一次情報で確認する。",
        "- filter: 鮮度・関連性・媒体分散フィルタを適用",
        f"- collectedAt: {now}",
        "",
    ]
    if topic == "pokemon-card-watch":
        sales_rows, deck_rows = split_pokemon_rows(rows)
        winner_rows = pick_recent_winner_decks(rows, datetime.now(timezone.utc), within_days=7)
        lines.extend(["## 直近1週間 優勝デッキピックアップ", "- 項目: テーマ / 根拠 / 媒体 / URL"])
        if not winner_rows:
            lines.append("- N/C (直近1週間で優勝デッキ関連記事なし)")
        else:
            for i, row in enumerate(winner_rows[:6], 1):
                lines.append(f"{i}. テーマ: {clean_title(row.title)}")
                lines.append(f"   - 根拠: {row.pub or 'N/A'}")
                lines.append(f"   - 媒体: {row.source or 'unknown'}")
                lines.append(f"   - URL: {row.link}")
        lines.extend(["", "## Lottery & Resale Watch", "- 項目: 商品名 / 区分 / 条件 / 締切 / 媒体 / URL"])
        if not sales_rows:
            lines.append("- N/C (抽選・受注・再販・販売の更新なし)")
        else:
            for i, row in enumerate(sales_rows, 1):
                lines.append(f"{i}. 商品名: {clean_title(row.title)}")
                lines.append(f"   - 受付: {infer_sales_type(row.title + ' ' + row.desc)}")
                lines.append("   - 条件: N/A")
                lines.append(f"   - 締切: {row.pub or 'N/A'}")
                lines.append(f"   - 媒体: {row.source or 'unknown'}")
                lines.append(f"   - URL: {row.link}")
        lines.extend(["", "## Deck Environment Watch", "- 項目: テーマ / 区分 / 根拠 / 媒体 / URL"])
        if not deck_rows:
            lines.append("- N/C (環境デッキ変化なし)")
        else:
            for i, row in enumerate(deck_rows, 1):
                lines.append(f"{i}. テーマ: {clean_title(row.title)}")
                lines.append(f"   - 区分: {infer_deck_status(row.title + ' ' + row.desc)}")
                lines.append(f"   - 根拠: {row.pub or 'N/A'}")
                lines.append(f"   - 媒体: {row.source or 'unknown'}")
                lines.append(f"   - URL: {row.link}")
    else:
        lines.append("## Headlines")
        if not rows:
            lines.append("- N/C (checked)")
        else:
            for i, row in enumerate(rows, 1):
                lines.append(f"{i}. {clean_title(row.title)}")
                if row.desc:
                    lines.append(f"   - 要約: {row.desc}")
                if row.pub:
                    lines.append(f"   - 掲載時刻: {row.pub}")
                if row.source:
                    lines.append(f"   - 媒体: {row.source}")
                lines.append(f"   - {row.link}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    args = parse_args()
    watch_cfg = load_pokemon_watch_config()
    extra_queries = watch_cfg.get("extraQueries", []) if isinstance(watch_cfg, dict) else []
    if isinstance(extra_queries, list) and extra_queries:
        q = TOPIC_QUERIES.get("pokemon-card-watch", [])
        for item in extra_queries:
            s = str(item).strip()
            if s and s not in q:
                q.append(s)
        TOPIC_QUERIES["pokemon-card-watch"] = q
    written = 0
    now_utc = datetime.now(timezone.utc)
    for topic, queries in TOPIC_QUERIES.items():
        merged_all: list[RssItem] = []
        seen: set[str] = set()
        for q in queries:
            try:
                items = fetch_rss_items(q, args.max_items)
            except Exception:
                items = []
            for row in items:
                if row.link in seen:
                    continue
                if is_excluded(topic, row.title, row.desc):
                    continue
                if is_excluded_source(topic, row.source):
                    continue
                if not is_required_match(topic, row.title, row.desc):
                    continue
                if not within_age_limit(topic, row.pub, now_utc):
                    continue
                seen.add(row.link)
                merged_all.append(row)
        merged_all.sort(key=lambda x: parse_pubdate(x.pub), reverse=True)
        merged = select_diverse_items(topic, merged_all, args.max_items)
        path = write_topic_daily(topic, args.date, merged, args.overwrite)
        print(f"wrote {path.relative_to(ROOT)} items={len(merged)}")
        written += 1
    print(f"topics_written={written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
