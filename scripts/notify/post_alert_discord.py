#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sqlite3
import importlib.util
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db

JST = timezone(timedelta(hours=9))
INBOX = ROOT / "topics" / "investment-research" / "inbox"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_dotenv() -> None:
    for env_file in (ROOT / ".env.local", ROOT / ".env"):
        if not env_file.exists():
            continue
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
        resolve_investment_db(),
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
            warns.append(f"{task_name}: 参照期間内イベントなし")
        if errs:
            alerts.append(f"{task_name}: エラー {len(errs)}件")

    status = "ALERT" if alerts else "OK"
    return {
        "generatedAt": now.isoformat(timespec="seconds"),
        "status": status,
        "alerts": alerts,
        "warnings": warns,
        "tasks": per_task,
    }


def format_scheduler_status(payload: dict) -> str:
    status_label = {"ALERT": "警告", "OK": "正常"}.get(str(payload.get("status") or ""), str(payload.get("status") or "不明"))
    lines = [f"スケジューラ稼働状況 {datetime.now(JST).date().isoformat()}", f"- 状態: {status_label}"]
    alerts = payload.get("alerts") or []
    warns = payload.get("warnings") or []
    for item in alerts:
        lines.append(f"- {item}")
    if not alerts and warns:
        lines.append("- 警告のみ")
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


def collect_decision_support_warning_status() -> tuple[str, int]:
    files = sorted(INBOX.glob("*-decision-support-diff.json"))
    rows: list[tuple[str, str, list[str]]] = []
    for p in files[-20:]:
        name = p.name
        if len(name) < 10:
            continue
        ds = name[:10]
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        status = str(j.get("status", "")).strip().lower()
        warns = [str(x) for x in (j.get("warnings") or [])]
        rows.append((ds, status, warns))
    rows.sort(key=lambda x: x[0], reverse=True)
    if not rows:
        return ("decision-support-diff が未生成（観測開始前）", 0)

    streak = 0
    latest_date = rows[0][0]
    latest_warns: list[str] = rows[0][2]
    for _, st, _ in rows:
        if st == "warning":
            streak += 1
        else:
            break

    if streak >= 3:
        level = "要対応"
        lead = "警告が3営業日連続: 当日中に閾値調整タスクを対応"
    elif streak >= 2:
        level = "警告"
        lead = "警告が2営業日連続: 事前レビュー"
    else:
        level = "情報"
        lead = "警告の連続なし"
    detail = ", ".join(latest_warns) if latest_warns else "なし"
    text = (
        f"決定支援差分 {latest_date} ({level})\n"
        f"- 連続日数: {streak}\n"
        f"- 対応: {lead}\n"
        f"- 直近警告: {detail}"
    )
    return text, streak


def main() -> int:
    load_dotenv()
    webhook = os.getenv("DISCORD_ALERT_WEBHOOK_URL", "").strip()
    if not webhook:
        print("通知スキップ（webhook未設定）")
        return 0

    daily_status, daily_ok = collect_daily_status()
    scheduler_payload = build_scheduler_payload()
    sched_status = format_scheduler_status(scheduler_payload)
    sched_alert = scheduler_payload.get("status") == "ALERT"
    decision_support_status, ds_streak = collect_decision_support_warning_status()
    is_wednesday = datetime.now(JST).weekday() == 2
    needs_weekly = collect_needs_weekly_status() if is_wednesday else ""
    ds_alert = ds_streak >= 2
    if daily_ok and not sched_alert and not needs_weekly and not ds_alert:
        print("通知スキップ（全体正常）")
        return 0

    msg = "AIOS アラート\n\n[データ取り込み / 日次カバレッジ]\n" + daily_status.strip()
    if sched_status:
        msg += "\n\n[スケジューラ稼働]\n" + sched_status.strip()
    if decision_support_status:
        msg += "\n\n[投資シナリオ決定支援]\n" + decision_support_status.strip()
    if needs_weekly:
        msg += "\n\n[ニーズ週次鮮度]\n" + needs_weekly
    msg += f"\n\n基準時刻: {datetime.now(JST).strftime('%Y-%m-%d %H:%M')} JST"
    send_webhook(webhook, msg)
    print("通知送信")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
