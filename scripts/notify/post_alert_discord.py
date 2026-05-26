#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sqlite3
import importlib.util
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JST = timezone(timedelta(hours=9))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def send_webhook(webhook_url: str, content: str) -> None:
    body = json.dumps({"content": content}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "aios-alert/1.0"},
    )
    with urllib.request.urlopen(req, timeout=20):
        return


def collect_daily_status() -> tuple[str, bool]:
    mod = load_module("check_daily_missing", ROOT / "scripts" / "check_daily_missing.py")

    target = mod.resolve_target_date("today")
    targets = [target - timedelta(days=1), target]
    missing_by_date = {}
    existing_by_date = {}
    for item in targets:
        files = mod.expected_files(item)
        missing_by_date[item] = [path for path in files if not path.exists()]
        existing_by_date[item] = [path for path in files if path.exists()]
    hard, soft = mod.db_warnings(
        targets,
        mod.ROOT / "data" / "topics.db",
        mod.ROOT / "data" / "investment.db",
        mod.ROOT / "data" / "needs.db",
    )
    hard2, soft2 = mod.discord_log_warnings(targets)
    warns = [f"[HARD] {w}" for w in hard + hard2] + [f"[SOFT] {w}" for w in soft + soft2]
    status = mod.build_status_text(targets, missing_by_date, existing_by_date, warns)
    total_missing = sum(len(paths) for paths in missing_by_date.values())
    return status, total_missing == 0 and not hard


def parse_ts(s: str) -> datetime | None:
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=JST)
        except ValueError:
            pass
    return None


def build_scheduler_payload() -> dict:
    mod = load_module("check_scheduler_health", ROOT / "scripts" / "check_scheduler_health.py")

    now = datetime.now(JST)
    cutoff = now - timedelta(hours=24)
    task_log = ROOT / "logs" / "task-scheduler.log"
    ops_db = ROOT / "data" / "ops.db"
    events = mod.load_task_events_from_db(ops_db, cutoff)
    if not events:
        events = mod.load_task_events(task_log, cutoff)

    per_task: dict[str, dict] = {}
    alerts: list[str] = []
    warns: list[str] = []
    for task_name in mod.DEFAULT_TASKS:
        ev = [x for x in events if x["task"] == task_name]
        starts = [x for x in ev if x["kind"] == "START"]
        oks = [x for x in ev if x["kind"] == "OK"]
        errs = [x for x in ev if x["kind"] in {"ERROR", "EXCEPTION"}]
        per_task[task_name] = {
            "start_count": len(starts),
            "ok_count": len(oks),
            "error_count": len(errs),
            "last_event": ev[-1]["line"] if ev else "",
        }
        if not ev:
            warns.append(f"{task_name}: lookback内イベントなし")
        if errs:
            alerts.append(f"{task_name}: ERROR {len(errs)}件")

    status = "ALERT" if alerts else "OK"
    return {
        "generatedAt": now.isoformat(timespec="seconds"),
        "status": status,
        "alerts": alerts,
        "warnings": warns,
        "tasks": per_task,
    }


def format_scheduler_status(payload: dict) -> str:
    lines = [f"Scheduler Health {datetime.now(JST).date().isoformat()} (daily)", f"- status: {payload['status']}"]
    alerts = payload.get("alerts") or []
    warns = payload.get("warnings") or []
    for item in alerts:
        lines.append(f"- {item}")
    if not alerts and warns:
        lines.append("- WARN only")
    for item in warns[:8]:
        lines.append(f"- {item}")
    return "\n".join(lines)


def collect_needs_weekly_status() -> str:
    path = ROOT / "data" / "needs.db"
    if not path.exists():
        return ""
    try:
        conn = sqlite3.connect(path)
        row = conn.execute("select max(date) from need_items").fetchone()
        conn.close()
    except Exception:
        return ""
    last_date = str(row[0]) if row and row[0] else ""
    today = datetime.now(JST).date().isoformat()
    if last_date and last_date >= today:
        return ""
    return f"needs.db 最終投入日: {last_date or '(none)'}"


def main() -> int:
    load_dotenv()
    webhook = os.getenv("DISCORD_ALERT_WEBHOOK_URL", "").strip()
    if not webhook:
        print("ALERT skipped (webhook empty)")
        return 0

    daily_status, daily_ok = collect_daily_status()
    scheduler_payload = build_scheduler_payload()
    sched_status = format_scheduler_status(scheduler_payload)
    sched_alert = scheduler_payload.get("status") == "ALERT"
    is_wednesday = datetime.now(JST).weekday() == 2
    needs_weekly = collect_needs_weekly_status() if is_wednesday else ""
    if daily_ok and not sched_alert and not needs_weekly:
        print("ALERT skipped (all healthy)")
        return 0

    msg = "AIOS Alert\n\n[DATA_INGEST / DAILY_COVERAGE]\n" + daily_status.strip()
    if sched_status:
        msg += "\n\n[SCHEDULER_RUNTIME]\n" + sched_status.strip()
    if needs_weekly:
        msg += "\n\n[NEEDS_WEEKLY_FRESHNESS]\n" + needs_weekly
    msg += f"\n\nAsOf: {datetime.now(JST).strftime('%Y-%m-%d %H:%M')} JST"
    send_webhook(webhook, msg)
    print("ALERT posted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
