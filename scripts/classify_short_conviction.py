#!/usr/bin/env python3
"""Classify short candidates into stricter conviction buckets.

This is a presentation and research layer. It deliberately keeps short-entry
watch small because short signals are fragile and operationally risky.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
DEFAULT_READINESS = ROOT / "topics/investment-research/inbox/{date}-short-readiness-data.json"
CHART = ROOT / "topics/investment-research/inbox/{date}-short-chart-window-data.json"
REBOUND = ROOT / "topics/investment-research/inbox/{date}-short-rebound-risk-data.json"
OUTPUT_MD = ROOT / "topics/investment-research/inbox/{date}-short-conviction-report.md"
OUTPUT_JSON = ROOT / "topics/investment-research/inbox/{date}-short-conviction-data.json"

RULE_DEFINITION = {
    "strict_short_signal": [
        "shortUseCase == short_entry_candidate",
        "shortReadiness in {high, medium}",
        "borrowStatus == loan_margin",
        "liquidityBucket in {high, medium}",
        "followThrough == yes",
        "reboundRisk == no",
        "postBreakdownDays >= 5",
        "bearishDaysFirst5 >= 2",
    ],
    "return_short_wait": [
        "shortUseCase == short_entry_candidate",
        "borrowStatus == loan_margin",
        "liquidityBucket in {high, medium}",
        "reboundRisk == yes",
    ],
    "tactical_low_liquidity_watch": [
        "shortUseCase == short_entry_candidate",
        "borrowStatus == loan_margin",
        "liquidityBucket in {low, very_low}",
        "followThrough == yes",
        "reboundRisk == no",
    ],
    "promotion_policy": [
        "n < 8 は hypothesis_only",
        "n >= 8 かつ T+1/T+5 が安定してから daily rank 補正に使う",
        "実運用前は当日売建可否、売り禁、逆日歩、板、寄り付き後の反応を別確認する",
    ],
}


def key(row: dict) -> tuple[str, str, str]:
    return (row.get("ticker", ""), row.get("signalDate", ""), row.get("signalType", ""))


def outcome_counts(rows: list[dict], field: str) -> str:
    c = Counter(row.get(field, "unknown") for row in rows)
    judged = c["win"] + c["loss"] + c["flat"]
    wr = c["win"] / judged * 100 if judged else 0
    return f"{c['win']}/{c['loss']}/{c['flat']} pending={c['pending']} wr={wr:.1f}%"


def rule_stats(rows: list[dict]) -> dict:
    dates = sorted({r.get("signalDate", "") for r in rows if r.get("signalDate")})
    return {
        "count": len(rows),
        "firstSignalDate": dates[0] if dates else "",
        "lastSignalDate": dates[-1] if dates else "",
        "signalTypes": dict(Counter(r.get("signalType", "unknown") for r in rows)),
        "categories": dict(Counter(r.get("category", "unknown") for r in rows)),
        "t1": dict(Counter(r.get("t1", "unknown") for r in rows)),
        "t5": dict(Counter(r.get("t5", "unknown") for r in rows)),
        "t20": dict(Counter(r.get("t20", "unknown") for r in rows)),
    }


def yen_label(value: float | int | None) -> str:
    if value is None:
        return "unknown"
    try:
        return f"{float(value) / 100_000_000:.1f}億円"
    except (TypeError, ValueError):
        return "unknown"


def classify(row: dict, chart: dict | None, rebound: dict | None) -> tuple[str, list[str]]:
    reasons: list[str] = []
    use_case = row.get("shortUseCase")
    readiness = row.get("shortReadiness")
    borrow = row.get("borrow_borrowStatus")
    liquidity = row.get("liquidityBucket")
    chart_review = (chart or {}).get("review", {})
    follow = chart_review.get("followThrough")
    rebound_risk = chart_review.get("reboundRisk")
    breakdown_days = chart_review.get("postBreakdownDays") or 0
    bearish_days = chart_review.get("bearishDaysFirst5") or 0
    action = (rebound or {}).get("actionClass")

    if use_case != "short_entry_candidate":
        if readiness == "avoid_short_rebound_risk" or action:
            return "return_short_wait_or_avoid", ["not_short_entry", action or "avoid_short_rebound_risk"]
        if use_case == "short_term_event_short":
            return "event_only", ["short_term_event"]
        if use_case == "exit_or_buy_avoid":
            return "exit_or_buy_avoid", ["exit_or_buy_avoid"]
        return "not_short", ["not_short_entry"]

    if borrow != "loan_margin":
        return "buy_avoid_no_system_short", ["not_jpx_loan_margin"]
    if liquidity in {"low", "very_low"}:
        if follow == "yes" and rebound_risk == "no":
            return "tactical_low_liquidity_watch", ["loan_margin", "low_liquidity", "follow_through"]
        return "buy_avoid_low_liquidity", ["low_liquidity"]
    if rebound_risk == "yes":
        return "return_short_wait", ["rebound_risk", "wait_failed_rebound"]
    if readiness in {"high", "medium"} and follow == "yes" and rebound_risk == "no" and breakdown_days >= 5 and bearish_days >= 2:
        return "strict_short_signal", ["loan_margin", f"liquidity_{liquidity}", "follow_through", "no_rebound", "weak_first5"]
    if readiness in {"high", "medium"}:
        return "short_watch_needs_confirmation", ["loan_margin", f"liquidity_{liquidity}", "needs_chart_confirmation"]
    return "not_short", ["insufficient_conditions"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify strict short conviction.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    parser.add_argument("--input", type=Path, default=None)
    args = parser.parse_args()

    input_path = args.input or Path(str(DEFAULT_READINESS).format(date=args.date))
    readiness_rows = json.loads(input_path.read_text(encoding="utf-8")).get("rows", [])
    chart_path = Path(str(CHART).format(date=args.date))
    rebound_path = Path(str(REBOUND).format(date=args.date))
    chart_idx = {key(row): row for row in json.loads(chart_path.read_text(encoding="utf-8")).get("rows", [])} if chart_path.exists() else {}
    rebound_idx = {key(row): row for row in json.loads(rebound_path.read_text(encoding="utf-8")).get("rows", [])} if rebound_path.exists() else {}

    rows = []
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in readiness_rows:
        k = key(row)
        bucket, reasons = classify(row, chart_idx.get(k), rebound_idx.get(k))
        if bucket in {"not_short"}:
            continue
        enriched = {
            "ticker": row.get("ticker"),
            "company": row.get("company"),
            "signalDate": row.get("signalDate"),
            "category": row.get("category"),
            "signalType": row.get("signalType"),
            "shortRank": row.get("shortRank"),
            "shortUseCase": row.get("shortUseCase"),
            "shortReadiness": row.get("shortReadiness"),
            "borrowStatus": row.get("borrow_borrowStatus"),
            "liquidityBucket": row.get("liquidityBucket"),
            "avgTurnoverYen": row.get("avgTurnoverYen"),
            "t1": row.get("t1"),
            "t5": row.get("t5"),
            "t20": row.get("t20"),
            "convictionBucket": bucket,
            "convictionReasons": reasons,
            "chart": (chart_idx.get(k) or {}).get("review", {}),
            "reboundAction": (rebound_idx.get(k) or {}).get("actionClass", ""),
        }
        rows.append(enriched)
        groups[bucket].append(enriched)

    output_json = Path(str(OUTPUT_JSON).format(date=args.date))
    stats = {bucket: rule_stats(bucket_rows) for bucket, bucket_rows in sorted(groups.items())}
    output_json.write_text(json.dumps({
        "createdAt": datetime.now(JST).replace(microsecond=0).isoformat(),
        "mode": "short-conviction-classification",
        "caution": "売買助言ではなく、ショート監視候補を少数精鋭に絞るための研究ログ。",
        "ruleDefinition": RULE_DEFINITION,
        "ruleStats": stats,
        "rows": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        f"# {args.date} Short Conviction Report",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {args.date}",
        "- mode: short-conviction-classification",
        f"- sourceLog: {input_path.relative_to(ROOT / 'topics/investment-research')}",
        "- caution: 売買助言ではなく、ショート監視候補を少数精鋭に絞るための研究ログ。",
        "",
        "## Reproducible Rule Definition",
    ]
    for rule, conditions in RULE_DEFINITION.items():
        lines.append(f"### {rule}")
        for condition in conditions:
            lines.append(f"- {condition}")
    lines.extend([
        "",
        "## Summary",
        f"- rows: {len(rows)}",
    ])
    for bucket, bucket_rows in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines.append(f"- {bucket}: {len(bucket_rows)}")

    lines.extend(["", "## Outcome By Conviction"])
    for bucket, bucket_rows in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines.append(f"- {bucket} ({len(bucket_rows)}): T+1 {outcome_counts(bucket_rows, 't1')} / T+5 {outcome_counts(bucket_rows, 't5')} / T+20 {outcome_counts(bucket_rows, 't20')}")

    lines.extend(["", "## Rule Occurrence History"])
    for bucket, bucket_rows in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        stat = stats[bucket]
        signal_types = ", ".join(f"{k}:{v}" for k, v in sorted(stat["signalTypes"].items(), key=lambda kv: (-kv[1], kv[0]))[:5])
        categories = ", ".join(f"{k}:{v}" for k, v in sorted(stat["categories"].items(), key=lambda kv: (-kv[1], kv[0]))[:5])
        lines.append(
            f"- {bucket}: appearances={stat['count']}, period={stat['firstSignalDate']}..{stat['lastSignalDate']}, "
            f"T+1 {outcome_counts(bucket_rows, 't1')}, T+5 {outcome_counts(bucket_rows, 't5')}, T+20 {outcome_counts(bucket_rows, 't20')}, "
            f"types=[{signal_types}], categories=[{categories}]"
        )

    for title, bucket in [
        ("Strict Short Signal", "strict_short_signal"),
        ("Return Short Wait", "return_short_wait"),
        ("Tactical Low Liquidity Watch", "tactical_low_liquidity_watch"),
        ("Hard Avoid / Buy Avoid", "return_short_wait_or_avoid"),
    ]:
        lines.extend(["", f"## {title}"])
        bucket_rows = groups.get(bucket, [])
        if not bucket_rows:
            lines.append("- 確認済み N/C")
            continue
        for row in sorted(bucket_rows, key=lambda r: (r.get("signalDate", ""), r.get("ticker", ""))):
            chart = row.get("chart", {})
            lines.append(
                f"- {row.get('ticker')} {row.get('signalDate')} {row.get('signalType')}: "
                f"readiness={row.get('shortReadiness')}, borrow={row.get('borrowStatus')}, liquidity={row.get('liquidityBucket')}({yen_label(row.get('avgTurnoverYen'))}), "
                f"T+1/T+5/T+20={row.get('t1')}/{row.get('t5')}/{row.get('t20')}, "
                f"follow={chart.get('followThrough', 'unknown')}, rebound={chart.get('reboundRisk', 'unknown')}, "
                f"breakdownDays={chart.get('postBreakdownDays', 'unknown')}, bearishFirst5={chart.get('bearishDaysFirst5', 'unknown')}"
            )

    lines.extend([
        "",
        "## Practical Read",
        "- `strict_short_signal` だけを日次の空売り監視候補の中核にする。",
        "- `return_short_wait` は即追随ではなく、戻り失敗/再下落確認待ち。",
        "- `tactical_low_liquidity_watch` は方向検証用。実売買では板/約定/逆日歩を強く確認する。",
        "- `buy_avoid_no_system_short` / `return_short_wait_or_avoid` は買い回避や撤退判断に寄せる。",
    ])

    output_md = Path(str(OUTPUT_MD).format(date=args.date))
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {output_md.relative_to(ROOT)} rows={len(rows)} strict={len(groups.get('strict_short_signal', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
