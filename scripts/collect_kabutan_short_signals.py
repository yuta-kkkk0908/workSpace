#!/usr/bin/env python3
"""Collect rough short-side signal seeds from Kabutan negative reaction pages.

Targets public Kabutan articles such as opening topic stocks, negative material
articles, and sold-stock summaries. It stores concise secondary-source seeds for
rough backtesting, not trading advice.
"""
from __future__ import annotations

import argparse
import html
import re
import time
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
DEFAULT_OUTPUT = ROOT / "topics/investment-research/inbox/{date}-six-month-rough-backtest-batch-6-short-negative.md"
DEFAULT_URLS = [
    "https://s.kabutan.jp/news/n202602030330/",
    "https://s.kabutan.jp/news/n202602040787/",
    "https://s.kabutan.jp/news/n202602060396/",
    "https://s.kabutan.jp/news/k202602120493/",
    "https://s.kabutan.jp/news/n202603120341/",
    "https://s.kabutan.jp/news/n202603130367/",
    "https://s.kabutan.jp/news/n202603300505/",
    "https://s.kabutan.jp/news/k202603180012/",
    "https://s.kabutan.jp/news/n202604010419/",
    "https://s.kabutan.jp/news/n202604070238/",
    "https://s.kabutan.jp/news/n202604100049/",
    "https://s.kabutan.jp/news/n202604150253/",
    "https://s.kabutan.jp/news/n202604150300/",
    "https://s.kabutan.jp/news/n202604150434/",
    "https://s.kabutan.jp/news/n202604161003/",
    "https://s.kabutan.jp/news/n202604240345/",
    "https://s.kabutan.jp/news/n202604270428/",
    "https://s.kabutan.jp/news/n202604270706/",
    "https://s.kabutan.jp/news/n202604270815/",
    "https://s.kabutan.jp/news/n202604270834/",
    "https://s.kabutan.jp/news/n202605010393/",
    "https://s.kabutan.jp/news/n202605071035/",
    "https://s.kabutan.jp/news/n202510310521/",
    "https://s.kabutan.jp/news/n202511040654/",
    "https://s.kabutan.jp/news/n202511060844/",
    "https://s.kabutan.jp/news/n202511140576/",
    "https://s.kabutan.jp/news/n202508130553/",
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

NEGATIVE_KEYWORDS = (
    "下方修正", "減配", "一転赤字", "赤字", "減益", "弱い", "嫌気", "売り材料", "売り気配",
    "大幅反落", "大幅続落", "続落", "ストップ安", "下落", "減損", "希薄化", "売り出し", "売出",
    "自己株処分", "第三者割当", "公募", "不祥事", "調査報告", "遅延", "撤回", "格下げ",
)
SKIP_POSITIVE_IF_ONLY = ("好感", "買い材料", "特別買い気配", "ストップ高", "上方修正", "増配", "最高益")


@dataclass(frozen=True)
class Seed:
    ticker: str
    company: str
    signal_date: str
    published_at: str
    category: str
    signal_type: str
    expected: str
    long_rank: str
    short_rank: str
    summary: str
    source: str
    article_date: str


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8", "ignore")
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"</(p|li|div|h[1-6]|tr)>", "\n", raw, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text


def discover_recent_urls(limit: int) -> list[str]:
    if limit <= 0:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for page in DISCOVERY_PAGES:
        try:
            raw = urllib.request.urlopen(
                urllib.request.Request(page, headers={"User-Agent": "Mozilla/5.0"}),
                timeout=15,
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
    return found


def article_date(text: str, url: str) -> str | None:
    m = re.search(r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日", text)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"n(20\d{2})(\d{2})(\d{2})", url)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"k(20\d{2})(\d{2})(\d{2})", url)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def material_date(block: str, art_date: str) -> str:
    # Opening articles often say "30日に" for the prior material date.
    base = datetime.strptime(art_date, "%Y-%m-%d").date()
    m = re.search(r"(\d{1,2})日に", block)
    if not m:
        return art_date
    day = int(m.group(1))
    year = base.year
    month = base.month
    if day > base.day:
        # Previous month reference, e.g. May 1 article says Apr 30.
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    try:
        return date(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return art_date


def is_negative(block: str) -> bool:
    has_neg = any(k in block for k in NEGATIVE_KEYWORDS)
    has_pos = any(k in block for k in SKIP_POSITIVE_IF_ONLY)
    # Positive words can coexist with negative words in mixed cases; keep if negative is explicit.
    if has_neg:
        return True
    return False


def clean_summary(block: str) -> str:
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    compact = " ".join(lines[:5])
    compact = re.sub(r"\s+", " ", compact)
    return compact[:260]


def classify(block: str) -> tuple[str, str, str, str, str]:
    if "売り出し" in block or "売出" in block or "自己株処分" in block or "公募" in block or "第三者割当" in block:
        return "capital_policy", "offering_or_dilution", "down", "C", "B"
    if "減配" in block and ("一転赤字" in block or "赤字" in block or "下方修正" in block):
        return "earnings_negative", "downward_revision_dividend_cut", "down", "C", "A-"
    if "減配" in block:
        return "dividend_return", "dividend_cut", "down", "C", "B+"
    if "一転赤字" in block or "赤字" in block:
        return "earnings_negative", "downward_revision_to_loss", "down", "C", "A-"
    if "下方修正" in block:
        return "earnings_negative", "downward_revision", "down", "C", "B"
    if "減損" in block:
        return "earnings_negative", "impairment_loss", "down", "C", "B+"
    if "格下げ" in block:
        return "external_policy_macro", "analyst_downgrade", "down_or_unclear", "C", "B"
    if "遅延" in block or "撤回" in block or "調査報告" in block or "不祥事" in block:
        return "risk_event", "negative_business_or_governance_event", "down", "C", "B"
    if "減益" in block or "市場予想" in block or "コンセンサス" in block:
        return "earnings_negative", "weak_earnings_or_guidance", "down_or_unclear", "C", "B"
    return "technical_market_reaction", "negative_price_reaction", "down_or_unclear", "C", "C"


def split_blocks(text: str) -> list[str]:
    parts = re.split(r"\n?■", text)
    out = []
    for part in parts:
        if re.search(r"<([0-9]{4}|[0-9]{3}[A-Z])>", part):
            out.append(part.strip())
    if out:
        return out
    # Single-stock material pages do not always use ■ blocks.
    return [text]


def parse_block(block: str, url: str, art_date: str) -> Seed | None:
    m = re.search(r"([^\n<]{1,40})\s*<([0-9]{4}|[0-9]{3}[A-Z])>", block)
    if not m:
        return None
    company = m.group(1).strip(" ・　[]【】")
    ticker = m.group(2)
    if not is_negative(block):
        return None
    signal_date = material_date(block, art_date)
    category, signal_type, expected, long_rank, short_rank = classify(block)
    summary = clean_summary(block)
    return Seed(
        ticker=ticker,
        company=company,
        signal_date=signal_date,
        published_at=f"{signal_date}T15:30:00+09:00",
        category=category,
        signal_type=signal_type,
        expected=expected,
        long_rank=long_rank,
        short_rank=short_rank,
        summary=summary,
        source=url,
        article_date=art_date,
    )


def collect(urls: list[str], sleep: float) -> list[Seed]:
    seeds = []
    seen: set[tuple[str, str, str]] = set()
    for url in urls:
        text = fetch_text(url)
        art_date = article_date(text, url)
        if not art_date:
            continue
        for block in split_blocks(text):
            seed = parse_block(block, url, art_date)
            if not seed:
                continue
            key = (seed.ticker, seed.signal_date, seed.signal_type)
            if key in seen:
                continue
            seen.add(key)
            seeds.append(seed)
        time.sleep(sleep)
    return seeds


def build_markdown(seeds: list[Seed], urls: list[str], run_date: str) -> str:
    lines = [
        f"# {run_date} Six-Month Rough Backtest Batch 6 Short Negative",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {run_date}",
        "- mode: rough-backtest-short-expansion",
        "- ruleVersion: market-signal-v7-short-technical",
        "- sourceData: Kabutan negative reaction/material pages, concise secondary-source discovery",
        "- caution: 株探記事からの二次情報seed。価格結果は `scripts/fill_market_outcomes.py` で別途補完する。売買助言ではない。",
        "",
        "## Coverage Update",
        f"- sourcePages: {len(urls)}",
        f"- addedSeedsBeforeDedup: {len(seeds)}",
        "- target: short-side sample expansion for downward revision, dividend cut, dilution, weak earnings, risk event",
        "",
        "## Source Pages",
    ]
    for url in urls:
        lines.append(f"- {url}")
    lines.extend(["", "## Added Signals"])
    for idx, s in enumerate(seeds, 1):
        lines.extend([
            f"### rough6_{run_date.replace('-', '')}_{idx:03d}: {s.ticker} {s.company} {s.signal_type}",
            f"- ticker: {s.ticker}",
            f"- company: {s.company}",
            f"- signalDate: {s.signal_date} after close",
            f"- publishedAt: {s.published_at}",
            "- session: after_close",
            f"- articleDate: {s.article_date}",
            f"- disclosureCategory: {s.category}",
            f"- signalType: {s.signal_type}",
            f"- signalSummary: {s.summary}",
            f"- expectedDirection: {s.expected}",
            f"- longSignalRank: {s.long_rank}",
            f"- shortSignalRank: {s.short_rank}",
            "- materialityReason: 悪材料/弱反応ページから抽出。詳細は一次開示で後日確認する。",
            f"- source: {s.source}",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect Kabutan short-side rough backtest seeds.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--url", action="append", dest="urls")
    parser.add_argument("--sleep", type=float, default=0.3)
    parser.add_argument("--discover-latest", type=int, default=30, help="discover additional recent Kabutan URLs from index pages")
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
    extra = discover_recent_urls(args.discover_latest)
    if extra:
        known = set(urls)
        for u in extra:
            if u not in known:
                urls.append(u)
                known.add(u)
    seeds = collect(urls, args.sleep)
    output.write_text(build_markdown(seeds, urls, args.date), encoding="utf-8")
    print(f"wrote {display_path(output)} seeds={len(seeds)} pages={len(urls)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
