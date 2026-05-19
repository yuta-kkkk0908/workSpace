#!/usr/bin/env python3
"""Collect rough backtest signal seeds from Kabutan surprise earnings pages.

This creates a Markdown seed file for rough outcome filling. It uses public
Kabutan article pages as secondary-source discovery, then stores only concise
signal summaries and source URLs. It is for research logs, not trading advice.
"""
from __future__ import annotations

import argparse
import html
import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
JST = timezone(timedelta(hours=9))
DEFAULT_OUTPUT = ROOT / "topics/investment-research/inbox/{date}-six-month-rough-backtest-batch-5-kabutan-surprise.md"
DEFAULT_URLS = [
    "https://s.kabutan.jp/news/n202601081087/",
    "https://s.kabutan.jp/news/n202601091187/",
    "https://s.kabutan.jp/news/n202601131006/",
    "https://s.kabutan.jp/news/n202603020903/",
    "https://s.kabutan.jp/news/n202603131087/",
    "https://s.kabutan.jp/news/n202603231075/",
    "https://s.kabutan.jp/news/n202603251001/",
    "https://s.kabutan.jp/news/n202603311153/",
    "https://s.kabutan.jp/news/n202604130911/",
    "https://s.kabutan.jp/news/n202604151025/",
    "https://s.kabutan.jp/news/n202604171034/",
    "https://s.kabutan.jp/news/n202604200898/",
    "https://s.kabutan.jp/news/n202604301167/",
    "https://s.kabutan.jp/news/n202605011184/",
]
DISCOVERY_PAGES = [
    "https://s.kabutan.jp/news/",
    "https://s.kabutan.jp/news/marketnews/",
]


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


@dataclass(frozen=True)
class Seed:
    ticker: str
    company: str
    signal_date: str
    category: str
    signal_type: str
    expected: str
    long_rank: str
    short_rank: str
    summary: str
    source: str
    section: str


DEFAULT_USER_AGENT = "AIOSResearchBot/1.0 (+for research logging; contact: local operator)"


def polite_sleep(base: float, jitter: float) -> None:
    delay = max(0.0, base + random.uniform(0.0, max(0.0, jitter)))
    time.sleep(delay)


def fetch_text(url: str, timeout: float = 10.0, user_agent: str = DEFAULT_USER_AGENT, retries: int = 2, retry_wait: float = 2.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "ignore")
            break
        except urllib.error.HTTPError as e:
            if attempt >= retries:
                raise
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(retry_wait * (2**attempt))
                continue
            raise
        except Exception:
            if attempt >= retries:
                raise
            time.sleep(retry_wait * (2**attempt))
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"</(p|li|div|h[1-6]|tr)>", "\n", raw, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text


def discover_recent_urls(limit: int, timeout: float = 10.0, user_agent: str = DEFAULT_USER_AGENT, sleep: float = 1.5, jitter: float = 0.5) -> list[str]:
    if limit <= 0:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for page in DISCOVERY_PAGES:
        try:
            raw = urllib.request.urlopen(
                urllib.request.Request(page, headers={"User-Agent": user_agent}),
                timeout=timeout,
            ).read().decode("utf-8", "ignore")
        except Exception:
            continue
        for m in re.finditer(r'href="(/news/[nk]\d{12}/)"', raw):
            url = "https://s.kabutan.jp" + m.group(1)
            if url in seen:
                continue
            seen.add(url)
            found.append(url)
            if len(found) >= limit:
                return found
        polite_sleep(sleep, jitter)
    return found


