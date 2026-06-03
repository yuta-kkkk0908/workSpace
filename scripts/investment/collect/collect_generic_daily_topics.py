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
TECH_STACK_WATCH_CONFIG = TOPICS_DIR / "tech-stack-reads" / "watch-sources.json"
URL_RE = re.compile(r"https?://[^\s\])>]+")
FEED_LINK_RE = re.compile(
    r'<link[^>]+rel=["\']alternate["\'][^>]+type=["\'](?:application/(?:rss|atom|\w*\+xml))["\'][^>]*href=["\']([^"\']+)["\']',
    re.IGNORECASE,
)

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
        "InfoQ software architecture",
        "Martin Fowler architecture",
        "Cloudflare engineering blog",
        "GitHub engineering blog",
        "AWS architecture blog",
        "Google Cloud blog architecture",
        "OpenAI engineering blog",
        "Anthropic engineering blog",
        "Kubernetes blog",
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
    "tech-stack-reads": 120,
}

TOPIC_MIN_DISTINCT_SOURCES: dict[str, int] = {
    "pokemon-card-watch": 2,
    "tech-stack-reads": 3,
}

TOPIC_MAX_ITEMS_PER_SOURCE: dict[str, int] = {
    "pokemon-card-watch": 1,
    "tech-stack-reads": 1,
}

