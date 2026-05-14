#!/usr/bin/env python3
"""Prioritize unknown fields in the rough backtest dataset."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
DEFAULT_OUTCOME = ROOT / "topics/investment-research/inbox/{date}-rough-backtest-outcomes-batch-1.md"
DEFAULT_STRATIFIED = ROOT / "topics/investment-research/inbox/{date}-rough-backtest-stratified-analysis.md"
DEFAULT_OUTPUT = ROOT / "topics/investment-research/inbox/{date}-unknown-priority-queue.md"
DEFAULT_MARGIN_DATA = ROOT / "topics/investment-research/inbox/{date}-margin-context-data.json"
OUTCOME = Path(str(DEFAULT_OUTCOME).format(date="2026-05-10"))
STRATIFIED = Path(str(DEFAULT_STRATIFIED).format(date="2026-05-10"))
MARGIN_DATA = Path(str(DEFAULT_MARGIN_DATA).format(date="2026-05-10"))


def field(body: str, name: str) -> str:
    m = re.search(rf"^\s*- {re.escape(name)}:\s*(.+)$", body, re.M)
    return m.group(1).strip() if m else ""


def sections(path: Path):
    text = path.read_text(encoding="utf-8")
    matches = list(re.finditer(r"^###\s+([^:]+):\s+(.+)$", text, re.M))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        yield m.group(1).strip(), m.group(2).strip(), text[start:end]


def importance(row: dict[str, str]) -> int:
    score = 0
    if row["category"] == "unknown":
        score += 3
    if row["longRank"] in {"A", "A-", "B+"}:
        score += 3
    if row["shortRank"] in {"A", "A-", "B", "B+"}:
        score += 3
    if row["t1"] in {"loss", "win"} and row["t5"] in {"loss", "win"}:
        score += 1
    if row["outcomeType"] in {"failed_or_downtrend", "trend_continuation", "initial_pop_only"}:
        score += 2
    if row["expected"] in {"up", "down"}:
        score += 1
    return score


def load_filled_margin_tickers() -> set[str]:
    if not MARGIN_DATA.exists():
        return set()
    data = json.loads(MARGIN_DATA.read_text(encoding="utf-8"))
    filled = set()
    for row in data.get("rows", []):
        ticker = str(row.get("ticker") or "")
        bucket = str(row.get("marginBucket") or "")
        if ticker and bucket and bucket != "unknown":
            filled.add(ticker)
    return filled


def main() -> int:
    global OUTCOME, STRATIFIED, MARGIN_DATA

    parser = argparse.ArgumentParser(description="Prioritize unknown fields in the rough backtest dataset.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    parser.add_argument("--outcome", type=Path, default=None)
    parser.add_argument("--stratified", type=Path, default=None)
    parser.add_argument("--margin-data", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    OUTCOME = args.outcome or Path(str(DEFAULT_OUTCOME).format(date=args.date))
    STRATIFIED = args.stratified or Path(str(DEFAULT_STRATIFIED).format(date=args.date))
    MARGIN_DATA = args.margin_data or Path(str(DEFAULT_MARGIN_DATA).format(date=args.date))
    output = args.output or Path(str(DEFAULT_OUTPUT).format(date=args.date))

    filled_margin_tickers = load_filled_margin_tickers()
    rows = []
    for signal_id, title, body in sections(OUTCOME):
        if field(body, "outcomeStatus") != "ok":
            continue
        rows.append({
            "id": signal_id,
            "title": title,
            "ticker": title.split()[0] if title.split() else "",
            "signalDate": field(body, "signalDate"),
            "category": field(body, "disclosureCategory") or "unknown",
            "signalType": field(body, "signalType") or "unknown",
            "expected": field(body, "expectedDirection") or "unknown",
            "longRank": field(body, "longSignalRank") or "unknown",
            "shortRank": field(body, "shortSignalRank") or "unknown",
            "outcomeType": field(body, "roughOutcomeType") or "unknown",
            "t1": field(body, "T+1Judge"),
            "t5": field(body, "T+5Judge"),
            "t20": field(body, "T+20Judge"),
        })
    category_unknown = [r for r in rows if r["category"] == "unknown"]
    rank_priority = [r for r in rows if r["longRank"] in {"A", "A-", "B+"} or r["shortRank"] in {"A", "A-", "B", "B+"}]
    margin_unknown_priority = [r for r in rank_priority if r["ticker"] not in filled_margin_tickers]
    category_unknown.sort(key=importance, reverse=True)
    margin_unknown_priority.sort(key=importance, reverse=True)

    lines = [
        f"# {args.date} Unknown Priority Queue",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {args.date}",
        "- mode: unknown-priority-queue",
        f"- sourceLog: {OUTCOME.relative_to(ROOT / 'topics/investment-research')}",
        "",
        "## Summary",
        f"- outcomeRows: {len(rows)}",
        f"- disclosureCategoryUnknownRows: {len(category_unknown)}",
        f"- filledMarginTickers: {len(filled_margin_tickers)}",
        f"- rankPriorityRows: {len(rank_priority)}",
        f"- rankPriorityRowsMissingMargin: {len(margin_unknown_priority)}",
        "",
        "## Priority 1: category unknown but important outcome/rank",
    ]
    for r in category_unknown[:25]:
        lines.append(f"- {r['ticker']} {r['title']}: date={r['signalDate']}, type={r['signalType']}, expected={r['expected']}, long={r['longRank']}, short={r['shortRank']}, outcome={r['outcomeType']}, score={importance(r)}")
    lines.extend(["", "## Priority 2: margin/session fill candidates by rank"])
    for r in margin_unknown_priority[:30]:
        lines.append(f"- {r['ticker']} {r['title']}: date={r['signalDate']}, category={r['category']}, type={r['signalType']}, long={r['longRank']}, short={r['shortRank']}, T1={r['t1']}, T5={r['t5']}, T20={r['t20']}, score={importance(r)}")
    lines.extend([
        "",
        "## Efficient Fill Plan",
        "1. disclosureCategory unknown は、signalTypeから一括分類できるものを先に潰す。",
        "2. margin unknown は、Priority 2のうち long A/A-/B+ と short B/A を優先する。",
        "3. session unknown は、sourceLogのpublishedAt/signalDateから after_close / intraday / before_open を復元する。",
        "4. 全件を完璧にせず、集計に効くrank上位と極端outcomeを先に処理する。",
    ])
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {output.relative_to(ROOT)}")
    print(f"category_unknown={len(category_unknown)} rank_priority={len(rank_priority)} missing_margin={len(margin_unknown_priority)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
