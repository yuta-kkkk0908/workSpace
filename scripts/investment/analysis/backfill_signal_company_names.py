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
    p = argparse.ArgumentParser(description="Backfill placeholder company names in signals/entry_candidates/opening_scenarios")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--date", help="target date YYYY-MM-DD (optional)")
    return p.parse_args()


def is_placeholder(v: str) -> bool:
    s = (v or "").strip()
    if not s:
        return True
    return s.upper() in {"不明", "-", "N/A", "NA", "UNKNOWN"}


def resolve_company(conn: sqlite3.Connection, ticker: str, asof: str) -> str:
    row = conn.execute(
        "SELECT company FROM signals WHERE ticker=? AND date<=? AND company IS NOT NULL ORDER BY date DESC, signal_id DESC LIMIT 1",
        (ticker, asof),
    ).fetchone()
    if row and not is_placeholder(str(row[0] or "")):
        return str(row[0] or "").strip()
    row = conn.execute(
        "SELECT company FROM tdnet_disclosures WHERE ticker=? AND date<=? AND company IS NOT NULL ORDER BY date DESC, disclosed_at DESC LIMIT 1",
        (ticker, asof),
    ).fetchone()
    if row and not is_placeholder(str(row[0] or "")):
        return str(row[0] or "").strip()
    try:
        row = conn.execute("SELECT name FROM instruments WHERE ticker=? LIMIT 1", (ticker,)).fetchone()
        if row and not is_placeholder(str(row[0] or "")):
            return str(row[0] or "").strip()
    except sqlite3.DatabaseError:
        # Keep company backfill alive even if instruments is temporarily broken.
        pass
    return ""


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        where_date = " AND date=?" if args.date else ""
        params = (args.date,) if args.date else tuple()
        rows = conn.execute(
            f"SELECT date,ticker,company,signal_id FROM signals WHERE COALESCE(ticker,'')<>''{where_date} ORDER BY date,signal_id",
            params,
        ).fetchall()
        updates = 0
        for d, t, c, sid in rows:
            if not is_placeholder(str(c or "")):
                continue
            name = resolve_company(conn, str(t or "").strip(), str(d or ""))
            if not name:
                continue
            conn.execute("UPDATE signals SET company=? WHERE date=? AND signal_id=?", (name, d, sid))
            updates += 1

        rows = conn.execute(
            f"SELECT date,side,candidate_type,signal_id,ticker,company FROM entry_candidates WHERE COALESCE(ticker,'')<>''{where_date}",
            params,
        ).fetchall()
        for d, side, ctype, sid, t, c in rows:
            if not is_placeholder(str(c or "")):
                continue
            name = resolve_company(conn, str(t or "").strip(), str(d or ""))
            if not name:
                continue
            conn.execute(
                "UPDATE entry_candidates SET company=? WHERE date=? AND side=? AND candidate_type=? AND signal_id=?",
                (name, d, side, ctype, sid),
            )
            updates += 1

        rows = conn.execute(
            f"SELECT scenario_date,ticker,direction,signal_id,company FROM opening_scenarios WHERE COALESCE(ticker,'')<>''" +
            (" AND scenario_date=?" if args.date else ""),
            params,
        ).fetchall()
        for d, t, direction, sid, c in rows:
            if not is_placeholder(str(c or "")):
                continue
            name = resolve_company(conn, str(t or "").strip(), str(d or ""))
            if not name:
                continue
            conn.execute(
                "UPDATE opening_scenarios SET company=? WHERE scenario_date=? AND ticker=? AND direction=? AND COALESCE(signal_id,'')=COALESCE(?, '')",
                (name, d, t, direction, sid),
            )
            updates += 1

        conn.commit()
    finally:
        conn.close()
    print(f"backfill_signal_company_names updates={updates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
