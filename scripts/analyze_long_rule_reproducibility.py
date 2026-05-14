#!/usr/bin/env python3
"""Summarize reproducibility of long-side rule candidates.

This reads the generic rule-check output and promotes only rules with enough
historical appearances and stable T+1/T+5 behavior into stricter long buckets.
It is a research log, not trading advice.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
INPUT = ROOT / "topics/investment-research/inbox/{date}-rule-check-data.json"
OUTPUT_MD = ROOT / "topics/investment-research/inbox/{date}-long-rule-reproducibility.md"
OUTPUT_JSON = ROOT / "topics/investment-research/inbox/{date}-long-rule-reproducibility.json"

RULE_DEFINITION = {
    "strict_long_signal": [
        "judgement == promote_candidate",
        "direction == long_bias",
        "T+1 support >= 20 and winRate >= 80",
        "T+5 support >= 15 and winRate >= 70",
        "T+20 support >= 8 and winRate >= 60",
    ],
    "long_watch": [
        "judgement == promote_candidate",
        "direction == long_bias",
        "T+1 support >= 12 and winRate >= 65",
        "T+5 support >= 8 and winRate >= 60",
        "strict_long_signal conditions are not fully met",
    ],
    "long_downgrade_or_avoid": [
        "judgement == downgrade_or_avoid_candidate",
        "direction == long_bias",
        "T+1 and T+5 winRate are weak",
    ],
    "long_short_term_only": [
        "judgement == short_term_only_candidate",
        "T+1 is usable but T+20 degrades",
    ],
    "promotion_policy": [
        "n < 8 は hypothesis_only",
        "n >= 20 かつ T+1/T+5/T+20 が安定したものだけ strict 扱い",
        "dailyでは該当ルール名、出現回数、T+1/T+5/T+20傾向を添えて使う",
    ],
}


def win_rate(item: dict, window: str) -> float:
    value = item.get("windows", {}).get(window, {}).get("winRate")
    return float(value) if value is not None else 0.0


def support(item: dict, window: str) -> int:
    return int(item.get("windows", {}).get(window, {}).get("support") or 0)


def classify(item: dict) -> str:
    judgement = item.get("judgement")
    direction = item.get("direction")
    if judgement == "promote_candidate" and direction == "long_bias":
        if (
            support(item, "t1") >= 20 and win_rate(item, "t1") >= 80
            and support(item, "t5") >= 15 and win_rate(item, "t5") >= 70
            and support(item, "t20") >= 8 and win_rate(item, "t20") >= 60
        ):
            return "strict_long_signal"
        if support(item, "t1") >= 12 and win_rate(item, "t1") >= 65 and support(item, "t5") >= 8 and win_rate(item, "t5") >= 60:
            return "long_watch"
    if judgement == "downgrade_or_avoid_candidate" and direction == "long_bias":
        return "long_downgrade_or_avoid"
    if judgement == "short_term_only_candidate" and direction in {"long_bias", "mixed_or_neutral"}:
        return "long_short_term_only"
    return "not_long_repro_rule"


def score(item: dict) -> tuple[int, float, float, float]:
    return (
        support(item, "t1") + support(item, "t5") + support(item, "t20"),
        win_rate(item, "t1"),
        win_rate(item, "t5"),
        win_rate(item, "t20"),
    )


def window_text(item: dict) -> str:
    parts = []
    for window in ("t1", "t5", "t20"):
        w = item.get("windows", {}).get(window, {})
        parts.append(
            f"{window.upper()} {w.get('win', 0)}/{w.get('loss', 0)}/{w.get('flat', 0)} n={w.get('support', 0)} wr={w.get('winRate', 'n/a')}%"
        )
    return " / ".join(parts)


def period_from_examples(item: dict) -> tuple[str, str]:
    occurrence = item.get("occurrence") or {}
    if occurrence.get("firstSignalDate") or occurrence.get("lastSignalDate"):
        return occurrence.get("firstSignalDate", ""), occurrence.get("lastSignalDate", "")
    dates = sorted(ex.get("signalDate", "") for ex in item.get("examples", []) if ex.get("signalDate"))
    return (dates[0], dates[-1]) if dates else ("", "")


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze long-side rule reproducibility.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    args = parser.parse_args()

    src = Path(str(INPUT).format(date=args.date))
    data = json.loads(src.read_text(encoding="utf-8"))
    rows = []
    groups: dict[str, list[dict]] = {}
    for item in data.get("ruleCandidates", []):
        bucket = classify(item)
        if bucket == "not_long_repro_rule":
            continue
        first, last = period_from_examples(item)
        enriched = {
            "bucket": bucket,
            "ruleGroup": item.get("ruleGroup"),
            "label": item.get("label"),
            "direction": item.get("direction"),
            "judgement": item.get("judgement"),
            "rowCount": item.get("rowCount"),
            "windows": item.get("windows"),
            "examples": item.get("examples", []),
            "occurrence": item.get("occurrence", {}),
            "occurrencePeriodFirst": first,
            "occurrencePeriodLast": last,
        }
        rows.append(enriched)
        groups.setdefault(bucket, []).append(enriched)

    for bucket in groups:
        groups[bucket].sort(key=score, reverse=True)
    rows.sort(key=lambda r: ({"strict_long_signal": 0, "long_watch": 1, "long_downgrade_or_avoid": 2, "long_short_term_only": 3}.get(r["bucket"], 9), -int(r.get("rowCount") or 0)))

    output_json = Path(str(OUTPUT_JSON).format(date=args.date))
    output_json.write_text(json.dumps({
        "createdAt": datetime.now(JST).replace(microsecond=0).isoformat(),
        "mode": "long-rule-reproducibility",
        "source": src.relative_to(ROOT).as_posix(),
        "caution": "粗いルール再現性集計。売買助言ではない。",
        "ruleDefinition": RULE_DEFINITION,
        "rows": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        f"# {args.date} Long Rule Reproducibility",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {args.date}",
        "- mode: long-rule-reproducibility",
        f"- sourceLog: {src.relative_to(ROOT / 'topics/investment-research').as_posix()}",
        "- caution: 粗いルール再現性集計。売買助言ではない。",
        "",
        "## Reproducible Rule Definition",
    ]
    for rule, conditions in RULE_DEFINITION.items():
        lines.append(f"### {rule}")
        for condition in conditions:
            lines.append(f"- {condition}")

    lines.extend(["", "## Summary"])
    for bucket in ("strict_long_signal", "long_watch", "long_downgrade_or_avoid", "long_short_term_only"):
        lines.append(f"- {bucket}: {len(groups.get(bucket, []))}")

    for title, bucket, limit in [
        ("Strict Long Signal", "strict_long_signal", 15),
        ("Long Watch", "long_watch", 12),
        ("Long Downgrade Or Avoid", "long_downgrade_or_avoid", 12),
        ("Long Short-Term Only", "long_short_term_only", 10),
    ]:
        lines.extend(["", f"## {title}"])
        selected = groups.get(bucket, [])
        if not selected:
            lines.append("- none")
            continue
        for item in selected[:limit]:
            lines.append(
                f"- {item['ruleGroup']}: `{item['label']}` appearances={item['rowCount']} "
                f"occurrencePeriod={item['occurrencePeriodFirst']}..{item['occurrencePeriodLast']} / {window_text(item)}"
            )
            for ex in item.get("examples", [])[:3]:
                lines.append(f"  - {ex.get('ticker')} {ex.get('signalDate')} {ex.get('category')} {ex.get('signalType')} T+1/T+5/T+20={ex.get('t1')}/{ex.get('t5')}/{ex.get('t20')}")

    lines.extend([
        "",
        "## Practical Read",
        "- `strict_long_signal` はdailyのLong監視候補の中核にできるが、個別材料と当日地合いの確認は必須。",
        "- `long_watch` は監視候補。出来高、寄り付き、引け形状が揃うまで強く扱わない。",
        "- `long_downgrade_or_avoid` は買い回避/利確/撤退の確認観点にする。",
        "- `long_short_term_only` はT+1/T+5中心。T+20まで引っ張らない。",
    ])

    output_md = Path(str(OUTPUT_MD).format(date=args.date))
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {output_md.relative_to(ROOT)} strict={len(groups.get('strict_long_signal', []))} rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
