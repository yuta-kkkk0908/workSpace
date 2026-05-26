#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DBS = [ROOT / "data" / "investment.db", ROOT / "data" / "ops.db", ROOT / "data" / "topics.db", ROOT / "data" / "needs.db"]


REPLACEMENTS = {
    "諠・ｱ譎らせ": "AsOf",
    "譎らせ": "AsOf",
    "蜀・ｨｳ": "内訳",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fix known mojibake strings in sqlite text columns")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    total_updates = 0
    for dbp in DEFAULT_DBS:
        if not dbp.exists():
            continue
        conn = sqlite3.connect(dbp)
        try:
            cur = conn.cursor()
            tables = [r[0] for r in cur.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'").fetchall()]
            for t in tables:
                cols = cur.execute(f"pragma table_info({t})").fetchall()
                txt_cols = [c[1] for c in cols if "TEXT" in str(c[2]).upper()]
                for c in txt_cols:
                    for bad, good in REPLACEMENTS.items():
                        q = f"select count(*) from {t} where {c} like ?"
                        n = int((cur.execute(q, (f"%{bad}%",)).fetchone() or [0])[0] or 0)
                        if n <= 0:
                            continue
                        print(f"{dbp.name}:{t}.{c} replace '{bad}' -> '{good}' rows={n}")
                        if not args.dry_run:
                            uq = f"update {t} set {c}=replace({c}, ?, ?) where {c} like ?"
                            cur.execute(uq, (bad, good, f"%{bad}%"))
                            total_updates += cur.rowcount if cur.rowcount is not None else n
            if not args.dry_run:
                conn.commit()
        finally:
            conn.close()
    print(f"done dry_run={args.dry_run} updated={total_updates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
