#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db

DEFAULT_DB = resolve_investment_db()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Diagnose unresolved company-name placeholders")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    return p.parse_args()


def is_placeholder(v: str) -> bool:
    s = (v or "").strip()
    if not s:
        return True
    return s.upper() in {"不明", "-", "N/A", "NA", "UNKNOWN"}


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT 'signals' AS tbl, signal_id AS row_id, ticker, company
            FROM signals
            WHERE date=?
              AND COALESCE(ticker,'')<>''
              AND UPPER(TRIM(COALESCE(company,''))) IN ('', '不明', '-', 'N/A', 'NA', 'UNKNOWN')
            UNION ALL
            SELECT 'entry_candidates' AS tbl, signal_id AS row_id, ticker, company
            FROM entry_candidates
            WHERE date=?
              AND COALESCE(ticker,'')<>''
              AND UPPER(TRIM(COALESCE(company,''))) IN ('', '不明', '-', 'N/A', 'NA', 'UNKNOWN')
            UNION ALL
            SELECT 'opening_scenarios' AS tbl, COALESCE(signal_id,'') AS row_id, ticker, company
            FROM opening_scenarios
            WHERE scenario_date=?
              AND COALESCE(ticker,'')<>''
              AND UPPER(TRIM(COALESCE(company,''))) IN ('', '不明', '-', 'N/A', 'NA', 'UNKNOWN')
            ORDER BY tbl, ticker, row_id
            """,
            (args.date, args.date, args.date),
        ).fetchall()

        if not rows:
            print(f"company_gap_diagnosis date={args.date} gaps=0")
            return 0

        print(f"company_gap_diagnosis date={args.date} gaps={len(rows)}")
        unresolved_tickers: set[str] = set()
        for r in rows:
            ticker = str(r["ticker"] or "").strip()
            sig = conn.execute(
                "SELECT company,date,signal_id FROM signals WHERE ticker=? ORDER BY date DESC, signal_id DESC LIMIT 1",
                (ticker,),
            ).fetchone()
            td = conn.execute(
                "SELECT company,date,disclosed_at FROM tdnet_disclosures WHERE ticker=? ORDER BY date DESC, disclosed_at DESC LIMIT 1",
                (ticker,),
            ).fetchone()
            ins = conn.execute("SELECT name FROM instruments WHERE ticker=? LIMIT 1", (ticker,)).fetchone()
            sig_company = str(sig["company"] or "").strip() if sig else ""
            td_company = str(td["company"] or "").strip() if td else ""
            ins_name = str(ins["name"] or "").strip() if ins else ""
            print(
                f"- {r['tbl']} ticker={ticker} row_id={str(r['row_id'] or '')} "
                f"| signals={sig_company or '(none)'} "
                f"| tdnet={td_company or '(none)'} "
                f"| instruments={ins_name or '(none)'}"
            )
            if is_placeholder(sig_company) and is_placeholder(td_company) and is_placeholder(ins_name):
                unresolved_tickers.add(ticker)
        if unresolved_tickers:
            print("suggest_override:")
            for t in sorted(unresolved_tickers):
                print(f'  "{t}": "<company name>"')
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