def article_date(text: str) -> str | None:
    m = re.search(r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日", text)
    if not m:
        return None
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def normalize_section(line: str) -> str | None:
    if "今期" in line and "最高益" in line and "予想" in line:
        return "highest_profit_guidance"
    if "最高益予想" in line and "上乗せ" in line:
        return "upward_revision_highest_profit"
    if "最高益" in line and "上方修正" in line:
        return "upward_revision_highest_profit"
    if "大幅" in line and "上方修正" in line:
        return "upward_revision"
    if "一転増益" in line and "上方修正" in line:
        return "upward_revision"
    if "通期計画" in line and "超過" in line:
        return "earnings_progress_positive"
    if "大幅増益" in line and "着地" in line:
        return "earnings_positive"
    if "大幅増益" in line and "予想" in line:
        return "earnings_positive_guidance"
    if "黒字浮上" in line:
        return "turnaround_positive"
    if "配当増額" in line:
        return "dividend_revision"
    if "下方修正" in line:
        return "downward_revision"
    if "赤字" in line or "減益" in line:
        return "earnings_negative"
    return None


def classify(section: str, summary: str) -> tuple[str, str, str, str, str]:
    s = summary
    lower = s.lower()
    has_dividend = "増配" in s or "配当" in s or "復配" in s
    has_highest = "最高益" in s
    has_up = "上方修正" in s or "上乗せ" in s or "増益" in s or has_highest or "黒字浮上" in s or "超過" in s
    has_down = "下方修正" in s or "赤字" in s or "減益" in s or "減配" in s
    if has_down and not has_up:
        return "earnings_negative", "downward_revision", "down", "C", "B"
    if section == "dividend_revision" and not has_highest and not "上方修正" in s:
        return "dividend_return", "dividend_revision", "up_or_unclear", "B", "none"
    if has_highest and has_dividend:
        return "earnings_positive", "highest_profit_guidance_dividend_revision", "up", "A-", "none"
    if has_highest and ("上方修正" in s or "上乗せ" in s):
        return "earnings_positive", "upward_revision_highest_profit", "up", "A-", "none"
    if has_highest:
        return "earnings_positive", "highest_profit_guidance", "up", "B+", "none"
    if "上方修正" in s or "上乗せ" in s:
        st = "upward_revision_plus_dividend" if has_dividend else "upward_revision"
        rank = "A-" if has_dividend else "B+"
        return "earnings_positive", st, "up", rank, "none"
    if has_up:
        return "earnings_positive", section or "earnings_positive", "up", "B", "none"
    return "unknown", section or "unknown", "unclear", "C", "C"


def extract_from_url(url: str, timeout: float, user_agent: str, retries: int, retry_wait: float) -> list[Seed]:
    text = fetch_text(url, timeout=timeout, user_agent=user_agent, retries=retries, retry_wait=retry_wait)
    date = article_date(text)
    if not date:
        return []
    # Keep the current-day surprise block and drop next-day schedule noise.
    body = text.split("２）", 1)[0]
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    section = "unknown"
    out: list[Seed] = []
    for line in lines:
        maybe_section = normalize_section(line)
        if maybe_section and "<" not in line:
            section = maybe_section
            continue
        m = re.search(r"(.+?)\s*<([0-9]{4}|[0-9]{3}[A-Z])>\s*(?:\[[^\]]+\])?\s*(.+)", line)
        if not m:
            continue
        company = m.group(1).strip(" ・　")
        ticker = m.group(2)
        summary = m.group(3).strip(" ・　")
        # Skip schedule/table fragments that slipped through.
        if not company or "前回" in summary or "合計" in summary or "予定" in summary:
            continue
        cat, stype, expected, long_rank, short_rank = classify(section, summary)
        out.append(
            Seed(
                ticker=ticker,
                company=company,
                signal_date=date,
                category=cat,
                signal_type=stype,
                expected=expected,
                long_rank=long_rank,
                short_rank=short_rank,
                summary=summary,
                source=url,
                section=section,
            )
        )
    return out


def build_markdown(seeds: list[Seed], urls: list[str], date: str) -> str:
    lines = [
        f"# {date} Six-Month Rough Backtest Batch 5 Kabutan Surprise",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {date}",
        "- mode: rough-backtest-expansion",
        "- ruleVersion: market-signal-v6-auto-rule-check",
        "- sourceData: Kabutan surprise earnings pages, concise secondary-source discovery",
        "- caution: 株探記事からの二次情報seed。価格結果は `scripts/investment/backtest/fill_market_outcomes.py` で別途補完する。売買助言ではない。",
        "",
        "## Coverage Update",
        f"- sourcePages: {len(urls)}",
        f"- addedSeedsBeforeDedup: {len(seeds)}",
        "- target: 200-300 outcome rows after merging with existing rough backtest seeds",
        "",
        "## Source Pages",
    ]
    for url in urls:
        lines.append(f"- {url}")
    lines.extend(["", "## Added Signals"])
    for idx, s in enumerate(seeds, 1):
        lines.extend([
            f"### rough5_{date.replace('-', '')}_{idx:03d}: {s.ticker} {s.company} {s.signal_type}",
            f"- ticker: {s.ticker}",
            f"- company: {s.company}",
            f"- signalDate: {s.signal_date} after close",
            f"- publishedAt: {s.signal_date}T17:05:00+09:00",
            "- session: after_close",
            f"- disclosureCategory: {s.category}",
            f"- signalType: {s.signal_type}",
            f"- signalSummary: {s.summary}",
            f"- expectedDirection: {s.expected}",
            f"- longSignalRank: {s.long_rank}",
            f"- shortSignalRank: {s.short_rank}",
            f"- materialityReason: 株探サプライズ決算記事の `{s.section}` セクションから抽出。詳細は一次開示で後日確認する。",
            f"- source: {s.source}",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect Kabutan surprise earnings signals into rough backtest seeds.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--url", action="append", dest="urls", help="Kabutan article URL; can be repeated")
    parser.add_argument("--sleep", type=float, default=1.5, help="Base delay (seconds) between requests")
    parser.add_argument("--jitter", type=float, default=0.5, help="Random extra delay [0, jitter] seconds")
    parser.add_argument("--discover-latest", type=int, default=12, help="discover additional recent Kabutan URLs from index pages")
    parser.add_argument("--timeout", type=float, default=8.0, help="HTTP timeout seconds per page")
    parser.add_argument("--max-pages", type=int, default=24, help="max number of pages to scan after merge")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--retries", type=int, default=2, help="HTTP retry count for transient errors")
    parser.add_argument("--retry-wait", type=float, default=2.0, help="Base wait seconds before retry (exponential backoff)")
    parser.add_argument("--cache-only", action="store_true", help="Do not fetch Kabutan pages; keep existing output if present.")
    args = parser.parse_args()
    output = args.output or Path(str(DEFAULT_OUTPUT).format(date=args.date))
    if args.cache_only:
        if output.exists():
            print(f"cache-only: kept {display_path(output)}")
            return 0
        output.write_text(build_markdown([], [], args.date), encoding="utf-8")
        print(f"cache-only: wrote empty {display_path(output)}")
        return 0
    urls = list(args.urls or DEFAULT_URLS)
    extra = discover_recent_urls(
        args.discover_latest,
        timeout=args.timeout,
        user_agent=args.user_agent,
        sleep=args.sleep,
        jitter=args.jitter,
    )
    if extra:
        known = set(urls)
        for u in extra:
            if u not in known:
                urls.append(u)
                known.add(u)
    seeds: list[Seed] = []
    seen: set[tuple[str, str, str]] = set()
    if args.max_pages > 0 and len(urls) > args.max_pages:
        urls = urls[: args.max_pages]
    print(f"[collect-surprise] pages={len(urls)} timeout={args.timeout}s sleep={args.sleep}s")
    for i, url in enumerate(urls, 1):
        print(f"[collect-surprise] {i}/{len(urls)} {url}")
        try:
            parsed = extract_from_url(
                url,
                timeout=args.timeout,
                user_agent=args.user_agent,
                retries=args.retries,
                retry_wait=args.retry_wait,
            )
        except Exception as e:
            print(f"[collect-surprise] skip fetch error: {e}")
            polite_sleep(args.sleep, args.jitter)
            continue
        for seed in parsed:
            key = (seed.ticker, seed.signal_date, seed.signal_type)
            if key in seen:
                continue
            seen.add(key)
            seeds.append(seed)
        polite_sleep(args.sleep, args.jitter)
    output.write_text(build_markdown(seeds, urls, args.date), encoding="utf-8")
    print(f"wrote {display_path(output)} seeds={len(seeds)} pages={len(urls)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
