#!/usr/bin/env python3
"""Create compact OHLC chart-window reviews for short watch candidates."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
JST = timezone(timedelta(hours=9))
CACHE = ROOT / ".cache/market-outcomes/yahoo-chart-cache.json"
DEFAULT_READINESS = ROOT / "topics/investment-research/inbox/{date}-short-readiness-data.json"
OUTPUT = ROOT / "topics/investment-research/inbox/{date}-short-chart-window-review.md"
OUTPUT_JSON = ROOT / "topics/investment-research/inbox/{date}-short-chart-window-data.json"


def load_price_index() -> dict[str, list[dict]]:
    raw = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    by_ticker: dict[str, dict[str, dict]] = {}
    for key, rows in raw.items():
        ticker = key.split(":", 1)[0].split(".", 1)[0]
        by_ticker.setdefault(ticker, {})
        for row in rows:
            if row.get("date") and row.get("close") is not None:
                by_ticker[ticker][row["date"]] = row
    return {ticker: [rows[d] for d in sorted(rows)] for ticker, rows in by_ticker.items()}


def row_at_or_after(rows: list[dict], date: str) -> int | None:
    for idx, row in enumerate(rows):
        if row["date"] >= date:
            return idx
    return None


def pct(a: float | None, b: float | None) -> float | None:
    if a is None or b in (None, 0):
        return None
    return (a / b - 1) * 100


def fmt_pct(value: float | None) -> str:
    return "unknown" if value is None else f"{value:+.2f}%"


def fmt_price(value: float | None) -> str:
    return "unknown" if value is None else f"{float(value):.2f}"


def candle(row: dict) -> str:
    o, h, l, c = (row.get(k) for k in ("open", "high", "low", "close"))
    if None in (o, h, l, c) or not o or h == l:
        return "unknown"
    close_location = (c - l) / (h - l)
    body_pct = abs(c - o) / o * 100
    upper_wick_pct = (h - max(o, c)) / o * 100
    if c < o and close_location <= 0.35:
        return "bearish_close"
    if c < o:
        return "bearish_body"
    if upper_wick_pct >= max(body_pct, 1.0) and close_location <= 0.5:
        return "upper_wick_reversal"
    if c > o and close_location >= 0.65:
        return "bullish_close"
    return "mixed"


def review_for(row: dict, prices: list[dict], before: int, after: int) -> dict:
    idx = row_at_or_after(prices, row["signalDate"])
    if idx is None:
        return {"status": "missing_prices", "window": []}
    base = prices[idx]
    start = max(0, idx - before)
    end = min(len(prices), idx + after + 1)
    window = prices[start:end]
    base_close = base.get("close")
    base_low = base.get("low")
    rows = []
    for i, p in enumerate(window, start=start):
        rows.append({
            "date": p.get("date"),
            "relDay": i - idx,
            "open": p.get("open"),
            "high": p.get("high"),
            "low": p.get("low"),
            "close": p.get("close"),
            "volume": p.get("volume"),
            "closeVsBasePct": pct(p.get("close"), base_close),
            "lowVsBaseLowPct": pct(p.get("low"), base_low),
            "candle": candle(p),
        })
    post = [p for p in rows if p["relDay"] > 0]
    pre = [p for p in rows if p["relDay"] < 0]
    breakdown_days = [p for p in post if p["lowVsBaseLowPct"] is not None and p["lowVsBaseLowPct"] <= -1]
    rebound_days = [p for p in post if p["closeVsBasePct"] is not None and p["closeVsBasePct"] >= 1]
    bearish_days = [p for p in post[:5] if p["candle"] in {"bearish_close", "bearish_body"}]
    return {
        "status": "ok",
        "baseDate": base.get("date"),
        "baseClose": base_close,
        "postBreakdownDays": len(breakdown_days),
        "postReboundDays": len(rebound_days),
        "bearishDaysFirst5": len(bearish_days),
        "followThrough": "yes" if len(breakdown_days) >= 2 and len(bearish_days) >= 2 else "mixed_or_no",
        "reboundRisk": "yes" if rebound_days else "no",
        "window": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate short chart window review.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--before", type=int, default=5)
    parser.add_argument("--after", type=int, default=10)
    parser.add_argument("--include", default="high,medium,medium_low_liquidity,low_liquidity_avoid,medium_rebound_risk,watch_needs_confirmation")
    args = parser.parse_args()
    include = {x.strip() for x in args.include.split(",") if x.strip()}
    input_path = args.input or Path(str(DEFAULT_READINESS).format(date=args.date))
    prices = load_price_index()
    readiness = json.loads(input_path.read_text(encoding="utf-8"))["rows"]
    candidates = [r for r in readiness if r.get("shortReadiness") in include and r.get("shortUseCase") == "short_entry_candidate"]
    candidates.sort(key=lambda r: ({"high": 0, "medium": 1, "medium_low_liquidity": 2}.get(r.get("shortReadiness"), 9), r.get("ticker", "")))

    data_rows = []
    lines = [
        f"# {args.date} Short Chart Window Review",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {args.date}",
        "- mode: short-chart-window-review",
        f"- sourceLog: {input_path.relative_to(ROOT / 'topics/investment-research')}",
        "- caution: 日足OHLCVによる過去検証。売買助言ではない。実運用では分足、板、売建可否、逆日歩を別確認する。",
        "",
        "## Summary",
        f"- candidates: {len(candidates)}",
        f"- includeReadiness: {', '.join(sorted(include))}",
        "",
    ]
    for row in candidates:
        review = review_for(row, prices.get(row["ticker"], []), args.before, args.after)
        data_rows.append({
            "ticker": row.get("ticker"),
            "company": row.get("company"),
            "signalDate": row.get("signalDate"),
            "category": row.get("category"),
            "signalType": row.get("signalType"),
            "shortReadiness": row.get("shortReadiness"),
            "shortRank": row.get("shortRank"),
            "borrowStatus": row.get("borrow_borrowStatus"),
            "liquidityBucket": row.get("liquidityBucket"),
            "t1": row.get("t1"),
            "t5": row.get("t5"),
            "t20": row.get("t20"),
            "review": review,
        })
        lines.extend([
            f"## {row['ticker']} {row['signalDate']} {row['category']} / {row['signalType']}",
            f"- shortReadiness: {row.get('shortReadiness')}",
            f"- shortRank: {row.get('shortRank')}",
            f"- borrowStatus: {row.get('borrow_borrowStatus')} / liquidity: {row.get('liquidityBucket')}",
            f"- ruleOutcome: T+1={row.get('t1')} / T+5={row.get('t5')} / T+20={row.get('t20')}",
        ])
        if review["status"] != "ok":
            lines.append("- chartStatus: missing_prices")
            lines.append("")
            continue
        lines.extend([
            f"- base: {review['baseDate']} close {fmt_price(review['baseClose'])}",
            f"- followThrough: {review['followThrough']}",
            f"- reboundRiskWithinWindow: {review['reboundRisk']}",
            f"- postBreakdownDays: {review['postBreakdownDays']}",
            f"- postReboundDays: {review['postReboundDays']}",
            f"- bearishDaysFirst5: {review['bearishDaysFirst5']}",
            "",
            "| rel | date | O | H | L | C | C/base | L/baseLow | candle | volume |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |",
        ])
        for p in review["window"]:
            lines.append(
                f"| {p['relDay']} | {p['date']} | {fmt_price(p['open'])} | {fmt_price(p['high'])} | {fmt_price(p['low'])} | {fmt_price(p['close'])} | {fmt_pct(p['closeVsBasePct'])} | {fmt_pct(p['lowVsBaseLowPct'])} | {p['candle']} | {p.get('volume') or 'unknown'} |"
            )
        lines.extend([
            "",
            "### Read",
            "- 弱い足が続くか、翌日以降すぐ戻すかを確認するための窓。",
            "- `followThrough=yes` ならT+1/T+5監視に向き、`reboundRisk=yes` なら戻り売り待ちへ回す。",
            "",
        ])
    output = Path(str(OUTPUT).format(date=args.date))
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    output_json = Path(str(OUTPUT_JSON).format(date=args.date))
    output_json.write_text(json.dumps({
        "createdAt": datetime.now(JST).replace(microsecond=0).isoformat(),
        "mode": "short-chart-window-review",
        "caution": "日足OHLCVによる過去検証。売買助言ではない。",
        "includeReadiness": sorted(include),
        "before": args.before,
        "after": args.after,
        "rows": data_rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output.relative_to(ROOT)} and {output_json.relative_to(ROOT)} candidates={len(candidates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
