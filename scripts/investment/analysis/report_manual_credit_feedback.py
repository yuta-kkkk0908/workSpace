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
    p = argparse.ArgumentParser(description="Report manual credit feedback from scenario replies")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT c.date,c.ticker,c.credit_status,c.buy_status,c.sell_status,c.source_kind,c.source_detail,c.updated_at,
                   (
                     SELECT s.company FROM signals s
                     WHERE s.ticker=c.ticker
                     ORDER BY s.date DESC LIMIT 1
                   ) as company
            FROM credit_status_rows c
            WHERE c.date=?
            ORDER BY c.updated_at DESC, c.ticker
            """,
            (args.date,),
        ).fetchall()
    finally:
        conn.close()

    items = [dict(r) for r in rows]
    out_json = OUT / f"{args.date}-manual-credit-feedback.json"
    out_md = OUT / f"{args.date}-manual-credit-feedback.md"
    out_json.write_text(json.dumps({"date": args.date, "rows": items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        f"# {args.date} Manual Credit Feedback",
        "",
        "- source: db:credit_status_rows",
        f"- rows: {len(items)}",
        "",
        "## Entries",
    ]
    if not items:
        lines.append("- none")
    else:
        for r in items:
            lines.append(
                f"- {r.get('ticker','')} {r.get('company','') or ''} / {r.get('credit_status','')} (buy={r.get('buy_status','') or '-'} sell={r.get('sell_status','') or '-'}) / source={r.get('source_kind','')} / updated={r.get('updated_at','')}"
            )
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out_md.relative_to(ROOT)}")
    print(f"wrote {out_json.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
