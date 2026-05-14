#!/usr/bin/env python3
"""Build rough technical indicator context for investment outcome rows.

Uses cached Yahoo Finance OHLCV rows produced by fill_market_outcomes.py. If a
row is not available in cache, the script leaves the technical fields unknown
rather than fetching fresh data. This keeps the rule-check layer reproducible.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache/market-outcomes/yahoo-chart-cache.json"
JST = timezone(timedelta(hours=9))
DEFAULT_OUTPUT_JSON = ROOT / "topics/investment-research/inbox/{date}-technical-context-data.json"
DEFAULT_OUTPUT_MD = ROOT / "topics/investment-research/inbox/{date}-technical-context-summary.md"

sys.path.insert(0, str(ROOT / "scripts"))
import analyze_market_outcomes as outcomes  # noqa: E402


def load_price_index() -> dict[str, list[dict]]:
    if not CACHE.exists():
        return {}
    raw = json.loads(CACHE.read_text(encoding="utf-8"))
    by_ticker: dict[str, dict[str, dict]] = defaultdict(dict)
    for key, rows in raw.items():
        symbol = key.split(":", 1)[0]
        ticker = symbol.split(".", 1)[0]
        if not rows:
            continue
        for row in rows:
            if not row.get("date") or row.get("close") in (None, 0):
                continue
            by_ticker[ticker][row["date"]] = row
    return {ticker: [rows[d] for d in sorted(rows)] for ticker, rows in by_ticker.items()}


def epoch(date: str) -> int:
    return int(datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=JST).timestamp())


def add_days(date: str, days: int) -> str:
    return (datetime.strptime(date, "%Y-%m-%d").date() + timedelta(days=days)).strftime("%Y-%m-%d")


def has_enough_history(rows: list[dict], signal_date: str, min_rows: int = 90) -> bool:
    idx, _ = row_at_or_after(rows, signal_date)
    return idx is not None and idx + 1 >= min_rows


def fetch_prices(ticker: str, start: str, end: str, cache: dict) -> list[dict]:
    for suffix in (".T", ".N", ".S", ".F"):
        symbol = f"{ticker}{suffix}"
        key = f"{symbol}:{start}:{end}"
        if key in cache:
            return cache[key]
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{symbol}?period1={epoch(start)}&period2={epoch(end)}&interval=1d"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            cache[key] = []
            continue
        result = (data.get("chart", {}).get("result") or [None])[0]
        rows = []
        if result:
            timestamps = result.get("timestamp") or []
            quote = (result.get("indicators", {}).get("quote") or [{}])[0]
            adj = (result.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or []
            open_ = quote.get("open") or []
            high = quote.get("high") or []
            low = quote.get("low") or []
            close = quote.get("close") or []
            volume = quote.get("volume") or []
            for idx, ts in enumerate(timestamps):
                c = adj[idx] if idx < len(adj) and adj[idx] is not None else (close[idx] if idx < len(close) else None)
                if c is None or (isinstance(c, float) and math.isnan(c)):
                    continue
                o = open_[idx] if idx < len(open_) and open_[idx] is not None else c
                h = high[idx] if idx < len(high) and high[idx] is not None else c
                l = low[idx] if idx < len(low) and low[idx] is not None else c
                v = volume[idx] if idx < len(volume) and volume[idx] is not None else None
                rows.append({
                    "date": datetime.fromtimestamp(ts, JST).strftime("%Y-%m-%d"),
                    "open": round(float(o), 4),
                    "high": round(float(h), 4),
                    "low": round(float(l), 4),
                    "close": round(float(c), 4),
                    "volume": int(v) if v is not None else None,
                })
        cache[key] = rows
        time.sleep(0.12)
        if rows:
            return rows
    return []


def extend_price_index(rows: list[dict[str, str]], price_index: dict[str, list[dict]], cache_only: bool = False) -> dict[str, list[dict]]:
    if cache_only:
        return price_index
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    needed: dict[str, tuple[str, str]] = {}
    for row in rows:
        ticker = row["ticker"]
        signal_date = row["signalDate"]
        if has_enough_history(price_index.get(ticker, []), signal_date):
            continue
        start = add_days(signal_date, -140)
        end = add_days(signal_date, 50)
        cur = needed.get(ticker)
        if cur is None:
            needed[ticker] = (start, end)
        else:
            needed[ticker] = (min(cur[0], start), max(cur[1], end))
    for ticker, (start, end) in sorted(needed.items()):
        fetch_prices(ticker, start, end, cache)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return load_price_index()


def row_at_or_after(rows: list[dict], date: str) -> tuple[int | None, dict | None]:
    for idx, row in enumerate(rows):
        if row["date"] >= date:
            return idx, row
    return None, None


def sma(values: list[float], length: int) -> float | None:
    if len(values) < length:
        return None
    return sum(values[-length:]) / length


def ema_series(values: list[float], length: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (length + 1)
    out = [values[0]]
    for value in values[1:]:
        out.append(value * alpha + out[-1] * (1 - alpha))
    return out


def rsi(values: list[float], length: int = 14) -> float | None:
    if len(values) <= length:
        return None
    gains = []
    losses = []
    for prev, cur in zip(values[-length - 1:-1], values[-length:]):
        diff = cur - prev
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))
    avg_gain = sum(gains) / length
    avg_loss = sum(losses) / length
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def pct(a: float | None, b: float | None) -> float | None:
    if a is None or b in (None, 0):
        return None
    return (a / b - 1) * 100


def bucket_price_vs_ma(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= 5:
        return "far_above"
    if value >= 1:
        return "above"
    if value > -1:
        return "near"
    if value > -5:
        return "below"
    return "far_below"


def bucket_rsi(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= 80:
        return "extreme_overbought"
    if value >= 70:
        return "overbought"
    if value >= 55:
        return "strong"
    if value >= 45:
        return "neutral"
    if value >= 30:
        return "weak"
    return "oversold"


def bucket_bb(z: float | None) -> str:
    if z is None:
        return "unknown"
    if z >= 2:
        return "above_upper_band"
    if z >= 1:
        return "upper_half"
    if z > -1:
        return "middle"
    if z > -2:
        return "lower_half"
    return "below_lower_band"


def slope_bucket(short: float | None, long: float | None, prev_short: float | None, prev_long: float | None) -> str:
    if None in (short, long, prev_short, prev_long):
        return "unknown"
    short_up = short > prev_short
    long_up = long > prev_long
    if short > long and short_up and long_up:
        return "bullish_alignment"
    if short > long and short_up:
        return "short_term_bullish"
    if short < long and not short_up and not long_up:
        return "bearish_alignment"
    if short < long and not short_up:
        return "short_term_bearish"
    return "mixed"


def macd_bucket(macd: float | None, signal: float | None, hist: float | None) -> str:
    if macd is None or signal is None or hist is None:
        return "unknown"
    if macd > signal and hist > 0:
        return "bullish"
    if macd < signal and hist < 0:
        return "bearish"
    return "mixed"


def classify_pattern(ctx: dict) -> str:
    candle = ctx.get("t1Candle", "unknown")
    ma = ctx.get("maTrend", "unknown")
    rsi_b = ctx.get("rsi14Bucket", "unknown")
    bb = ctx.get("bollingerBucket", "unknown")
    macd = ctx.get("macdBucket", "unknown")
    breakout = ctx.get("breakout20", "unknown")
    if candle in {"bearish_close", "upper_wick_reversal", "gap_up_upper_wick"} and rsi_b in {"overbought", "extreme_overbought"} and bb in {"above_upper_band", "upper_half"}:
        return "overbought_reversal_watch"
    if candle == "bearish_close" and ma in {"bearish_alignment", "short_term_bearish"}:
        return "bearish_trend_continuation"
    if candle in {"bullish_close", "bullish_body"} and ma in {"bullish_alignment", "short_term_bullish"} and macd == "bullish":
        return "trend_follow_long_watch"
    if breakout == "high_breakout" and candle in {"bullish_close", "gap_up_upper_wick"}:
        return "breakout_watch"
    if breakout == "low_breakdown" and candle in {"bearish_close", "bearish_body"}:
        return "breakdown_short_watch"
    if ma == "bearish_alignment" and macd == "bearish":
        return "technical_short_bias"
    if ma == "bullish_alignment" and macd == "bullish":
        return "technical_long_bias"
    return "mixed_or_unclassified"


def metrics_for(rows: list[dict], signal_date: str, t1_candle: str) -> dict:
    idx, base = row_at_or_after(rows, signal_date)
    if idx is None or base is None:
        return {"technicalStatus": "missing_price_rows"}
    hist = rows[: idx + 1]
    closes = [float(r["close"]) for r in hist if r.get("close") is not None]
    if len(closes) < 26:
        return {"technicalStatus": "insufficient_history", "baseDate": base["date"]}
    close = closes[-1]
    ma5 = sma(closes, 5)
    ma25 = sma(closes, 25)
    ma75 = sma(closes, 75)
    prev_closes = closes[:-5] if len(closes) > 30 else closes[:-1]
    prev_ma5 = sma(prev_closes, 5)
    prev_ma25 = sma(prev_closes, 25)
    ma_trend = slope_bucket(ma5, ma25, prev_ma5, prev_ma25)
    rsi14 = rsi(closes, 14)
    ema12 = ema_series(closes, 12)
    ema26 = ema_series(closes, 26)
    macd_line = None
    macd_signal = None
    macd_hist = None
    if len(ema12) == len(ema26):
        macd_values = [a - b for a, b in zip(ema12, ema26)]
        sig = ema_series(macd_values, 9)
        macd_line = macd_values[-1]
        macd_signal = sig[-1]
        macd_hist = macd_line - macd_signal
    bb_z = None
    if len(closes) >= 20:
        last20 = closes[-20:]
        mean20 = statistics.mean(last20)
        sd20 = statistics.pstdev(last20)
        if sd20:
            bb_z = (close - mean20) / sd20
    prior20 = closes[-21:-1] if len(closes) >= 21 else closes[:-1]
    breakout = "unknown"
    if prior20:
        if close >= max(prior20):
            breakout = "high_breakout"
        elif close <= min(prior20):
            breakout = "low_breakdown"
        else:
            breakout = "inside_20d_range"
    ctx = {
        "technicalStatus": "ok",
        "baseDate": base["date"],
        "close": round(close, 4),
        "ma5": round(ma5, 4) if ma5 is not None else None,
        "ma25": round(ma25, 4) if ma25 is not None else None,
        "ma75": round(ma75, 4) if ma75 is not None else None,
        "closeVsMA5Pct": round(pct(close, ma5), 3) if ma5 else None,
        "closeVsMA25Pct": round(pct(close, ma25), 3) if ma25 else None,
        "closeVsMA75Pct": round(pct(close, ma75), 3) if ma75 else None,
        "closeVsMA25Bucket": bucket_price_vs_ma(pct(close, ma25) if ma25 else None),
        "maTrend": ma_trend,
        "rsi14": round(rsi14, 2) if rsi14 is not None else None,
        "rsi14Bucket": bucket_rsi(rsi14),
        "macd": round(macd_line, 4) if macd_line is not None else None,
        "macdSignal": round(macd_signal, 4) if macd_signal is not None else None,
        "macdHist": round(macd_hist, 4) if macd_hist is not None else None,
        "macdBucket": macd_bucket(macd_line, macd_signal, macd_hist),
        "bollingerZ20": round(bb_z, 3) if bb_z is not None else None,
        "bollingerBucket": bucket_bb(bb_z),
        "breakout20": breakout,
        "t1Candle": t1_candle,
    }
    ctx["technicalPattern"] = classify_pattern(ctx)
    return ctx


def main() -> int:
    parser = argparse.ArgumentParser(description="Build rough technical indicator context.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    parser.add_argument("--outcome", type=Path, default=None)
    parser.add_argument("--cache-only", action="store_true", help="Use existing Yahoo cache only; do not fetch missing rows.")
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    args = parser.parse_args()
    output_json = args.output_json or Path(str(DEFAULT_OUTPUT_JSON).format(date=args.date))
    output_md = args.output_md or Path(str(DEFAULT_OUTPUT_MD).format(date=args.date))
    outcomes.OUTCOME = args.outcome or Path(str(outcomes.DEFAULT_OUTCOME).format(date=args.date))

    rows = outcomes.parse_outcomes()
    price_index = load_price_index()
    price_index = extend_price_index(rows, price_index, cache_only=args.cache_only)
    out_rows = []
    for row in rows:
        ticker = row["ticker"]
        ctx = metrics_for(price_index.get(ticker, []), row["signalDate"], row.get("t1Candle", "unknown"))
        out_rows.append({
            "ticker": ticker,
            "signalDate": row["signalDate"],
            "category": row.get("category", "unknown"),
            "signalType": row.get("signalType", "unknown"),
            "expected": row.get("expected", "unknown"),
            **ctx,
        })
    counts = Counter(r.get("technicalPattern", r.get("technicalStatus", "unknown")) for r in out_rows)
    status_counts = Counter(r.get("technicalStatus", "unknown") for r in out_rows)
    output_json.write_text(json.dumps({
        "date": args.date,
        "source": "Cached Yahoo Finance OHLCV from .cache/market-outcomes/yahoo-chart-cache.json",
        "createdAt": datetime.now(JST).replace(microsecond=0).isoformat(),
        "caution": "日足ベースの粗いテクニカル文脈。発表時刻、場中織り込み、分割補正、流動性は未精査。売買助言ではない。",
        "rows": out_rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"# {args.date} Technical Context Summary",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {args.date}",
        "- mode: technical-context-fill",
        "- sourceData: cached Yahoo Finance OHLCV",
        f"- cacheOnly: {args.cache_only}",
        "- caution: 日足ベースの粗いテクニカル文脈。売買助言ではない。",
        "",
        "## Summary",
        f"- analyzedRows: {len(out_rows)}",
    ]
    for k, v in status_counts.most_common():
        lines.append(f"- technicalStatus.{k}: {v}")
    lines.extend(["", "## Technical Pattern Counts"])
    for k, v in counts.most_common():
        lines.append(f"- {k}: {v}")
    lines.extend(["", "## Short-Side Focus"])
    for pattern in ["bearish_trend_continuation", "breakdown_short_watch", "technical_short_bias", "overbought_reversal_watch"]:
        examples = [r for r in out_rows if r.get("technicalPattern") == pattern][:10]
        lines.append(f"### {pattern}")
        if not examples:
            lines.append("- none")
            continue
        for r in examples:
            lines.append(f"- {r['ticker']} {r['signalDate']} {r['category']} {r['signalType']} RSI={r.get('rsi14')} MA={r.get('maTrend')} MACD={r.get('macdBucket')} BB={r.get('bollingerBucket')}")
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {output_json.relative_to(ROOT)} rows={len(out_rows)}")
    print(f"wrote {output_md.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
