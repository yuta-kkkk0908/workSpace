#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill instruments.name from existing signals/tdnet_disclosures")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--date", default="", help="optional YYYY-MM-DD (prefer names up to this date)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"db not found: {args.db}")
    conn = sqlite3.connect(args.db)
    try:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        # Ensure instruments rows exist for tickers seen in core tables.
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
        print(f"instrument_names_backfilled updated={updated}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

