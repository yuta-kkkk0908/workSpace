#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
PROMPTS_DIR = ROOT / "prompts"
DATA_DIR = ROOT / "data"
JST = timezone(timedelta(hours=9))
DEFAULT_OPS_DB = DATA_DIR / "ops.db"

DEFAULT_TASKS = [
    "AIOS-Night",
    "AIOS-Inv-Morning",
    "AIOS-Inv-Noon",
    "AIOS-Inv-Evening",
    "AIOS-Inv-Scenario-0810",
]

LINE_RE = re.compile(r"^\[(?P<ts>[^\]]+)\]\s+\[(?P<task>[^\]]+)\]\s+\[(?P<kind>[^\]]+)\]")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Check scheduler/task health from local logs")
    p.add_argument("--mode", choices=["daily", "weekly"], default="daily")
    p.add_argument("--hours", type=int, default=24, help="lookback hours")
    p.add_argument("--tasks", nargs="*", default=DEFAULT_TASKS)
    p.add_argument("--task-log", default=str((LOG_DIR / "task-scheduler.log").relative_to(ROOT)))
    p.add_argument("--out-json", default=str((PROMPTS_DIR / "scheduler-health.json").relative_to(ROOT)))
    p.add_argument("--out-status", default=str((PROMPTS_DIR / "scheduler-health.status.txt").relative_to(ROOT)))
    p.add_argument("--ops-db", default=str(DEFAULT_OPS_DB.relative_to(ROOT)))
    return p.parse_args()


def parse_ts(s: str) -> datetime | None:
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=JST)
        except ValueError:
            pass
    return None


def load_task_events(path: Path, cutoff: datetime) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = LINE_RE.match(raw.strip())
        if not m:
            continue
        ts = parse_ts(m.group("ts"))
        if ts is None or ts < cutoff:
            continue
        out.append(
            {
                "ts": ts.isoformat(),
                "task": m.group("task"),
                "kind": m.group("kind"),
                "line": raw.strip(),
            }
        )
    return out


