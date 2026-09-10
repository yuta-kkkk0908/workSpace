#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.request
import uuid
import zipfile
from datetime import datetime
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db
from utils.env_loader import load_env_files

DATA_DIR = ROOT / "data"
BACKUP_DIR = DATA_DIR / "backups"
MANIFEST_PATH = BACKUP_DIR / "discord-backups-manifest.json"


def load_dotenv() -> None:
    load_env_files(ROOT / ".env.local", ROOT / ".env")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Zip and upload investment.db to Discord webhook")
    p.add_argument("--db", default=str(resolve_investment_db()))
    p.add_argument("--label", default="investment-db-backup")
    p.add_argument("--keep-local", type=int, default=14, help="Number of local zip files to keep")
    p.add_argument("--retention-days", type=int, default=14, help="Delete Discord backup posts older than this")
    return p.parse_args()


def create_zip(src_db: Path, label: str) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    zip_name = f"{label}-{ts}.zip"
    zip_path = BACKUP_DIR / zip_name
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(src_db, arcname="investment.db")
    return zip_path


def sqlite_safe_snapshot(src_db: Path, dst_db: Path) -> None:
    """
    Create a consistent snapshot using SQLite backup API.
    Avoid raw file copy while WAL is active.
    """
    if dst_db.exists():
        dst_db.unlink()
    src = sqlite3.connect(f"file:{src_db}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(dst_db))
        try:
            src.backup(dst)
            dst.commit()
        finally:
            dst.close()
    finally:
        src.close()


def build_multipart(fields: dict[str, str], file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = f"----CodexBoundary{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for k, v in fields.items():
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{k}"\r\n\r\n'
                f"{v}\r\n"
            ).encode("utf-8")
        )
    file_name = file_path.name
    mime = "application/zip"
    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{file_field}"; filename="{file_name}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode("utf-8")
    )
    parts.append(file_path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    return body, boundary


def upload_to_discord(webhook_url: str, zip_path: Path, label: str) -> dict:
    meta = {"label": label, "file": zip_path.name, "created_at": datetime.now().isoformat(timespec="seconds")}
    fields = {
        "content": f"[DB BACKUP] {zip_path.name}",
        "payload_json": json.dumps({"content": f"[DB BACKUP] {zip_path.name}", "allowed_mentions": {"parse": []}, "embeds": [{"title": "SQLite Backup", "description": json.dumps(meta, ensure_ascii=False)}]}, ensure_ascii=False),
    }
    body, boundary = build_multipart(fields, "files[0]", zip_path)
    req = urllib.request.Request(
        webhook_url + "?wait=true",
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "aios-db-backup/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def update_manifest(entry: dict) -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    if MANIFEST_PATH.exists():
        try:
            manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except Exception:
            manifest = []
    manifest.insert(0, entry)
    MANIFEST_PATH.write_text(json.dumps(manifest[:200], ensure_ascii=False, indent=2), encoding="utf-8")


def load_manifest() -> list[dict]:
    if not MANIFEST_PATH.exists():
        return []
    try:
        rows = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        rows = []
    return rows if isinstance(rows, list) else []


def save_manifest(rows: list[dict]) -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(rows[:200], ensure_ascii=False, indent=2), encoding="utf-8")


def delete_discord_message(token: str, channel_id: str, message_id: str) -> bool:
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}",
        method="DELETE",
        headers={"Authorization": f"Bot {token}", "User-Agent": "aios-db-backup/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30):
            return True
    except Exception:
        return False


def prune_discord_backups(retention_days: int) -> tuple[int, int]:
    rows = load_manifest()
    if not rows:
        return 0, 0
    token = os.getenv("DISCORD_TASKS_BOT_TOKEN", "").strip()
    if not token:
        return 0, 0
    now = datetime.now()
    cutoff = now - timedelta(days=max(1, retention_days))
    kept: list[dict] = []
    deleted = 0
    failed = 0
    for row in rows:
        created_at_raw = str(row.get("created_at") or "")
        try:
            created_at = datetime.fromisoformat(created_at_raw)
        except Exception:
            kept.append(row)
            continue
        if created_at >= cutoff:
            kept.append(row)
            continue
        channel_id = str(row.get("channel_id") or os.getenv("DISCORD_BACKUP_CHANNEL_ID", "").strip() or "")
        message_id = str(row.get("message_id") or "")
        if not channel_id or not message_id:
            failed += 1
            continue
        if delete_discord_message(token, channel_id, message_id):
            deleted += 1
            continue
        failed += 1
        kept.append(row)
    save_manifest(kept)
    return deleted, failed


def cleanup_local_backups(keep: int) -> None:
    zips = sorted(BACKUP_DIR.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in zips[keep:]:
        p.unlink(missing_ok=True)


def main() -> int:
    args = parse_args()
    load_dotenv()
    # Run retention even when a later upload step fails, so local archives do
    # not grow indefinitely after a transient Discord/network failure.
    cleanup_local_backups(max(1, int(args.keep_local)))
    webhook = os.getenv("DISCORD_BACKUPPER_URL", "").strip()
    if not webhook:
        raise SystemExit("DISCORD_BACKUPPER_URL is empty")
    src_db = Path(args.db)
    if not src_db.exists():
        raise SystemExit(f"DB not found: {src_db}")
    src_db_real = src_db.resolve()

    tmp_copy = BACKUP_DIR / "investment.db.snapshot"
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    sqlite_safe_snapshot(src_db_real, tmp_copy)
    zip_path = create_zip(tmp_copy, args.label)
    tmp_copy.unlink(missing_ok=True)

    resp = upload_to_discord(webhook, zip_path, args.label)
    attachments = resp.get("attachments") or []
    a0 = attachments[0] if attachments else {}
    entry = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "zip_file": str(zip_path),
        "db_arg": str(src_db),
        "db_real": str(src_db_real),
        "message_id": resp.get("id"),
        "channel_id": resp.get("channel_id"),
        "attachment_url": a0.get("url"),
        "attachment_filename": a0.get("filename"),
    }
    update_manifest(entry)
    cleanup_local_backups(max(1, int(args.keep_local)))
    deleted, failed = prune_discord_backups(int(args.retention_days))
    entry["pruned_deleted"] = deleted
    entry["pruned_failed"] = failed
    print(json.dumps(entry, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
