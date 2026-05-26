#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"
OUT = ROOT / "topics" / "investment-research" / "inbox"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Report quality of auto credit collection (SBI)")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--unknown-rate-warn", type=float, default=0.30, help="warn threshold for unknown rate (0-1)")
    p.add_argument("--unknown-rate-error", type=float, default=0.50, help="error threshold for unknown rate (0-1)")
    p.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        total_tickers = int(
            conn.execute(
                "SELECT COUNT(DISTINCT ticker) FROM entry_candidates WHERE date=? AND COALESCE(ticker,'')<>''",
                (args.date,),
            ).fetchone()[0]
            or 0
        )
        rows = conn.execute(
            """
            SELECT ticker,credit_status,source_kind,source_detail
            FROM credit_status_rows
            WHERE date=? AND source_kind='auto_sbi'
            """,
            (args.date,),
        ).fetchall()
    finally:
        conn.close()

    auto_rows = len(rows)
    auto_unknown = 0
    auto_non_marginable = 0
    auto_marginable = 0
    regulation_hits = 0
    for r in rows:
        cs = str(r["credit_status"] or "").strip().lower()
        if cs == "auto_unknown":
            auto_unknown += 1
        elif cs == "auto_non_marginable":
            auto_non_marginable += 1
        elif cs == "auto_marginable":
            auto_marginable += 1
        raw = str(r["source_detail"] or "").strip()
        try:
            d = json.loads(raw) if raw else {}
        except Exception:
            d = {}
        hits = d.get("regulation_hits") if isinstance(d, dict) else None
        if isinstance(hits, list) and hits:
            regulation_hits += 1

    unknown_rate = (auto_unknown / auto_rows) if auto_rows > 0 else 0.0
    regulation_hit_rate = (regulation_hits / auto_rows) if auto_rows > 0 else 0.0
    quality_status = "ok"
    if auto_rows == 0:
        quality_status = "no_data"
    elif unknown_rate >= max(0.0, min(1.0, args.unknown_rate_error)):
        quality_status = "error"
    elif unknown_rate >= max(0.0, min(1.0, args.unknown_rate_warn)):
        quality_status = "warn"

    payload = {
        "date": args.date,
        "totalTickers": total_tickers,
        "autoRows": auto_rows,
        "autoUnknownCount": auto_unknown,
        "autoNonMarginableCount": auto_non_marginable,
        "autoMarginableCount": auto_marginable,
        "regulationHitCount": regulation_hits,
        "unknownRate": round(unknown_rate, 4),
        "regulationHitRate": round(regulation_hit_rate, 4),
        "qualityStatus": quality_status,
        "unknownRateWarn": args.unknown_rate_warn,
        "unknownRateError": args.unknown_rate_error,
    }

    if args.write_files:
        out_json = OUT / f"{args.date}-credit-auto-quality.json"
        out_md = OUT / f"{args.date}-credit-auto-quality.md"
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        lines = [
            f"# {args.date} Credit Auto Quality",
            "",
            f"- totalTickers: {total_tickers}",
            f"- autoRows: {auto_rows}",
            f"- autoUnknownCount: {auto_unknown}",
            f"- autoNonMarginableCount: {auto_non_marginable}",
            f"- autoMarginableCount: {auto_marginable}",
            f"- regulationHitCount: {regulation_hits}",
            f"- unknownRate: {unknown_rate:.1%}",
            f"- regulationHitRate: {regulation_hit_rate:.1%}",
            f"- qualityStatus: {quality_status}",
        ]
        out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {out_md.relative_to(ROOT)}")
        print(f"wrote {out_json.relative_to(ROOT)}")

    print(
        "credit_auto_quality date={0} auto_rows={1} unknown={2} unknown_rate={3:.3f} status={4}".format(
            args.date, auto_rows, auto_unknown, unknown_rate, quality_status
        )
    )
    return 2 if quality_status == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
