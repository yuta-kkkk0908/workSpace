#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
BACKUP_DIR = DATA_DIR / "backups"
MANIFEST_PATH = BACKUP_DIR / "discord-backups-manifest.json"


def load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Restore investment.db from Discord backup message")
    p.add_argument("--channel-id", default="", help="Discord channel id containing backup message")
    p.add_argument("--message-id", default="", help="Discord message id with zip attachment")
    p.add_argument("--target-db", default=str(DATA_DIR / "investment.db"))
    return p.parse_args()


def load_latest_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        raise SystemExit("Backup manifest not found. Please specify --channel-id/--message-id.")
    rows = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not rows:
        raise SystemExit("Backup manifest is empty.")
    return rows[0]


def fetch_message(token: str, channel_id: str, message_id: str) -> dict:
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}",
        method="GET",
        headers={"Authorization": f"Bot {token}", "User-Agent": "aios-db-restore/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download_attachment(url: str, token: str, dest: Path) -> None:
    req = urllib.request.Request(
        url,
        method="GET",
        headers={"Authorization": f"Bot {token}", "User-Agent": "aios-db-restore/1.0"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        dest.write_bytes(resp.read())


def run_recovery_if_needed(extracted_db: Path, out_db: Path) -> Path:
    import sqlite3

    try:
        conn = sqlite3.connect(str(extracted_db))
        qc = conn.execute("PRAGMA quick_check").fetchone()[0]
        conn.close()
        if qc == "ok":
            shutil.copy2(extracted_db, out_db)
            return out_db
    except Exception:
        pass

    fresh = DATA_DIR / "investment.restore.fresh.db"
    recovered = DATA_DIR / "investment.restore.recovered.db"
    subprocess.run(["python3", "scripts/data/init_investment_db.py", "--db", str(fresh)], cwd=ROOT, check=True)
    subprocess.run(
        [
            "python3",
            "scripts/data/recover_investment_db.py",
            "--broken",
            str(extracted_db),
            "--fresh",
            str(fresh),
            "--out",
            str(recovered),
        ],
        cwd=ROOT,
        check=True,
    )
    shutil.copy2(recovered, out_db)
    return out_db


def main() -> int:
    args = parse_args()
    load_dotenv()
    token = os.getenv("DISCORD_TASKS_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("DISCORD_TASKS_BOT_TOKEN is empty")

    channel_id = args.channel_id.strip()
    message_id = args.message_id.strip()
    if not channel_id:
        channel_id = os.getenv("DISCORD_BACKUP_CHANNEL_ID", "").strip()
    if not channel_id or not message_id:
        latest = load_latest_manifest()
        channel_id = channel_id or str(latest.get("channel_id") or "")
        message_id = message_id or str(latest.get("message_id") or "")
    if not channel_id or not message_id:
        raise SystemExit("channel/message id is unresolved. pass --channel-id and --message-id.")

    msg = fetch_message(token, channel_id, message_id)
    attachments = msg.get("attachments") or []
    if not attachments:
        raise SystemExit("No attachment in target message.")
    attachment = attachments[0]
    url = attachment.get("url")
    if not url:
        raise SystemExit("Attachment URL missing.")

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = BACKUP_DIR / f"restore-download-{ts}.zip"
    extract_dir = BACKUP_DIR / f"restore-extract-{ts}"
    extract_dir.mkdir(parents=True, exist_ok=True)
    download_attachment(url, token, zip_path)

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)
    extracted_db = extract_dir / "investment.db"
    if not extracted_db.exists():
        found = list(extract_dir.rglob("*.db"))
        if not found:
            raise SystemExit("No .db file in downloaded zip")
        extracted_db = found[0]

    target_db = Path(args.target_db)
    pre = target_db.parent / f"{target_db.name}.pre-restore-{ts}"
    if target_db.exists():
        shutil.copy2(target_db, pre)

    run_recovery_if_needed(extracted_db, target_db)
    print(
        json.dumps(
            {
                "restored_to": str(target_db),
                "previous_backup": str(pre) if pre.exists() else "",
                "channel_id": channel_id,
                "message_id": message_id,
                "downloaded_zip": str(zip_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
