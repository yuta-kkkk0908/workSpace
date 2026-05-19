#!/usr/bin/env python3
"""Review avoid_short_rebound_risk rows for exclusion-rule refinement."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
JST = timezone(timedelta(hours=9))
DEFAULT_INPUT = ROOT / "topics/investment-research/inbox/{date}-short-readiness-data.json"
CACHE = ROOT / ".cache/market-outcomes/yahoo-chart-cache.json"
OUTPUT_MD = ROOT / "topics/investment-research/inbox/{date}-short-rebound-risk-review.md"
OUTPUT_JSON = ROOT / "topics/investment-research/inbox/{date}-short-rebound-risk-data.json"


def load_price_index() -> dict[str, list[dict]]:
    raw = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    by_ticker: dict[str, dict[str, dict]] = {}
    for key, prices in raw.items():
        ticker = key.split(":", 1)[0].split(".", 1)[0]
        by_ticker.setdefault(ticker, {})
        for row in prices:
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


def outcome_counts(rows: list[dict], field: str) -> str:
    c = Counter(row.get(field, "unknown") for row in rows)
    judged = c["win"] + c["loss"] + c["flat"]
    wr = c["win"] / judged * 100 if judged else 0
    return f"{c['win']}/{c['loss']}/{c['flat']} pending={c['pending']} wr={wr:.1f}%"


def window_review(row: dict, prices: list[dict], after: int = 10) -> dict:
    idx = row_at_or_after(prices, row.get("signalDate", ""))
    if idx is None:
        return {"status": "missing"}
    base = prices[idx]
    post = prices[idx + 1:idx + after + 1]
    base_close = base.get("close")
    base_low = base.get("low")
    if not post:
        return {"status": "no_post"}
    max_close_pct = max((pct(p.get("close"), base_close) for p in post), default=None)
    min_low_pct = min((pct(p.get("low"), base_low) for p in post), default=None)
    rebound_days = [p for p in post if (pct(p.get("close"), base_close) or -999) >= 1]
    breakdown_days = [p for p in post if (pct(p.get("low"), base_low) or 999) <= -1]
    return {
        "status": "ok",
        "baseDate": base.get("date"),
        "maxCloseVsBasePct": max_close_pct,
        "minLowVsBaseLowPct": min_low_pct,
        "reboundDays": len(rebound_days),
        "breakdownDays": len(breakdown_days),
        "firstReboundDate": rebound_days[0].get("date") if rebound_days else "",
    }


def exclusion_bucket(row: dict) -> str:
    reasons = set(row.get("shortReadinessReasons") or [])
    liquidity = row.get("liquidityBucket")
    borrow = row.get("borrow_borrowStatus")
    if "oversold_rebound_risk" in reasons and liquidity in {"high", "medium"} and borrow == "loan_margin":
        return "liquid_oversold_rebound_wait"
    if liquidity in {"low", "very_low"}:
        return "low_liquidity_buy_avoid"
    if borrow != "loan_margin":
        return "not_loan_margin_buy_avoid"
    if "volume_not_confirmed" in reasons:
        return "volume_not_confirmed_wait"
    return "rebound_risk_review"


def action_class(row: dict, review: dict) -> str:
    liquidity = row.get("liquidityBucket")
    borrow = row.get("borrow_borrowStatus")
    max_close = review.get("maxCloseVsBasePct")
    rebound_days = review.get("reboundDays") or 0
    breakdown_days = review.get("breakdownDays") or 0
    if borrow != "loan_margin":
        return "buy_avoid_no_system_short"
    if liquidity in {"low", "very_low"}:
        return "buy_avoid_low_liquidity"
    if max_close is not None and max_close >= 5:
        return "hard_no_short_strong_rebound"
    if rebound_days >= 5 and breakdown_days == 0:
        return "hard_no_short_rebound_dominant"
    if breakdown_days >= 5 and rebound_days == 0:
        return "return_short_wait_after_setup"
    if rebound_days >= 2:
        return "wait_for_failed_rebound"
    return "watch_retest_only"


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze short rebound-risk rows.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    parser.add_argument("--input", type=Path, default=None)
    args = parser.parse_args()

    input_path = args.input or Path(str(DEFAULT_INPUT).format(date=args.date))
    prices = load_price_index()
    data = json.loads(input_path.read_text(encoding="utf-8"))
    rows = [
        r for r in data.get("rows", [])
        if r.get("shortReadiness") == "avoid_short_rebound_risk" or r.get("shortUseCase") == "buy_avoid_rebound_risk"
    ]
    enriched = []
    for row in rows:
        review = window_review(row, prices.get(row.get("ticker", ""), []))
        enriched.append({
            **row,
            "reboundReview": review,
            "exclusionBucket": exclusion_bucket(row),
            "actionClass": action_class(row, review),
        })

    by_bucket: dict[str, list[dict]] = defaultdict(list)
    by_liquidity: dict[str, list[dict]] = defaultdict(list)
    by_borrow: dict[str, list[dict]] = defaultdict(list)
    by_action: dict[str, list[dict]] = defaultdict(list)
    for row in enriched:
        by_bucket[row["exclusionBucket"]].append(row)
        by_liquidity[row.get("liquidityBucket", "unknown")].append(row)
        by_borrow[row.get("borrow_borrowStatus", "unknown")].append(row)
        by_action[row["actionClass"]].append(row)

    output_json = Path(str(OUTPUT_JSON).format(date=args.date))
    output_json.write_text(json.dumps({
        "createdAt": datetime.now(JST).replace(microsecond=0).isoformat(),
        "mode": "short-rebound-risk-review",
        "caution": "売買助言ではなく、ショート除外/戻り売り待ちルールの検証ログ。",
        "rows": enriched,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        f"# {args.date} Short Rebound Risk Review",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {args.date}",
        "- mode: short-rebound-risk-review",
        f"- sourceLog: {input_path.relative_to(ROOT / 'topics/investment-research')}",
        "- caution: 売買助言ではなく、ショート除外/戻り売り待ちルールの検証ログ。",
        "",
        "## Summary",
        f"- rows: {len(enriched)}",
        f"- T+1: {outcome_counts(enriched, 't1')}",
        f"- T+5: {outcome_counts(enriched, 't5')}",
        f"- T+20: {outcome_counts(enriched, 't20')}",
        "",
        "## By Exclusion Bucket",
    ]
    for key, group in sorted(by_bucket.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines.append(f"- {key} ({len(group)}): T+1 {outcome_counts(group, 't1')} / T+5 {outcome_counts(group, 't5')} / T+20 {outcome_counts(group, 't20')}")

    lines.extend(["", "## By Action Class"])
    for key, group in sorted(by_action.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines.append(f"- {key} ({len(group)}): T+1 {outcome_counts(group, 't1')} / T+5 {outcome_counts(group, 't5')} / T+20 {outcome_counts(group, 't20')}")

    lines.extend(["", "## By Liquidity"])
    for key, group in sorted(by_liquidity.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines.append(f"- {key} ({len(group)}): T+1 {outcome_counts(group, 't1')} / T+5 {outcome_counts(group, 't5')} / T+20 {outcome_counts(group, 't20')}")

    lines.extend(["", "## By Borrow Status"])
    for key, group in sorted(by_borrow.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines.append(f"- {key} ({len(group)}): T+1 {outcome_counts(group, 't1')} / T+5 {outcome_counts(group, 't5')} / T+20 {outcome_counts(group, 't20')}")

    lines.extend(["", "## Rows"])
    for row in enriched:
        review = row.get("reboundReview", {})
        lines.append(
            f"- {row.get('ticker')} {row.get('signalDate')} {row.get('signalType')}: "
            f"bucket={row.get('exclusionBucket')}, action={row.get('actionClass')}, liquidity={row.get('liquidityBucket')}, borrow={row.get('borrow_borrowStatus')}, "
            f"T+1/T+5/T+20={row.get('t1')}/{row.get('t5')}/{row.get('t20')}, "
            f"maxClose={fmt_pct(review.get('maxCloseVsBasePct'))}, minLow={fmt_pct(review.get('minLowVsBaseLowPct'))}, "
            f"reboundDays={review.get('reboundDays', 'unknown')}, breakdownDays={review.get('breakdownDays', 'unknown')}"
        )

    lines.extend([
        "",
        "## Practical Read",
        "- `liquid_oversold_rebound_wait`: 流動性と貸借はあるが売られすぎ。即ショートではなく戻り売り待ち。",
        "- `low_liquidity_buy_avoid`: 方向が合っても板/約定リスクが大きい。空売りより買い回避。",
        "- `not_loan_margin_buy_avoid`: JPX貸借でないため、制度信用ショートの監視候補にしない。",
        "- `volume_not_confirmed_wait`: 悪材料でも出来高確認が弱い。追随ではなく反応待ち。",
        "- `hard_no_short_*`: 検証窓内の戻りが強く、即ショート除外。",
        "- `return_short_wait_after_setup`: 下落継続はあるが売られすぎ扱いのため、戻り失敗後だけ再検討。",
    ])

    output_md = Path(str(OUTPUT_MD).format(date=args.date))
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {output_md.relative_to(ROOT)} rows={len(enriched)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
