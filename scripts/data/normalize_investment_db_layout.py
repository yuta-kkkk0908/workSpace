#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Normalize investment DB to stable main-file + symlink layout")
    p.add_argument("--db-link", default=str(DATA_DIR / "investment.db"))
    p.add_argument("--db-main", default=str(DATA_DIR / "investment.main.db"))
    p.add_argument("--source", default=str(DATA_DIR / "investment.ingestfix.db"))
    return p.parse_args()


def sqlite_ok(path: Path) -> bool:
    try:
        conn = sqlite3.connect(str(path))
        try:
            row = conn.execute("PRAGMA quick_check").fetchone()
            return bool(row and row[0] == "ok")
        finally:
            conn.close()
    except Exception:
        return False


def main() -> int:
    args = parse_args()
    db_link = Path(args.db_link)
    db_main = Path(args.db_main)
    source = Path(args.source)

    if not source.exists():
        raise SystemExit(f"source DB not found: {source}")
    if not sqlite_ok(source):
        raise SystemExit(f"source DB failed quick_check: {source}")

    db_main.parent.mkdir(parents=True, exist_ok=True)
    tmp_main = db_main.with_suffix(db_main.suffix + ".tmp")
    if tmp_main.exists():
        tmp_main.unlink()
    shutil.copyfile(source, tmp_main)
    if db_main.exists() or db_main.is_symlink():
        db_main.unlink()
    tmp_main.rename(db_main)

    if db_link.exists() or db_link.is_symlink():
        db_link.unlink()
    db_link.symlink_to(db_main.name)

    print(f"normalized: link={db_link} -> {db_main.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