def load_task_events_from_db(db_path: Path, cutoff: datetime) -> list[dict]:
    if not db_path.exists():
        return []
    cutoff_s = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT ts,task_name,level,message
            FROM task_log_events
            WHERE ts >= ?
            ORDER BY ts
            """,
            (cutoff_s,),
        ).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return []
    finally:
        conn.close()
    out = []
    for ts, task, level, msg in rows:
        out.append({"ts": str(ts), "task": str(task), "kind": str(level), "line": f"[{ts}] [{task}] [{level}] {msg}"})
    return out


def latest_log_age_minutes(path: Path, now: datetime) -> float | None:
    if not path.exists():
        return None
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=JST)
    return (now - mtime).total_seconds() / 60.0


def main() -> int:
    args = parse_args()
    now = datetime.now(JST)
    cutoff = now - timedelta(hours=max(1, args.hours))
    task_log = ROOT / args.task_log
    ops_db = ROOT / args.ops_db
    events = load_task_events_from_db(ops_db, cutoff)
    if not events:
        events = load_task_events(task_log, cutoff)

    per_task: dict[str, dict] = {}
    alerts: list[str] = []
    warns: list[str] = []
    db_alerts: list[str] = []

    for t in args.tasks:
        ev = [x for x in events if x["task"] == t]
        starts = [x for x in ev if x["kind"] == "START"]
        oks = [x for x in ev if x["kind"] == "OK"]
        errs = [x for x in ev if x["kind"] == "ERROR"]
        per_task[t] = {
            "start_count": len(starts),
            "ok_count": len(oks),
            "error_count": len(errs),
            "last_event": ev[-1]["line"] if ev else "",
        }
        if not ev:
            warns.append(f"{t}: lookback内イベントなし")
        if errs:
            alerts.append(f"{t}: ERROR {len(errs)}件")

    # DB integrity check for backtest_outcomes duplicate identity.
    inv_db = DATA_DIR / "investment.db"
    if inv_db.exists():
        try:
            conn = sqlite3.connect(inv_db)
            dup_groups = conn.execute(
                """
                SELECT COUNT(*)
                FROM (
                  SELECT 1
                  FROM backtest_outcomes
                  WHERE COALESCE(source_signal_id,'')<>'' AND COALESCE(signal_date,'')<>'' AND COALESCE(signal_type,'')<>''
                  GROUP BY source_signal_id, signal_date, signal_type
                  HAVING COUNT(*) > 1
                ) x
                """
            ).fetchone()[0]
            conn.close()
            if dup_groups > 0:
                db_alerts.append(f"backtest_outcomes duplicate identity groups={dup_groups}")
        except Exception as e:
            warns.append(f"investment.db duplicate check failed: {type(e).__name__}")

    # Posting logs freshness checks (best-effort)
    log_targets = {
        "discord-signal.log": 24 * 60,
        "discord-generic.log": 48 * 60,
        "discord-scenario.log": 48 * 60,
        "discord-paper-stats.log": 48 * 60,
    }
    freshness: dict[str, float | None] = {}
    channel_map = {
        "discord-signal.log": "signal",
        "discord-generic.log": "generic",
        "discord-scenario.log": "scenario",
        "discord-paper-stats.log": "paper_stats",
    }
    db_fresh: dict[str, float | None] = {}
    if ops_db.exists():
        conn = sqlite3.connect(ops_db)
        try:
            for log_name, channel in channel_map.items():
                row = conn.execute("SELECT max(ts) FROM discord_log_events WHERE channel=?", (channel,)).fetchone()
                ts = row[0] if row else None
                if ts:
                    dt = parse_ts(str(ts))
                    db_fresh[log_name] = ((now - dt).total_seconds() / 60.0) if dt else None
                else:
                    db_fresh[log_name] = None
        except sqlite3.OperationalError:
            db_fresh = {}
        finally:
            conn.close()
    for name, limit_min in log_targets.items():
        age = db_fresh.get(name)
        if age is None:
            p = LOG_DIR / name
            age = latest_log_age_minutes(p, now)
        freshness[name] = age
        if age is None:
            warns.append(f"{name}: データなし")
        elif age > limit_min:
            warns.append(f"{name}: 更新遅延 {age:.0f}分")

    alerts.extend(db_alerts)
    status = "ALERT" if alerts else "OK"

    def choose_action() -> str:
        joined = "\n".join(alerts + warns).lower()
        if status == "OK" and not warns:
            return "点検"
        if "needs.db need_items" in joined:
            return "ニーズ補完"
        if "signals 未投入" in joined or any("AIOS-Inv-" in a for a in alerts):
            return "投資補完"
        if "topics.db 未投入" in joined or "daily missing" in joined:
            return "話題補完"
        if alerts:
            return "全部"
        return "点検補完"

    recommended_action = choose_action()
    payload = {
        "generatedAt": now.isoformat(timespec="seconds"),
        "lookbackHours": int(args.hours),
        "status": status,
        "alerts": alerts,
        "warnings": warns,
        "tasks": per_task,
        "freshnessMinutes": freshness,
        "taskLog": str(task_log.relative_to(ROOT)),
        "recommendedKeyword": recommended_action,
    }

    out_json = ROOT / args.out_json
    out_status = ROOT / args.out_status
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_status.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [f"Scheduler Health {now.date().isoformat()} ({args.mode})", f"- status: {status}"]
    for a in alerts:
        lines.append(f"- {a}")
    if not alerts and warns:
        lines.append("- WARN only")
    for w in warns[:8]:
        lines.append(f"- {w}")
    lines.append(f"- 推奨キーワード: {recommended_action}")
    lines.append("- 実行: python scripts/ops/keyword_action.py <推奨キーワード>")
    if args.mode == "weekly":
        lines.append("- weekly-summary:")
        lines.append(f"  - lookbackHours: {int(args.hours)}")
        lines.append(f"  - taskCount: {len(per_task)}")
        total_start = sum(v["start_count"] for v in per_task.values())
        total_ok = sum(v["ok_count"] for v in per_task.values())
        total_err = sum(v["error_count"] for v in per_task.values())
        lines.append(f"  - totals: start={total_start} ok={total_ok} error={total_err}")
        for name, stat in per_task.items():
            lines.append(
                f"  - {name}: start={stat['start_count']} ok={stat['ok_count']} error={stat['error_count']}"
            )
        for k, age in freshness.items():
            if age is None:
                lines.append(f"  - freshness {k}: missing")
            else:
                lines.append(f"  - freshness {k}: {age:.0f} min")
    lines.append(f"- metrics: {out_json.relative_to(ROOT)}")
    out_status.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"{status}: {out_status.relative_to(ROOT)}")
    return 2 if alerts else 0


if __name__ == "__main__":
    raise SystemExit(main())
