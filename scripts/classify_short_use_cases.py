#!/usr/bin/env python3
"""Classify short-side rows into short entry vs buy avoid use cases.

This script reads the enriched rough outcome rows from analyze_market_outcomes
and emits a conservative classification. It is for research/triage only, not
trading advice.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
DEFAULT_OUTPUT_JSON = ROOT / "topics/investment-research/inbox/{date}-short-use-case-data.json"
DEFAULT_OUTPUT_MD = ROOT / "topics/investment-research/inbox/{date}-short-use-case-summary.md"
DEFAULT_OUTCOME = ROOT / "topics/investment-research/inbox/{date}-rough-backtest-outcomes-batch-1.md"
WINDOWS = ("t1", "t5", "t20")

sys.path.insert(0, str(ROOT / "scripts"))
import analyze_market_outcomes as outcomes  # noqa: E402

STRONG_NEGATIVE_CATEGORIES = {"earnings_negative", "risk_event"}
CAPITAL_POLICY_CATEGORIES = {"capital_policy", "capital_policy_large_holding"}
WEAK_CANDLES = {"bearish_close", "bearish_body", "upper_wick_reversal"}
SHORT_TECHNICALS = {"technical_short_bias", "breakdown_short_watch", "bearish_trend_continuation"}
OVERHEAT_REVERSAL = {"overbought_reversal_watch"}
OVERSOLD_RSI = {"oversold"}
LOWER_BB = {"below_lower_band", "lower_half"}


def is_down_expected(row: dict[str, str]) -> bool:
    return "down" in row.get("expected", "").lower()


def is_short_rank_candidate(row: dict[str, str]) -> bool:
    return row.get("shortRank") in {"A", "A-", "B+", "B"}


def is_oversold(row: dict[str, str]) -> bool:
    return row.get("rsi14Bucket") in OVERSOLD_RSI or row.get("bollingerBucket") == "below_lower_band"


def classify(row: dict[str, str]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    category = row.get("category", "unknown")
    candle = row.get("t1Candle", "unknown")
    technical = row.get("technicalPattern", "unknown")
    market = row.get("marketContext", "unknown")
    sector = row.get("sectorMarketContext", "unknown")
    volume = row.get("volumeRatioBucket", "unknown")

    negative_material = category in STRONG_NEGATIVE_CATEGORIES or (category in CAPITAL_POLICY_CATEGORIES and is_down_expected(row))
    weak_reaction = candle in WEAK_CANDLES
    strong_volume_weak = volume in {"spike_2x_5x", "spike_5x_plus"} and candle == "bearish_close"
    technical_short = technical in SHORT_TECHNICALS
    overheat_reversal = technical in OVERHEAT_REVERSAL and candle in {"bearish_close", "upper_wick_reversal"}
    tailwind_failure = market == "tailwind_or_positive" and (negative_material or weak_reaction)
    sector_failure = sector in {"sector_tailwind", "sector_relative_strength"} and weak_reaction

    if negative_material:
        reasons.append("negative_material")
    if weak_reaction:
        reasons.append("weak_reaction")
    if strong_volume_weak:
        reasons.append("volume_confirmed_weak_close")
    if technical_short:
        reasons.append("technical_short_pattern")
    if overheat_reversal:
        reasons.append("overheat_reversal")
    if tailwind_failure:
        reasons.append("tailwind_failure")
    if sector_failure:
        reasons.append("sector_failure")
    if is_oversold(row):
        reasons.append("oversold_rebound_risk")

    if negative_material and strong_volume_weak and not is_oversold(row):
        return "short_entry_candidate", reasons
    if negative_material and weak_reaction and tailwind_failure and not is_oversold(row):
        return "short_entry_candidate", reasons
    if negative_material and technical_short and weak_reaction and not is_oversold(row):
        return "short_entry_candidate", reasons
    if overheat_reversal and weak_reaction and not negative_material:
        return "exit_or_buy_avoid", reasons
    if category in CAPITAL_POLICY_CATEGORIES and is_down_expected(row):
        return "short_term_event_short", reasons
    if negative_material and is_oversold(row):
        return "buy_avoid_rebound_risk", reasons
    if negative_material or is_short_rank_candidate(row) or weak_reaction or technical_short:
        return "buy_avoid_or_watch", reasons
    return "not_short_side", reasons


def judge_counter(rows: list[dict[str, str]]) -> dict[str, Counter[str]]:
    counters = {w: Counter() for w in WINDOWS}
    for row in rows:
        for w in WINDOWS:
            counters[w][row.get(w, "unknown")] += 1
    return counters


def win_rate(counter: Counter[str]) -> float | None:
    judged = counter["win"] + counter["loss"] + counter["flat"]
    if not judged:
        return None
    return counter["win"] / judged * 100


def counter_line(label: str, rows: list[dict[str, str]]) -> str:
    counters = judge_counter(rows)
    parts = []
    for w in WINDOWS:
        c = counters[w]
        wr = win_rate(c)
        wr_s = "n/a" if wr is None else f"{wr:.1f}%"
        parts.append(f"{w.upper()} {c['win']}/{c['loss']}/{c['flat']} wr={wr_s}")
    return f"- {label} ({len(rows)}): " + " / ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify short-side rows into use cases.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    parser.add_argument("--outcome", type=Path, default=None)
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    args = parser.parse_args()
    output_json = args.output_json or Path(str(DEFAULT_OUTPUT_JSON).format(date=args.date))
    output_md = args.output_md or Path(str(DEFAULT_OUTPUT_MD).format(date=args.date))
    outcomes.OUTCOME = args.outcome or Path(str(DEFAULT_OUTCOME).format(date=args.date))

    rows = outcomes.parse_outcomes()
    source_log = outcomes.OUTCOME.relative_to(ROOT / "topics/investment-research")
    out_rows = []
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    reason_counts: Counter[str] = Counter()
    for row in rows:
        use_case, reasons = classify(row)
        enriched = {**row, "shortUseCase": use_case, "shortUseCaseReasons": reasons}
        out_rows.append(enriched)
        groups[use_case].append(enriched)
        reason_counts.update(reasons)

    output_json.write_text(json.dumps({
        "createdAt": datetime.now(JST).replace(microsecond=0).isoformat(),
        "date": args.date,
        "mode": "short-use-case-classification",
        "caution": "粗い分類。売買助言ではなく、short entryとbuy avoidを分けるための研究ログ。",
        "rows": out_rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        f"# {args.date} Short Use Case Summary",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {args.date}",
        "- mode: short-use-case-classification",
        f"- sourceLog: {source_log}",
        "- caution: short entry と buy avoid を分けるための粗い分類。売買助言ではない。",
        "",
        "## Summary",
        f"- analyzedRows: {len(out_rows)}",
    ]
    for key, values in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines.append(f"- {key}: {len(values)}")

    lines.extend(["", "## Outcome By Short Use Case"])
    for key, values in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines.append(counter_line(key, values))

    lines.extend(["", "## Reason Counts"])
    for reason, count in reason_counts.most_common():
        lines.append(f"- {reason}: {count}")

    lines.extend(["", "## Short Entry Candidates"])
    for row in groups.get("short_entry_candidate", [])[:20]:
        lines.append(
            f"- {row['ticker']} {row['signalDate']} {row['category']} {row['signalType']} "
            f"T1/T5/T20={row['t1']}/{row['t5']}/{row['t20']} reasons={','.join(row['shortUseCaseReasons'])}"
        )
    lines.extend(["", "## Buy Avoid Rebound Risk"])
    for row in groups.get("buy_avoid_rebound_risk", [])[:20]:
        lines.append(
            f"- {row['ticker']} {row['signalDate']} {row['category']} {row['signalType']} "
            f"T1/T5/T20={row['t1']}/{row['t5']}/{row['t20']} reasons={','.join(row['shortUseCaseReasons'])}"
        )

    lines.extend([
        "",
        "## Practical Read",
        "- `short_entry_candidate` は悪材料、弱い足、出来高/地合い/テクニカルの複合があるものに限定する。",
        "- `buy_avoid_rebound_risk` は悪材料でも売られすぎの可能性があり、空売りではなく買い回避に寄せる。",
        "- `short_term_event_short` は希薄化/売出しなどのイベント型。T+1/T+5中心に扱い、T+20まで引っ張らない。",
        "- `exit_or_buy_avoid` は既存Longの撤退/利確判断に使い、単独で空売り候補にしない。",
    ])
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {output_json.relative_to(ROOT)} rows={len(out_rows)}")
    print(f"wrote {output_md.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
