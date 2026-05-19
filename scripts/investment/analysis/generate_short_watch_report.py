#!/usr/bin/env python3
"""Generate a compact short watch report for daily presentation.

Reads short-readiness rows and emits a concise Markdown report that separates
short entry watch from buy-avoid/exit candidates. This is a presentation layer
for research logs, not trading advice.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
JST = timezone(timedelta(hours=9))
DEFAULT_INPUT = ROOT / "topics/investment-research/inbox/{date}-short-readiness-data.json"
DEFAULT_OUTPUT = ROOT / "topics/investment-research/inbox/{date}-short-watch-report.md"


def yen_label(value: float | int | None) -> str:
    if value is None:
        return "unknown"
    try:
        return f"{float(value) / 100_000_000:.1f}億円"
    except (TypeError, ValueError):
        return "unknown"


def compact_reasons(row: dict) -> str:
    reasons = row.get("shortReadinessReasons") or []
    priority = [
        "jpx_loan_margin_current",
        "volume_confirmed",
        "technical_support",
        "overheat_reversal_support",
        "oversold_rebound_risk",
        "liquidity_high",
        "liquidity_medium",
        "liquidity_low",
        "borrow_check_required",
    ]
    selected = [r for r in priority if r in reasons]
    return ", ".join(selected[:5]) if selected else ", ".join(reasons[:5])


def sort_key(row: dict) -> tuple[int, int, float]:
    readiness_order = {"high": 0, "medium": 1, "medium_low_liquidity": 2, "low_liquidity_avoid": 3}
    rank_order = {"A": 0, "A-": 1, "B+": 2, "B": 3, "C": 4, "none": 9, "unknown": 9}
    turnover = row.get("avgTurnoverYen") or 0
    return (readiness_order.get(row.get("shortReadiness"), 9), rank_order.get(row.get("shortRank"), 9), -float(turnover or 0))


def row_line(row: dict) -> str:
    return (
        f"- {row.get('ticker')} {row.get('category')} / {row.get('signalType')}: "
        f"shortRank={row.get('shortRank')}, readiness={row.get('shortReadiness')}, "
        f"borrow={row.get('borrow_borrowStatus', 'unknown')}, liquidity={row.get('liquidityBucket')}({yen_label(row.get('avgTurnoverYen'))}), "
        f"T+1/T+5/T+20={row.get('t1')}/{row.get('t5')}/{row.get('t20')}, reasons={compact_reasons(row)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate daily short watch report.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    input_path = args.input or Path(str(DEFAULT_INPUT).format(date=args.date))
    data = json.loads(input_path.read_text(encoding="utf-8"))
    rows = data.get("rows", [])
    short_watch = sorted(
        [r for r in rows if r.get("shortUseCase") == "short_entry_candidate" and r.get("shortReadiness") in {"high", "medium"}],
        key=sort_key,
    )
    low_liquidity = sorted(
        [
            r for r in rows
            if r.get("shortUseCase") == "short_entry_candidate"
            and r.get("shortReadiness") in {"medium_low_liquidity", "low_liquidity_avoid"}
            and r.get("borrow_borrowStatus") == "loan_margin"
        ],
        key=sort_key,
    )
    rebound_risk = sorted(
        [r for r in rows if r.get("shortReadiness") == "avoid_short_rebound_risk" or r.get("shortUseCase") == "buy_avoid_rebound_risk"],
        key=sort_key,
    )
    exit_watch = sorted(
        [r for r in rows if r.get("shortUseCase") == "exit_or_buy_avoid"],
        key=sort_key,
    )
    event_watch = sorted(
        [r for r in rows if r.get("shortUseCase") == "short_term_event_short"],
        key=sort_key,
    )
    low_liquidity_non_borrow = sorted(
        [
            r for r in rows
            if r.get("shortUseCase") == "short_entry_candidate"
            and r.get("shortReadiness") in {"medium_low_liquidity", "low_liquidity_avoid"}
            and r.get("borrow_borrowStatus") != "loan_margin"
        ],
        key=sort_key,
    )
    counts = Counter(r.get("shortReadiness", "unknown") for r in rows)
    output = args.output or Path(str(DEFAULT_OUTPUT).format(date=args.date))

    lines = [
        f"# {args.date} Short Watch Report",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {args.date}",
        "- mode: short-watch-report",
        f"- sourceLog: {input_path.relative_to(ROOT / 'topics/investment-research')}",
        "- caution: 売買助言ではなく、空売り/買い回避の監視候補整理。実売買前には当日の売建可否、売り禁、逆日歩、板、寄り付き後の反応確認が必要。",
        "",
        "## Summary",
        f"- shortEntryWatch: {len(short_watch)}",
        f"- lowLiquidityShortWatch: {len(low_liquidity)}",
        f"- reboundRiskWatch: {len(rebound_risk)}",
        f"- buyAvoidOrExit: {len(exit_watch)}",
        f"- shortTermEventWatch: {len(event_watch)}",
        f"- lowLiquidityNonBorrowWatch: {len(low_liquidity_non_borrow)}",
    ]
    for key, count in counts.most_common():
        lines.append(f"- readiness.{key}: {count}")

    lines.extend(["", "## Short Entry Watch"])
    if not short_watch:
        lines.append("- 確認済み N/C")
    for row in short_watch[:12]:
        lines.append(row_line(row))

    lines.extend(["", "## Low Liquidity Short Watch"])
    if not low_liquidity:
        lines.append("- 確認済み N/C")
    for row in low_liquidity[:12]:
        lines.append(row_line(row))

    lines.extend(["", "## Rebound Risk / Return-Short Wait"])
    if not rebound_risk:
        lines.append("- 確認済み N/C")
    for row in rebound_risk[:20]:
        lines.append(row_line(row))

    lines.extend(["", "## Buy Avoid / Exit Watch"])
    if not exit_watch and not low_liquidity_non_borrow:
        lines.append("- 確認済み N/C")
    for row in (exit_watch + low_liquidity_non_borrow)[:20]:
        lines.append(row_line(row))

    lines.extend(["", "## Short-Term Event Watch"])
    if not event_watch:
        lines.append("- 確認済み N/C")
    for row in event_watch[:20]:
        lines.append(row_line(row))

    lines.extend([
        "",
        "## Daily Presentation Rule",
        "- daily本文に出す空売り監視候補は `Short Entry Watch` のみを基本にする。",
        "- `Low Liquidity Short Watch` はJPX貸借銘柄だけを表示し、原則として買い回避/警戒寄りに扱う。",
        "- `Rebound Risk / Return-Short Wait` は悪材料でも売られすぎ/反発警戒があるため、即追随ではなく戻り売り待ちとして扱う。",
        "- JPX貸借でない低流動性候補は `Buy Avoid / Exit Watch` に落とす。",
        "- `Buy Avoid / Exit Watch` は既存Longの撤退/利確、新規買い見送りの材料として扱う。",
        "- `Short-Term Event Watch` は希薄化/売出しなどのT+1/T+5中心候補として扱う。",
        "- 候補なしの場合は確認済み `N/C` と表示する。",
    ])
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {output.relative_to(ROOT)} shortWatch={len(short_watch)} reboundRisk={len(rebound_risk)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
