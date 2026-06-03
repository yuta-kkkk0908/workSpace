#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db

DEFAULT_DB = resolve_investment_db()
INSTRUMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS instruments (
  ticker TEXT PRIMARY KEY,
  name TEXT,
  market TEXT,
  sector TEXT,
  credit_eligible TEXT,
  source_kind TEXT NOT NULL DEFAULT 'derived',
  updated_at TEXT NOT NULL
)
"""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill instruments.name from existing signals/tdnet_disclosures")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--date", default="", help="optional YYYY-MM-DD (prefer names up to this date)")
    return p.parse_args()


def reset_instruments_table(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS instruments")
    conn.execute(INSTRUMENTS_SCHEMA)
    conn.commit()


def instruments_accessible(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("SELECT COUNT(*) FROM instruments").fetchone()
        return True
    except sqlite3.DatabaseError:
        return False


def ensure_instrument_rows(conn: sqlite3.Connection, now: str) -> None:
    conn.execute(
        """
        INSERT INTO instruments(ticker,name,market,sector,credit_eligible,source_kind,updated_at)
        SELECT t.ticker,'','','','','derived',?
        FROM (
          SELECT DISTINCT ticker FROM signals WHERE COALESCE(ticker,'')<>''
          UNION
          SELECT DISTINCT ticker FROM tdnet_disclosures WHERE COALESCE(ticker,'')<>''
          UNION
          SELECT DISTINCT ticker FROM entry_candidates WHERE COALESCE(ticker,'')<>''
        ) t
        LEFT JOIN instruments i ON i.ticker=t.ticker
        WHERE i.ticker IS NULL
        """,
        (now,),
    )


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"db not found: {args.db}")
    conn = sqlite3.connect(args.db, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        # Normal path: keep existing table and just fill missing rows.
        # Only rebuild when the instruments table itself is unreadable.
        if instruments_accessible(conn):
            ensure_instrument_rows(conn, now)
        else:
            rebuilt = False
            for _ in range(3):
                try:
                    reset_instruments_table(conn)
                    ensure_instrument_rows(conn, now)
                    rebuilt = True
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower():
                        raise
                    time.sleep(3)
            if not rebuilt:
                raise sqlite3.OperationalError("database is locked while rebuilding instruments")

        if args.date:
            # Prioritize latest known company up to --date.
            rows = conn.execute(
                """
                WITH cands AS (
                  SELECT ticker, company AS name, date AS d, 1 AS pr
                  FROM signals
                  WHERE COALESCE(ticker,'')<>'' AND COALESCE(NULLIF(TRIM(company),''),'')<>''
                    AND date<=?
                  UNION ALL
                  SELECT ticker, company AS name, date AS d, 2 AS pr
                  FROM tdnet_disclosures
                  WHERE COALESCE(ticker,'')<>'' AND COALESCE(NULLIF(TRIM(company),''),'')<>''
                    AND date<=?
                ),
                ranked AS (
                  SELECT ticker,name,d,pr,
                         ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY d DESC, pr ASC) AS rn
                  FROM cands
                )
                SELECT ticker,name FROM ranked WHERE rn=1
                """,
                (args.date, args.date),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                WITH cands AS (
                  SELECT ticker, company AS name, date AS d, 1 AS pr
                  FROM signals
                  WHERE COALESCE(ticker,'')<>'' AND COALESCE(NULLIF(TRIM(company),''),'')<>''
                  UNION ALL
                  SELECT ticker, company AS name, date AS d, 2 AS pr
                  FROM tdnet_disclosures
                  WHERE COALESCE(ticker,'')<>'' AND COALESCE(NULLIF(TRIM(company),''),'')<>''
                ),
                ranked AS (
                  SELECT ticker,name,d,pr,
                         ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY d DESC, pr ASC) AS rn
                  FROM cands
                )
                SELECT ticker,name FROM ranked WHERE rn=1
                """
            ).fetchall()

        updated = 0
        for t, name in rows:
            t = str(t or "").strip()
            n = str(name or "").strip()
            if not t or not n:
                continue
            conn.execute(
                """
                UPDATE instruments
                SET name=?, updated_at=?
                WHERE ticker=?
                """,
                (n, now, t),
            )
            updated += 1
        conn.commit()
        total = int(conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0] or 0)
        print(f"instrument_names_backfilled updated={updated} total={total}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
