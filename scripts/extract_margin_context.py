#!/usr/bin/env python3
"""Extract manual margin fills into a machine-readable JSON file."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
DEFAULT_INPUT = ROOT / "topics/investment-research/inbox/{date}-margin-context-priority-fill.md"
DEFAULT_FALLBACK_INPUT = ROOT / "topics/investment-research/inbox/2026-05-10-margin-context-priority-fill.md"
DEFAULT_OUTPUT = ROOT / "topics/investment-research/inbox/{date}-margin-context-data.json"
DEFAULT_DB = ROOT / "data" / "investment.db"


def field(body: str, name: str) -> str:
    m = re.search(rf"^- {re.escape(name)}:\s*(.+)$", body, re.M)
    return m.group(1).strip() if m else ""


def number(value: str) -> float | None:
    value = value.replace(",", "").strip()
    try:
        return float(value)
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract manual margin fills into JSON.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    input_path = args.input or Path(str(DEFAULT_INPUT).format(date=args.date))
    if not input_path.exists() and args.input is None:
        input_path = DEFAULT_FALLBACK_INPUT
    output = args.output or Path(str(DEFAULT_OUTPUT).format(date=args.date))

    text = input_path.read_text(encoding="utf-8")
    matches = list(re.finditer(r"^###\s+(margin_\d+_\d+):\s+(.+)$", text, re.M))
    rows = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        title = match.group(2).strip()
        ticker_match = re.match(r"([0-9]{4}|[0-9]{3}[A-Z])\s+", title)
        ticker = ticker_match.group(1) if ticker_match else ""
        rows.append({
            "id": match.group(1),
            "ticker": ticker,
            "title": title,
            "relatedSignal": field(body, "relatedSignal"),
            "referenceDate": field(body, "referenceDate"),
            "marginBuyBalance": number(field(body, "marginBuyBalance")),
            "marginSellBalance": number(field(body, "marginSellBalance")),
            "marginRatio": number(field(body, "marginRatio")),
            "marginBucket": field(body, "marginBucket") or bucket(number(field(body, "marginRatio")), number(field(body, "marginBuyBalance")), number(field(body, "marginSellBalance"))),
            "source": field(body, "source"),
            "url": field(body, "url") or field(body, "yahooUrl") or field(body, "karauriUrl"),
        })
    output.write_text(json.dumps({
        "date": args.date,
        "source": str(input_path.relative_to(ROOT)),
        "rows": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    conn = sqlite3.connect(args.db)
    try:
        conn.execute("DELETE FROM margin_context_rows WHERE date=?", (args.date,))
        for r in rows:
            conn.execute(
                """
                INSERT INTO margin_context_rows(
                  date,ticker,reference_date,related_signal,margin_buy_balance,margin_sell_balance,margin_ratio,margin_bucket,source,url,source_path,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                """,
                (
                    args.date,
                    r.get("ticker", ""),
                    r.get("referenceDate", ""),
                    r.get("relatedSignal", ""),
                    r.get("marginBuyBalance"),
                    r.get("marginSellBalance"),
                    r.get("marginRatio"),
                    r.get("marginBucket", ""),
                    r.get("source", ""),
                    r.get("url", ""),
                    str(input_path.relative_to(ROOT)),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    print(f"wrote {output.relative_to(ROOT)} rows={len(rows)}")
    return 0


def bucket(ratio: float | None, buy: float | None, sell: float | None) -> str:
    if sell == 0 and buy and buy > 0:
        return "buy_only_heavy"
    if ratio is None:
        return "unknown"
    if ratio >= 50:
        return "extreme_buy_heavy"
    if ratio >= 10:
        return "buy_heavy"
    if ratio >= 5:
        return "balanced_to_buy_leaning"
    if ratio >= 1:
        return "balanced"
    return "sell_heavy_or_squeeze_risk"


if __name__ == "__main__":
    raise SystemExit(main())
