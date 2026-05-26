#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"
DEFAULT_DIR = ROOT / "resource" / "invest"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest manually collected JPX files from resource/invest")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    p.add_argument("--post-action", choices=["keep", "archive", "delete"], default="archive")
    return p.parse_args()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main() -> int:
    args = parse_args()
    now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    files = sorted([p for p in args.dir.glob("*") if p.is_file()])
    archive_dir = args.dir / "processed" / args.date.replace("-", "")
    if args.post_action == "archive":
        archive_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    try:
        upserted = 0
        unsupported = 0
        archived = 0
        deleted = 0
        for p in files:
            ext = p.suffix.lower()
            kind = {
                ".pdf": "pdf_backfill",
                ".xlsx": "xlsx_candidate",
                ".xls": "xls_candidate",
                ".csv": "csv_candidate",
            }.get(ext, "other")
            payload = {
                "date": args.date,
                "local_path": str(p),
                "file_name": p.name,
                "ext": ext,
                "kind": kind,
                "size_bytes": p.stat().st_size,
                "sha256": sha256_file(p),
            }
            if kind in ("xls_candidate", "xlsx_candidate"):
                payload["parse_status"] = "pending_parser"
            elif kind == "pdf_backfill":
                payload["parse_status"] = "pdf_backfill_lane"
            elif kind == "csv_candidate":
                payload["parse_status"] = "ready"
            else:
                payload["parse_status"] = "unsupported"
                unsupported += 1

            event_hash = hashlib.sha256(f"{args.date}|{p.name}|{payload['sha256']}".encode("utf-8")).hexdigest()
            conn.execute(
                """
                INSERT INTO raw_events(
                  event_hash,source_kind,source_url,event_time,ticker,ingest_date,fetched_at,payload_json,source_path,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source_kind,event_hash) DO UPDATE SET
                  fetched_at=excluded.fetched_at,
                  payload_json=excluded.payload_json,
                  updated_at=excluded.updated_at
                """,
                (
                    event_hash,
                    "jpx_resource_file",
                    str(p),
                    f"{args.date}T00:00:00+09:00",
                    "",
                    args.date,
                    now_utc,
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    "scripts/investment/collect/ingest_jpx_resource_files.py",
                    now_utc,
                ),
            )
            upserted += 1
            if args.post_action == "archive":
                dst = archive_dir / p.name
                if dst.exists():
                    dst = archive_dir / f"{p.stem}-{payload['sha256'][:8]}{p.suffix}"
                shutil.move(str(p), str(dst))
                archived += 1
            elif args.post_action == "delete":
                p.unlink(missing_ok=True)
                deleted += 1

        conn.execute(
            """
            INSERT INTO collection_progress(source,partition_key,last_date,status,last_run_at,error_message,updated_at)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(source,partition_key) DO UPDATE SET
              last_date=excluded.last_date,
              status=excluded.status,
              last_run_at=excluded.last_run_at,
              error_message=excluded.error_message,
              updated_at=excluded.updated_at
            """,
            ("jpx_resource_ingest", "resource/invest", args.date, "ok", now_utc, "", now_utc),
        )
        conn.commit()
    finally:
        conn.close()

    print(
        f"jpx_resource_ingest date={args.date} files={len(files)} upserted={upserted} "
        f"unsupported={unsupported} post_action={args.post_action} archived={archived if 'archived' in locals() else 0} "
        f"deleted={deleted if 'deleted' in locals() else 0}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