TOPIC_HISTORY_LOOKBACK_DAYS: dict[str, int] = {
    "ai-news-watch": 14,
    "tech-stack-reads": 30,
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


def load_tech_stack_watch_config() -> dict:
    if not TECH_STACK_WATCH_CONFIG.exists():
        return {}
    try:
        return json.loads(TECH_STACK_WATCH_CONFIG.read_text(encoding="utf-8"))
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


def fetch_url_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def fetch_url_text(url: str) -> str:
    return fetch_url_bytes(url).decode("utf-8", errors="replace")


def fetch_rss_items(query: str, max_items: int) -> list[RssItem]:
    q = urllib.parse.quote_plus(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=ja&gl=JP&ceid=JP:ja"
    raw = fetch_url_bytes(url)
    return parse_feed_items(raw, source_hint="Google News", max_items=max_items)


def parse_feed_items(raw: bytes, source_hint: str | None = None, max_items: int = 999) -> list[RssItem]:
    root = ET.fromstring(raw)
    rows: list[RssItem] = []
    def local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1].lower()

    def child_text(node: ET.Element, wanted: str) -> str:
        for child in list(node):
            if local_name(child.tag) == wanted.lower():
                return (child.text or "").strip()
        return ""

    def child_text_any(node: ET.Element, wanted: tuple[str, ...]) -> str:
        for key in wanted:
            text = child_text(node, key)
            if text:
                return text
        return ""

    def first_link(node: ET.Element) -> str:
        for child in list(node):
            if local_name(child.tag) != "link":
                continue
            href = (child.attrib.get("href") or child.text or "").strip()
            if not href:
                continue
            rel = (child.attrib.get("rel") or "").strip().lower()
            if rel in ("alternate", ""):
                return href
        for child in list(node):
            if local_name(child.tag) == "link":
                href = (child.attrib.get("href") or child.text or "").strip()
                if href:
                    return href
        return ""

    def item_source(node: ET.Element) -> str:
        src = child_text(node, "source")
        if src:
            return clean_text(src, max_len=80)
        return source_hint or "unknown"

    for node in root.iter():
        kind = local_name(node.tag)
        if kind not in ("item", "entry"):
            continue
        title = repair_mojibake_title(child_text_any(node, ("title",)))
        link = first_link(node)
        desc = clean_text(
            child_text_any(node, ("description", "summary", "content", "encoded")),
        )
        pub = clean_text(child_text_any(node, ("pubdate", "published", "updated", "modified")), max_len=80)
        source = item_source(node)
        if not title or not link:
            continue
        rows.append(RssItem(title=title, link=link, desc=desc, pub=pub, source=source))
        if len(rows) >= max_items:
            break
    return rows


def discover_feed_urls(page_url: str) -> list[str]:
    try:
        html_text = fetch_url_text(page_url)
    except Exception:
        return []
    urls: list[str] = []
    seen: set[str] = set()
    for match in FEED_LINK_RE.finditer(html_text):
        href = match.group(1).strip()
        if not href:
            continue
        abs_url = urllib.parse.urljoin(page_url, href)
        if abs_url in seen:
            continue
        seen.add(abs_url)
        urls.append(abs_url)
    return urls


def collect_source_page_items(topic: str, source_spec: dict, max_items: int) -> list[RssItem]:
    page_url = str(source_spec.get("url", "")).strip()
    if not page_url:
        return []
    label = str(source_spec.get("name") or source_spec.get("label") or page_url).strip()
    discovered = discover_feed_urls(page_url)
    rows: list[RssItem] = []
    feed_urls = discovered or []
    for feed_url in feed_urls:
        try:
            rows.extend(fetch_feed_items(feed_url, max_items=max_items, source_hint=label))
        except Exception:
            continue
        if len(rows) >= max_items:
            break
    return rows


def fetch_feed_items(feed_url: str, max_items: int, source_hint: str | None = None) -> list[RssItem]:
    raw = fetch_url_bytes(feed_url)
    return parse_feed_items(raw, source_hint=source_hint, max_items=max_items)


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


def normalize_history_title(t: str) -> str:
    s = clean_title(repair_mojibake_title(t))
    s = re.sub(r"\s+", " ", s).strip().lower()
    s = re.sub(r"[^\w\u3040-\u30ff\u3400-\u9fff]+", "", s)
    return s


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


def load_topic_history(topic: str, target_date: date) -> tuple[set[str], set[str]]:
    """
    Return previously seen URLs and normalized titles from the topic's inbox.

    URLs are suppressed across all prior daily files.
    Titles are suppressed within a configurable lookback window.
    """
    inbox = TOPICS_DIR / topic / "inbox"
    if not inbox.exists():
        return set(), set()
    lookback_days = TOPIC_HISTORY_LOOKBACK_DAYS.get(topic, 14)
    title_cutoff = target_date - timedelta(days=lookback_days)
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    for p in sorted(inbox.glob("*.md")):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})-(.+)\.md$", p.name)
        if not m:
            continue
        try:
            file_date = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if file_date >= target_date:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for url in URL_RE.findall(text):
            u = url.strip()
            if u:
                seen_urls.add(u)
        if file_date < title_cutoff:
            continue
        for raw in text.splitlines():
            s = raw.strip()
            m_title = re.match(r"^\d+\.\s+(.+)$", s)
            if not m_title:
                continue
            norm = normalize_history_title(m_title.group(1))
            if norm:
                seen_titles.add(norm)
    return seen_urls, seen_titles


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
    target_date = date.fromisoformat(args.date)
    watch_cfg = load_pokemon_watch_config()
    tech_watch_cfg = load_tech_stack_watch_config()
    extra_queries = watch_cfg.get("extraQueries", []) if isinstance(watch_cfg, dict) else []
    if isinstance(extra_queries, list) and extra_queries:
        q = TOPIC_QUERIES.get("pokemon-card-watch", [])
        for item in extra_queries:
            s = str(item).strip()
            if s and s not in q:
                q.append(s)
        TOPIC_QUERIES["pokemon-card-watch"] = q
    tech_extra_queries = tech_watch_cfg.get("queries", []) if isinstance(tech_watch_cfg, dict) else []
    if isinstance(tech_extra_queries, list) and tech_extra_queries:
        q = TOPIC_QUERIES.get("tech-stack-reads", [])
        for item in tech_extra_queries:
            s = str(item).strip()
            if s and s not in q:
                q.append(s)
        TOPIC_QUERIES["tech-stack-reads"] = q
    written = 0
    now_utc = datetime.now(timezone.utc)
    for topic, queries in TOPIC_QUERIES.items():
        merged_all: list[RssItem] = []
        seen: set[str] = set()
        history_urls, history_titles = load_topic_history(topic, target_date)
        topic_cfg = tech_watch_cfg if topic == "tech-stack-reads" else {}
        source_pages = topic_cfg.get("sourcePages", []) if isinstance(topic_cfg, dict) else []
        explicit_feeds = topic_cfg.get("feedUrls", []) if isinstance(topic_cfg, dict) else []

        for spec in source_pages if isinstance(source_pages, list) else []:
            if not isinstance(spec, dict):
                continue
            try:
                source_rows = collect_source_page_items(topic, spec, args.max_items)
            except Exception:
                source_rows = []
            for row in source_rows:
                norm_title = normalize_history_title(row.title)
                if row.link in seen or row.link in history_urls:
                    continue
                if norm_title and norm_title in history_titles:
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

        for feed_spec in explicit_feeds if isinstance(explicit_feeds, list) else []:
            feed_url = ""
            feed_label = topic
            if isinstance(feed_spec, dict):
                feed_url = str(feed_spec.get("url", "")).strip()
                feed_label = str(feed_spec.get("name") or feed_spec.get("label") or topic).strip() or topic
            else:
                feed_url = str(feed_spec).strip()
            if not feed_url:
                continue
            try:
                items = fetch_feed_items(feed_url, args.max_items, source_hint=feed_label)
            except Exception:
                items = []
            for row in items:
                norm_title = normalize_history_title(row.title)
                if row.link in seen or row.link in history_urls:
                    continue
                if norm_title and norm_title in history_titles:
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

        for q in queries:
            try:
                items = fetch_rss_items(q, args.max_items)
            except Exception:
                items = []
            for row in items:
                norm_title = normalize_history_title(row.title)
                if row.link in seen:
                    continue
                if row.link in history_urls:
                    continue
                if norm_title and norm_title in history_titles:
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
