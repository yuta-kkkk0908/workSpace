#!/usr/bin/env python3
"""Build rough daily market-context metadata for backtest signals.

The goal is not a precise trading model. It creates a broad context label for
research logs: was the reaction day generally a tailwind, headwind, or mixed?
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache/market-outcomes/yahoo-index-context-cache.json"
JST = timezone(timedelta(hours=9))
DEFAULT_OUTPUT = ROOT / "topics/investment-research/inbox/{date}-market-context-data.json"

sys.path.insert(0, str(ROOT / "scripts"))
import analyze_market_outcomes as outcomes  # noqa: E402

SYMBOLS = {
    "nikkei225": "^N225",
    "topix": "^TOPX",
    "sp500": "^GSPC",
    "nasdaq": "^IXIC",
    "usdjpy": "JPY=X",
}


def epoch(date: str) -> int:
    return int(datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=JST).timestamp())


def load_cache() -> dict:
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_symbol(symbol: str, start: str, end: str, cache: dict, cache_only: bool = False) -> list[dict]:
    key = f"{symbol}:{start}:{end}"
    if key in cache:
        return cache[key]
    if cache_only:
        return []
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{symbol}?period1={epoch(start)}&period2={epoch(end)}&interval=1d"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        cache[key] = []
        return []
    result = (data.get("chart", {}).get("result") or [None])[0]
    rows = []
    if result:
        timestamps = result.get("timestamp") or []
        quote = (result.get("indicators", {}).get("quote") or [{}])[0]
        adj = (result.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or []
        close = quote.get("close") or []
        for idx, ts in enumerate(timestamps):
            c = adj[idx] if idx < len(adj) and adj[idx] is not None else (close[idx] if idx < len(close) else None)
            if c is None or (isinstance(c, float) and math.isnan(c)):
                continue
            rows.append({"date": datetime.fromtimestamp(ts, JST).strftime("%Y-%m-%d"), "close": round(float(c), 4)})
    cache[key] = rows
    time.sleep(0.1)
    return rows


def pct(current: float | None, prev: float | None) -> float | None:
    if current is None or prev in (None, 0):
        return None
    return round((current / prev - 1) * 100, 3)


def row_at_or_after(rows: list[dict], date: str) -> tuple[int, dict] | tuple[None, None]:
    for idx, row in enumerate(rows):
        if row["date"] >= date:
            return idx, row
    return None, None


def prev_row(rows: list[dict], idx: int | None) -> dict | None:
    if idx is None or idx <= 0:
        return None
    return rows[idx - 1]


def add_days(date: str, days: int) -> str:
    return (datetime.strptime(date, "%Y-%m-%d").date() + timedelta(days=days)).strftime("%Y-%m-%d")


def reaction_date(signal_date: str, session: str, jp_rows: list[dict]) -> str:
    if session in {"after_close", "after_close_inferred", "eod_report_inferred"}:
        target = add_days(signal_date, 1)
    else:
        target = signal_date
    _, row = row_at_or_after(jp_rows, target)
    return row["date"] if row else signal_date


def close_map(rows: list[dict]) -> dict[str, float]:
    return {r["date"]: r["close"] for r in rows}


def previous_trading_date(rows: list[dict], date: str) -> str | None:
    idx, _ = row_at_or_after(rows, date)
    prev = prev_row(rows, idx)
    return prev["date"] if prev else None


def previous_us_date(us_rows: list[dict], jp_reaction_date: str) -> str | None:
    # US previous session available before the Japanese market open.
    candidates = [r for r in us_rows if r["date"] < jp_reaction_date]
    return candidates[-1]["date"] if candidates else None


def classify(jp: float | None, topix: float | None, spx_prev: float | None, nasdaq_prev: float | None, usd: float | None) -> str:
    positives = 0
    negatives = 0
    for value, threshold in ((jp, 0.4), (topix, 0.3), (spx_prev, 0.4), (nasdaq_prev, 0.5)):
        if value is None:
            continue
        if value >= threshold:
            positives += 1
        elif value <= -threshold:
            negatives += 1
    if usd is not None:
        if usd >= 0.4:
            positives += 0.5
        elif usd <= -0.4:
            negatives += 0.5
    if positives >= 2 and negatives == 0:
        return "tailwind_or_positive"
    if negatives >= 2 and positives == 0:
        return "headwind_or_negative"
    if positives > 0 and negatives > 0:
        return "mixed"
    return "neutral_or_unclear"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build rough daily market-context metadata.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    parser.add_argument("--outcome", type=Path, default=None)
    parser.add_argument("--cache-only", action="store_true", help="Use existing Yahoo index cache only; do not fetch network data.")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    output = args.output or Path(str(DEFAULT_OUTPUT).format(date=args.date))
    outcomes.OUTCOME = args.outcome or Path(str(outcomes.DEFAULT_OUTCOME).format(date=args.date))

    rows = outcomes.parse_outcomes()
    start = min(r["signalDate"] for r in rows)
    end = max(r["signalDate"] for r in rows)
    fetch_start = add_days(start, -10)
    fetch_end = add_days(end, 35)
    cache = load_cache()
    series = {name: fetch_symbol(symbol, fetch_start, fetch_end, cache, cache_only=args.cache_only) for name, symbol in SYMBOLS.items()}
    save_cache(cache)

    nikkei = series["nikkei225"]
    topix = series["topix"]
    spx = series["sp500"]
    nasdaq = series["nasdaq"]
    usdjpy = series["usdjpy"]
    maps = {k: close_map(v) for k, v in series.items()}

    context_by_reaction = {}
    for r in rows:
        rd = reaction_date(r["signalDate"], r["session"], nikkei)
        if rd in context_by_reaction:
            continue
        prev_jp = previous_trading_date(nikkei, rd)
        us_prev = previous_us_date(spx, rd)
        us_prev2 = previous_trading_date(spx, us_prev) if us_prev else None
        nikkei_pct = pct(maps["nikkei225"].get(rd), maps["nikkei225"].get(prev_jp or ""))
        topix_pct = pct(maps["topix"].get(rd), maps["topix"].get(prev_jp or ""))
        spx_pct = pct(maps["sp500"].get(us_prev or ""), maps["sp500"].get(us_prev2 or ""))
        nasdaq_pct = pct(maps["nasdaq"].get(us_prev or ""), maps["nasdaq"].get(us_prev2 or ""))
        usd_pct = pct(maps["usdjpy"].get(us_prev or ""), maps["usdjpy"].get(us_prev2 or ""))
        context_by_reaction[rd] = {
            "reactionDate": rd,
            "previousJapanTradingDate": prev_jp,
            "previousUSDate": us_prev,
            "nikkei225Pct": nikkei_pct,
            "topixPct": topix_pct,
            "sp500PrevPct": spx_pct,
            "nasdaqPrevPct": nasdaq_pct,
            "usdjpyPrevPct": usd_pct,
            "marketContext": classify(nikkei_pct, topix_pct, spx_pct, nasdaq_pct, usd_pct),
        }

    out_rows = []
    for r in rows:
        rd = reaction_date(r["signalDate"], r["session"], nikkei)
        c = context_by_reaction[rd]
        out_rows.append({
            "ticker": r["ticker"],
            "signalDate": r["signalDate"],
            "session": r["session"],
            "reactionDate": rd,
            "marketContext": c["marketContext"],
            "contextSource": "yahoo_finance_index_rough",
            "confidence": "rough_index_based",
            "nikkei225Pct": c["nikkei225Pct"],
            "topixPct": c["topixPct"],
            "sp500PrevPct": c["sp500PrevPct"],
            "nasdaqPrevPct": c["nasdaqPrevPct"],
            "usdjpyPrevPct": c["usdjpyPrevPct"],
        })

    output.write_text(json.dumps({
        "date": args.date,
        "cacheOnly": args.cache_only,
        "source": "Yahoo Finance chart API via query1.finance.yahoo.com",
        "caution": "指数終値ベースの粗い地合い分類。個別銘柄の売買助言ではない。",
        "rows": out_rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output.relative_to(ROOT)} rows={len(out_rows)} uniqueReactionDates={len(context_by_reaction)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
