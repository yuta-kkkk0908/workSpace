#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if not (ROOT / "doc").exists():
    ROOT = Path.cwd()
DEFAULT_DB = ROOT / "data" / "investment.db"
DEFAULT_OUT = ROOT / "doc" / "investment-db-table-inventory.md"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build inventory of investment DB tables/views")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return p.parse_args()


def classify(name: str) -> str:
    if name.startswith(("raw_",)):
        return "raw"
    if name.startswith(("facts_", "signals", "entry_candidates", "backtest_outcomes", "opening_scenarios", "execution_plan")):
        return "facts"
    if name.startswith(("instruments", "credit_", "sector_", "market_", "technical_", "margin_", "board_")):
        return "dimensions"
    return "ops"


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    try:
        objects = conn.execute(
            """
            SELECT name,type
            FROM sqlite_master
            WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'
            ORDER BY type,name
            """
        ).fetchall()
        lines = ["# Investment DB Table Inventory", ""]
        lines.append("| object | kind | domain | primary_key | unique_indexes |")
        lines.append("|---|---|---|---|---|")
        for name, kind in objects:
            pk_cols = [
                r[1]
                for r in conn.execute(f"PRAGMA table_info({name})").fetchall()
                if int(r[5] or 0) > 0
            ]
            pk = ",".join(pk_cols) if pk_cols else "-"
            unique_idx = []
            for idx in conn.execute(f"PRAGMA index_list({name})").fetchall():
                idx_name = idx[1]
                is_unique = int(idx[2] or 0) == 1
                if not is_unique:
                    continue
                cols = [r[2] for r in conn.execute(f"PRAGMA index_info({idx_name})").fetchall()]
                unique_idx.append(f"{idx_name}({','.join(cols)})")
            uniq = "<br>".join(unique_idx) if unique_idx else "-"
            lines.append(f"| {name} | {kind} | {classify(name)} | {pk} | {uniq} |")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    finally:
        conn.close()
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
