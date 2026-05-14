#!/usr/bin/env python3
"""Classify short entry readiness for short-use-case rows.

This separates a bearish research signal from something that is operationally
worth watching. It uses rough liquidity/turnover, oversold risk, volume
confirmation, technical pattern, and margin availability. It is not trading
advice.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
DEFAULT_SHORT_USE = ROOT / "topics/investment-research/inbox/{date}-short-use-case-data.json"
DEFAULT_OUTCOME = ROOT / "topics/investment-research/inbox/{date}-rough-backtest-outcomes-batch-1.md"
DEFAULT_BORROW = ROOT / "topics/investment-research/inbox/{date}-borrow-context-data.json"
DEFAULT_OUTPUT_JSON = ROOT / "topics/investment-research/inbox/{date}-short-readiness-data.json"
DEFAULT_OUTPUT_MD = ROOT / "topics/investment-research/inbox/{date}-short-readiness-summary.md"

HIGH_TURNOVER_YEN = 1_000_000_000
MEDIUM_TURNOVER_YEN = 300_000_000
LOW_TURNOVER_YEN = 100_000_000


def parse_sections(path: Path) -> list[tuple[str, str, str]]:
    text = path.read_text(encoding="utf-8")
    matches = list(re.finditer(r"^###\s+([^:]+):\s+(.+)$", text, re.M))
    sections = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((m.group(1).strip(), m.group(2).strip(), text[start:end]))
    return sections


def field(body: str, name: str) -> str:
    m = re.search(rf"^\s*- {re.escape(name)}:\s*(.+)$", body, re.M)
    return m.group(1).strip() if m else ""


def number(value: str) -> float | None:
    if not value or value in {"None", "null", "unknown", "pending"}:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
    return float(m.group(0)) if m else None


def outcome_index(path: Path) -> dict[tuple[str, str, str], dict]:
    idx = {}
    for _, title, body in parse_sections(path):
        ticker_m = re.match(r"([0-9]{4}|[0-9]{3}[A-Z])\s+", title)
        ticker = ticker_m.group(1) if ticker_m else ""
        signal_date = field(body, "signalDate")
        signal_type = field(body, "signalType") or "unknown"
        base_close = number(field(body, "base"))
        avg25 = number(field(body, "volumeAvg25BeforeSignal"))
        base_volume = number(field(body, "baseVolume"))
        t1_volume_ratio = number(field(body, "T+1VolumeRatio25")) or number(field(body, "T+1VolumeRatio5"))
        if ticker and signal_date:
            idx[(ticker, signal_date, signal_type)] = {
                "baseClose": base_close,
                "volumeAvg25BeforeSignal": avg25,
                "baseVolume": base_volume,
                "t1VolumeRatio": t1_volume_ratio,
                "avgTurnoverYen": base_close * avg25 if base_close and avg25 else None,
            }
    return idx


def borrow_index(path: Path) -> dict[tuple[str, str, str], dict]:
    if not path.exists():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8")).get("rows", [])
    return {
        (row.get("ticker", ""), row.get("signalDate", ""), row.get("signalType", "unknown")): row
        for row in rows
    }


def liquidity_bucket(turnover: float | None) -> str:
    if turnover is None:
        return "unknown"
    if turnover >= HIGH_TURNOVER_YEN:
        return "high"
    if turnover >= MEDIUM_TURNOVER_YEN:
        return "medium"
    if turnover >= LOW_TURNOVER_YEN:
        return "low"
    return "very_low"


def classify(row: dict, extra: dict, borrow: dict) -> tuple[str, list[str]]:
    reasons: list[str] = []
    use_case = row.get("shortUseCase", "")
    liquidity = liquidity_bucket(extra.get("avgTurnoverYen"))
    volume_ratio = extra.get("t1VolumeRatio")
    technical = row.get("technicalPattern", "unknown")
    candle = row.get("t1Candle", "unknown")
    rsi_bucket = row.get("rsi14Bucket", "unknown")
    margin_bucket = row.get("marginBucket", "unknown")
    borrow_status = borrow.get("borrowStatus", "unknown")

    if liquidity in {"high", "medium"}:
        reasons.append(f"liquidity_{liquidity}")
    elif liquidity in {"low", "very_low"}:
        reasons.append(f"liquidity_{liquidity}")
    else:
        reasons.append("liquidity_unknown")

    if volume_ratio is not None and volume_ratio >= 2:
        reasons.append("volume_confirmed")
    elif volume_ratio is not None:
        reasons.append("volume_not_confirmed")
    else:
        reasons.append("volume_unknown")

    if technical in {"technical_short_bias", "breakdown_short_watch", "bearish_trend_continuation"}:
        reasons.append("technical_support")
    if technical == "overbought_reversal_watch" and candle == "bearish_close":
        reasons.append("overheat_reversal_support")
    if rsi_bucket == "oversold" or row.get("bollingerBucket") == "below_lower_band":
        reasons.append("oversold_rebound_risk")
    if margin_bucket in {"buy_only_heavy", "balanced_to_buy_leaning"}:
        reasons.append(f"margin_{margin_bucket}")
    elif margin_bucket in {"sell_heavy_or_squeeze_risk"}:
        reasons.append("squeeze_risk")
    elif margin_bucket == "unknown":
        reasons.append("borrow_check_required")
    if borrow_status == "loan_margin":
        reasons.append("jpx_loan_margin_current")
    elif borrow_status == "standardized_margin_only":
        reasons.append("jpx_standardized_only_no_system_short")
    else:
        reasons.append("jpx_borrow_unknown_or_unavailable")

    if use_case != "short_entry_candidate":
        if use_case == "short_term_event_short":
            return "event_watch_only", reasons
        if use_case == "buy_avoid_rebound_risk":
            return "avoid_short_rebound_risk", reasons
        if use_case == "exit_or_buy_avoid":
            return "exit_or_buy_avoid_only", reasons
        return "not_entry", reasons

    if "oversold_rebound_risk" in reasons:
        return "medium_rebound_risk", reasons
    if borrow_status == "loan_margin" and liquidity in {"high", "medium"} and "volume_confirmed" in reasons and (technical in {"technical_short_bias", "breakdown_short_watch", "bearish_trend_continuation"} or candle == "bearish_close"):
        return "high", reasons
    if liquidity in {"high", "medium"} and "volume_confirmed" in reasons:
        return "medium", reasons
    if liquidity == "low" and "volume_confirmed" in reasons:
        return "medium_low_liquidity", reasons
    if liquidity == "very_low":
        return "low_liquidity_avoid", reasons
    return "watch_needs_confirmation", reasons


def win_rate(rows: list[dict], window: str) -> str:
    c = Counter(row.get(window, "unknown") for row in rows)
    judged = c["win"] + c["loss"] + c["flat"]
    wr = c["win"] / judged * 100 if judged else 0
    return f"{c['win']}/{c['loss']}/{c['flat']} wr={wr:.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify short entry readiness.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    parser.add_argument("--short-use", type=Path, default=None)
    parser.add_argument("--outcome", type=Path, default=None)
    parser.add_argument("--borrow", type=Path, default=None)
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    args = parser.parse_args()

    short_use = args.short_use or Path(str(DEFAULT_SHORT_USE).format(date=args.date))
    outcome_path = args.outcome or Path(str(DEFAULT_OUTCOME).format(date=args.date))
    borrow_path = args.borrow or Path(str(DEFAULT_BORROW).format(date=args.date))
    output_json = args.output_json or Path(str(DEFAULT_OUTPUT_JSON).format(date=args.date))
    output_md = args.output_md or Path(str(DEFAULT_OUTPUT_MD).format(date=args.date))

    short_rows = json.loads(short_use.read_text(encoding="utf-8"))["rows"]
    extra_idx = outcome_index(outcome_path)
    borrow_idx = borrow_index(borrow_path)
    out_rows = []
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in short_rows:
        key = (row.get("ticker", ""), row.get("signalDate", ""), row.get("signalType", "unknown"))
        extra = extra_idx.get(key, {})
        borrow = borrow_idx.get(key, {})
        readiness, reasons = classify(row, extra, borrow)
        enriched = {
            **row,
            **extra,
            **{f"borrow_{k}": v for k, v in borrow.items() if k in {"borrowStatus", "jpxCreditCategory", "standardizedShortEligible", "brokerGeneralShort", "reverseStockLoanFee", "sellRestriction", "borrowCheck"}},
            "liquidityBucket": liquidity_bucket(extra.get("avgTurnoverYen")),
            "shortReadiness": readiness,
            "shortReadinessReasons": reasons,
            "borrowCheck": borrow.get("borrowCheck", "required") if borrow else "required",
        }
        out_rows.append(enriched)
        groups[readiness].append(enriched)

    output_json.write_text(json.dumps({
        "createdAt": datetime.now(JST).replace(microsecond=0).isoformat(),
        "date": args.date,
        "mode": "short-readiness-classification",
        "caution": "粗い流動性・テクニカル分類。売買助言ではない。実売買前には貸借/売建可否/逆日歩/板を確認する。",
        "rows": out_rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        f"# {args.date} Short Readiness Summary",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {args.date}",
        "- mode: short-readiness-classification",
        f"- sourceLog: {short_use.relative_to(ROOT / 'topics/investment-research')}",
        "- caution: 粗い分類。売買助言ではなく、空売り候補を監視可能性で分けるための研究ログ。",
        "",
        "## Summary",
        f"- analyzedRows: {len(out_rows)}",
    ]
    for key, rows in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines.append(f"- {key}: {len(rows)}")
    lines.extend(["", "## Outcome By Readiness"])
    for key, rows in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines.append(f"- {key} ({len(rows)}): T1 {win_rate(rows, 't1')} / T5 {win_rate(rows, 't5')} / T20 {win_rate(rows, 't20')}")

    for title, key in [
        ("High Readiness", "high"),
        ("Medium Readiness", "medium"),
        ("Medium Low Liquidity", "medium_low_liquidity"),
        ("Watch Needs Confirmation", "watch_needs_confirmation"),
        ("Avoid Short Rebound Risk", "avoid_short_rebound_risk"),
    ]:
        lines.extend(["", f"## {title}"])
        selected = groups.get(key, [])[:25]
        if not selected:
            lines.append("- none")
            continue
        for row in selected:
            turnover = row.get("avgTurnoverYen")
            turnover_s = f"{turnover/100_000_000:.1f}億円" if turnover else "unknown"
            lines.append(
                f"- {row['ticker']} {row['signalDate']} {row['category']} {row['signalType']} "
                f"T1/T5/T20={row['t1']}/{row['t5']}/{row['t20']} liquidity={row['liquidityBucket']} turnover={turnover_s} reasons={','.join(row['shortReadinessReasons'])}"
            )

    lines.extend([
        "",
        "## Practical Read",
        "- `high` は研究上の最優先監視。実売買前には売建可否、貸借、逆日歩、板、寄り付き後の再確認が必要。",
        "- `medium` は材料と出来高はあるが、テクニカル/流動性/貸借の追加確認が必要。",
        "- `medium_low_liquidity` は値動きが荒く、空売りより買い回避に寄せる。",
        "- `avoid_short_rebound_risk` は悪材料でも売られすぎ。戻り売りの再セットアップまで待つ。",
    ])
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {output_json.relative_to(ROOT)} rows={len(out_rows)}")
    print(f"wrote {output_md.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
