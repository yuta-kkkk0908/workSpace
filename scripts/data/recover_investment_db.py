#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import sqlite3
from pathlib import Path


def fetch_table_names(conn: sqlite3.Connection, schema: str) -> list[str]:
    rows = conn.execute(
        f"""
        SELECT name
        FROM {schema}.sqlite_master
        WHERE type='table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [r[0] for r in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover malformed investment DB")
    parser.add_argument("--broken", required=True, help="Path to malformed DB file")
    parser.add_argument("--fresh", required=True, help="Path to initialized fresh DB file")
    parser.add_argument("--out", required=True, help="Path to write recovered DB file")
    args = parser.parse_args()

    broken = Path(args.broken)
    fresh = Path(args.fresh)
    out = Path(args.out)

    if not broken.exists():
        raise FileNotFoundError(f"broken DB not found: {broken}")
    if not fresh.exists():
        raise FileNotFoundError(f"fresh DB not found: {fresh}")

    if out.exists():
        out.unlink()
    shutil.copy2(fresh, out)

    conn = sqlite3.connect(str(out))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("ATTACH DATABASE ? AS broken", (str(broken),))

    dst_tables = set(fetch_table_names(conn, "main"))
    src_tables = fetch_table_names(conn, "broken")
    common_tables = [t for t in src_tables if t in dst_tables]

    copied = []
    skipped = []
    for idx, table in enumerate(common_tables, start=1):
        print(f"[{idx}/{len(common_tables)}] copying {table} ...", flush=True)
        try:
            conn.execute(f'DELETE FROM "{table}"')
            conn.execute(f'INSERT INTO "{table}" SELECT * FROM broken."{table}"')
            row_count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            copied.append((table, row_count))
            conn.commit()
            print(f"  OK {table}: {row_count}", flush=True)
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            skipped.append((table, str(e)))
            print(f"  FAIL {table}: {e}", flush=True)

    conn.execute("DETACH DATABASE broken")
    quick_check = conn.execute("PRAGMA quick_check").fetchone()
    conn.close()

    print("=== Recovery summary ===")
    print(f"copied tables: {len(copied)}")
    for name, count in copied:
        print(f"  OK   {name}: {count}")
    print(f"skipped tables: {len(skipped)}")
    for name, err in skipped:
        print(f"  FAIL {name}: {err}")
    print(f"quick_check: {quick_check[0] if quick_check else 'N/A'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
