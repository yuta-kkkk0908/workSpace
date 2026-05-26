#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import sqlite3
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TASK_DB = ROOT / "data" / "ops.db"
DEFAULT_MEMORY_DB = ROOT / "data" / "ops.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sync Discord tasks channel and execute approved ops commands")
    p.add_argument("--task-db", default=str(DEFAULT_TASK_DB))
    p.add_argument("--memory-db", default=str(DEFAULT_MEMORY_DB))
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--exec-timeout-sec", type=int, default=1800)
    p.add_argument("--post-run-summary", action="store_true", help="post poll summary to task channel")
    return p.parse_args()


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


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_env() -> tuple[str, str]:
    token = (
        os.getenv("DISCORD_TASKS_BOT_TOKEN", "").strip()
        or os.getenv("DISCORD_TASK_BOT_TOKEN", "").strip()
        or os.getenv("DISCORD_SCENARIOS_BOT_TOKEN", "").strip()
        or os.getenv("DISCORD_SCENARIO_BOT_TOKEN", "").strip()
        or os.getenv("DISCORD_BOT_TOKEN", "").strip()
        or os.getenv("DISCORD_TOKEN", "").strip()
    )
    channel_id = (
        os.getenv("DISCORD_TASK_CHANNEL_ID", "").strip()
        or os.getenv("DISCORD_TAKS_CHANNEL_ID", "").strip()
        or os.getenv("DISCORD_TASKS_CHANNEL_ID", "").strip()
    )
    if not token:
        raise SystemExit("DISCORD_TASKS_BOT_TOKEN (or fallback bot token) is empty")
    if not channel_id:
        raise SystemExit("DISCORD_TASK_CHANNEL_ID is empty")
    return token, channel_id


def api_get_messages(token: str, channel_id: str, limit: int) -> list[dict]:
    q = urllib.parse.urlencode({"limit": max(1, min(limit, 100))})
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages?{q}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bot {token}", "User-Agent": "aios-tasks-bot/1.0"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def api_post_reply(token: str, channel_id: str, parent_message_id: str, content: str) -> None:
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    body = json.dumps(
        {
            "content": content,
            "message_reference": {"message_id": parent_message_id, "channel_id": channel_id},
            "allowed_mentions": {"parse": []},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "aios-tasks-bot/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=20):
        return


def api_post_message(token: str, channel_id: str, content: str) -> None:
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    body = json.dumps({"content": content, "allowed_mentions": {"parse": []}}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "aios-tasks-bot/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=20):
        return


def already_processed(conn: sqlite3.Connection, message_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM discord_task_events WHERE message_id=?", (message_id,)).fetchone()
    return bool(row)


def mark_processing(
    conn: sqlite3.Connection,
    *,
    message_id: str,
    channel_id: str,
    author_id: str,
    raw_content: str,
    command_name: str,
    command_args: dict,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO discord_task_events(
          message_id, channel_id, author_id, raw_content, command_name, command_args_json, status, result_json, processed_at
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            message_id,
            channel_id,
            author_id,
            raw_content,
            command_name,
            json.dumps(command_args, ensure_ascii=False),
            "processing",
            json.dumps({}, ensure_ascii=False),
            now_iso(),
        ),
    )


def finalize_event(
    conn: sqlite3.Connection,
    *,
    message_id: str,
    status: str,
    result: dict,
) -> None:
    conn.execute(
        """
        UPDATE discord_task_events
        SET status=?, result_json=?, processed_at=?
        WHERE message_id=?
        """,
        (
            status,
            json.dumps(result, ensure_ascii=False),
            now_iso(),
            message_id,
        ),
    )


def parse_command(content: str) -> tuple[str, dict] | tuple[None, dict]:
    txt = (content or "").strip()
    if not txt:
        return None, {"error": "empty"}
    txt_norm = txt.replace("　", " ").strip()
    # Japanese shortcuts
    if txt_norm in {"ヘルプ", "使い方", "コマンド一覧"}:
        return "help", {}
    if txt_norm.startswith("メモ一覧"):
        toks = txt_norm.split()
        topic = toks[1] if len(toks) >= 2 else "general"
        limit = int(toks[2]) if len(toks) >= 3 and toks[2].isdigit() else 5
        return "memory_list", {"topic": topic, "limit": max(1, min(limit, 20))}
    if txt_norm.startswith("メモ:") or txt_norm.startswith("メモ："):
        body = txt_norm.split(":", 1)[1] if ":" in txt_norm else txt_norm.split("：", 1)[1]
        body = body.strip()
        topic = "general"
        mtype = "note"
        # 形式: メモ: topic=ops type=decision 本文...
        toks = body.split()
        content_start = 0
        for i, t in enumerate(toks[:3]):
            if t.startswith("topic="):
                topic = t.split("=", 1)[1] or "general"
                content_start = i + 1
            elif t.startswith("type="):
                mtype = t.split("=", 1)[1] or "note"
                content_start = i + 1
        memo_text = " ".join(toks[content_start:]).strip() if toks else body
        if not memo_text:
            return None, {"error": "empty_memory", "raw": txt}
        return "memory_add", {"topic": topic, "memory_type": mtype, "content": memo_text}
    if txt_norm.startswith("母数強化"):
        d = datetime.now().strftime("%Y-%m-%d")
        return "run_weekly_samples365", {"date": d}
    if txt_norm.startswith("週次30再収集"):
        return "run_weekly_recent30", {}
    if txt_norm.startswith("週次365再収集"):
        return "run_weekly_samples365", {}
    if txt_norm.startswith("月次ローテA"):
        return "run_monthly_rot_a", {}
    if txt_norm.startswith("月次ローテB"):
        return "run_monthly_rot_b", {}
    if txt_norm.startswith("月次ローテC"):
        return "run_monthly_rot_c", {}
    if txt_norm.startswith("outcomes補完") or txt_norm.startswith("アウトカム補完"):
        toks = txt_norm.split()
        d = toks[1] if len(toks) >= 2 else datetime.now().strftime("%Y-%m-%d")
        return "fill_outcomes_full", {"date": d}
    if txt_norm.startswith("エラー詳細"):
        toks = txt_norm.split(maxsplit=1)
        task = toks[1].strip() if len(toks) >= 2 else ""
        return "error_detail", {"task": task}
    if txt_norm in {"投資補完"}:
        return "keyword_action", {"keyword": txt_norm, "date": datetime.now().strftime("%Y-%m-%d")}
    if txt_norm.startswith("状態"):
        toks = txt_norm.split()
        d = toks[1] if len(toks) >= 2 else datetime.now().strftime("%Y-%m-%d")
        return "status", {"date": d}
    if txt_norm.startswith("投資情報収集"):
        toks = txt_norm.split()
        d = toks[1] if len(toks) >= 2 else datetime.now().strftime("%Y-%m-%d")
        return "collect_harvest", {"date": d}
    if txt_norm.startswith("昼の投資情報"):
        toks = txt_norm.split()
        d = toks[1] if len(toks) >= 2 else datetime.now().strftime("%Y-%m-%d")
        return "run_slot", {"slot": "inv-noon", "date": d}
    if txt_norm.startswith("夕の投資情報"):
        toks = txt_norm.split()
        d = toks[1] if len(toks) >= 2 else datetime.now().strftime("%Y-%m-%d")
        return "run_slot", {"slot": "inv-evening", "date": d}
    if txt_norm.startswith("シナリオ"):
        toks = txt_norm.split()
        d = toks[1] if len(toks) >= 2 else datetime.now().strftime("%Y-%m-%d")
        return "run_slot", {"slot": "inv-scenario", "date": d}
    if txt_norm.startswith("収集 実行") or txt_norm.startswith("収集実行"):
        toks = txt_norm.split()
        d = toks[-1] if len(toks) >= 3 else datetime.now().strftime("%Y-%m-%d")
        return "collect_harvest", {"date": d}
    if txt_norm.startswith("スロット 実行") or txt_norm.startswith("スロット実行"):
        toks = txt_norm.split()
        # expected: スロット 実行 inv-noon 2026-05-23
        if len(toks) >= 3:
            slot = toks[2]
            d = toks[3] if len(toks) >= 4 else datetime.now().strftime("%Y-%m-%d")
            if slot not in {"night", "inv-morning", "inv-noon", "inv-evening", "inv-scenario"}:
                return None, {"error": "invalid_slot", "raw": txt}
            return "run_slot", {"slot": slot, "date": d}
        return None, {"error": "invalid_slot", "raw": txt}

    parts = shlex.split(txt)
    if not parts:
        return None, {"error": "empty"}

    cmd0 = parts[0].lower()
    if cmd0 in {"help", "?"}:
        return "help", {}
    if cmd0 == "status":
        d = parts[1] if len(parts) >= 2 else datetime.now().strftime("%Y-%m-%d")
        return "status", {"date": d}
    if cmd0 == "error" and len(parts) >= 2 and parts[1].lower() == "detail":
        task = parts[2] if len(parts) >= 3 else ""
        return "error_detail", {"task": task}
    if cmd0 == "keyword" and len(parts) >= 2:
        kw = parts[1]
        d = parts[2] if len(parts) >= 3 else datetime.now().strftime("%Y-%m-%d")
        if kw != "投資補完":
            return None, {"error": "unsupported_keyword", "raw": txt}
        return "keyword_action", {"keyword": kw, "date": d}
    if cmd0 == "run" and len(parts) >= 3 and parts[1].lower() == "slot":
        slot = parts[2]
        d = parts[3] if len(parts) >= 4 else datetime.now().strftime("%Y-%m-%d")
        if slot not in {"night", "inv-morning", "inv-noon", "inv-evening", "inv-scenario"}:
            return None, {"error": "invalid_slot", "raw": txt}
        return "run_slot", {"slot": slot, "date": d}
    if cmd0 == "collect" and len(parts) >= 2 and parts[1].lower() == "harvest":
        d = parts[2] if len(parts) >= 3 else datetime.now().strftime("%Y-%m-%d")
        return "collect_harvest", {"date": d}
    if cmd0 == "outcomes" and len(parts) >= 2 and parts[1].lower() == "full":
        d = parts[2] if len(parts) >= 3 else datetime.now().strftime("%Y-%m-%d")
        return "fill_outcomes_full", {"date": d}
    # Fallback: treat free comment as memory note instead of format error.
    free = txt_norm.strip()
    if free:
        return "memory_add", {"topic": "general", "memory_type": "note", "content": free}
    return None, {"error": "unknown_command", "raw": txt}


def build_exec(cmd: str, payload: dict) -> list[str] | None:
    py = os.getenv("PYTHON", "python")
    if cmd == "run_slot":
        return [py, "scripts/run_ops_scheduler.py", "--slot", str(payload["slot"]), "--date", str(payload["date"])]
    if cmd == "collect_harvest":
        return [py, "scripts/investment/collect/run_harvest_backfill.py", "--date", str(payload["date"])]
    if cmd == "status":
        return [py, "scripts/notify/render_ops_kpi_summary_discord_message.py", "--date", str(payload["date"])]
    if cmd == "keyword_action":
        return [py, "scripts/ops/keyword_action.py", str(payload["keyword"]), "--date", str(payload["date"])]
    if cmd == "run_weekly_recent30":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts/ops/run_harvest_weekly_recent30.ps1"]
    if cmd == "run_weekly_samples365":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts/ops/run_harvest_weekly_samples365.ps1"]
    if cmd == "run_monthly_rot_a":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts/ops/run_harvest_monthly_rot_a.ps1"]
    if cmd == "run_monthly_rot_b":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts/ops/run_harvest_monthly_rot_b.ps1"]
    if cmd == "run_monthly_rot_c":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts/ops/run_harvest_monthly_rot_c.ps1"]
    if cmd == "fill_outcomes_full":
        return [py, "scripts/investment/backtest/fill_market_outcomes.py", "--date", str(payload["date"]), "--seed-list", "rough_backtest_full"]
    return None


def memory_add(
    db: Path,
    *,
    topic: str,
    memory_type: str,
    content: str,
    channel_id: str,
    message_id: str,
    author_id: str,
) -> int:
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_memory_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              memory_date TEXT NOT NULL,
              topic TEXT NOT NULL,
              memory_type TEXT NOT NULL,
              content TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'active',
              source_channel_id TEXT,
              source_message_id TEXT,
              source_author_id TEXT,
              payload_json TEXT,
              updated_at TEXT NOT NULL
            )
            """
        )
        row = conn.execute(
            """
            SELECT id
            FROM agent_memory_events
            WHERE source_channel_id=? AND source_message_id=?
            ORDER BY id
            LIMIT 1
            """,
            (channel_id, message_id),
        ).fetchone()
        if row:
            return int(row[0])
        now = now_iso()
        md = datetime.now().strftime("%Y-%m-%d")
        cur = conn.execute(
            """
            INSERT INTO agent_memory_events(
              memory_date,topic,memory_type,content,status,source_channel_id,source_message_id,source_author_id,payload_json,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                md,
                topic,
                memory_type,
                content,
                "active",
                channel_id,
                message_id,
                author_id,
                json.dumps({"ingest": "discord_task_channel"}, ensure_ascii=False),
                now,
            ),
        )
        conn.commit()
        return int(cur.lastrowid or 0)
    finally:
        conn.close()


def memory_list(db: Path, topic: str, limit: int) -> list[tuple]:
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            """
            WITH picked AS (
              SELECT MIN(id) AS id
              FROM agent_memory_events
              WHERE topic=? AND status='active'
              GROUP BY CASE
                WHEN COALESCE(source_message_id,'')<>'' THEN COALESCE(source_channel_id,'') || ':' || source_message_id
                ELSE 'row:' || CAST(id AS TEXT)
              END
            )
            SELECT e.id,e.memory_date,e.memory_type,e.content,e.updated_at
            FROM agent_memory_events e
            JOIN picked p ON p.id = e.id
            ORDER BY e.id DESC
            LIMIT ?
            """,
            (topic, limit),
        ).fetchall()
        return rows
    finally:
        conn.close()


def load_scheduler_health_detail(task: str) -> str:
    p = ROOT / "prompts" / "scheduler-health.json"
    if not p.exists():
        return "処理: エラー詳細 取得失敗（scheduler-health.json なし）"
    try:
        j = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return "処理: エラー詳細 取得失敗（JSON解析失敗）"
    status = str(j.get("status") or "unknown")
    alerts = j.get("alerts") or []
    tasks = (j.get("tasks") or {})
    if task:
        t = tasks.get(task) or {}
        if not t:
            return f"処理: エラー詳細 {task} 見つからず"
        return (
            f"処理: エラー詳細 {task}\n"
            f"status={status} start={int(t.get('start_count',0))} ok={int(t.get('ok_count',0))} error={int(t.get('error_count',0))}\n"
            f"last={str(t.get('last_event',''))[:900]}"
        )
    if not alerts:
        return f"処理: エラー詳細 status={status} alerts=なし"
    lines = [f"処理: エラー詳細 status={status}"]
    for a in alerts[:6]:
        lines.append(f"- {a}")
    return "\n".join(lines)


def run_exec(argv: list[str], timeout_sec: int) -> dict:
    p = subprocess.run(
        argv,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(30, timeout_sec),
    )
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    return {
        "argv": argv,
        "exit_code": int(p.returncode),
        "stdout_tail": "\n".join(out.splitlines()[-12:]),
        "stderr_tail": "\n".join(err.splitlines()[-12:]),
    }


def help_text() -> str:
    return (
        "tasks command help\n"
        "使い方:\n"
        "- ヘルプ / 使い方 / コマンド一覧\n"
        "- メモ: [topic=xxx] [type=note|decision|todo] 本文\n"
        "- メモ一覧 [topic] [件数]\n"
        "- エラー詳細（タスク名不要）\n"
        "- 投資補完\n"
        "- 母数強化 / 週次30再収集 / 週次365再収集 / 月次ローテA|B|C\n"
        "- outcomes補完 [YYYY-MM-DD]\n"
        "- 投資情報収集 [YYYY-MM-DD]\n"
        "- 昼の投資情報 [YYYY-MM-DD]\n"
        "- 夕の投資情報 [YYYY-MM-DD]\n"
        "- シナリオ [YYYY-MM-DD]\n"
        "- 状態 [YYYY-MM-DD]\n"
        "- スロット 実行 night|inv-morning|inv-noon|inv-evening|inv-scenario [YYYY-MM-DD]\n"
        "- 収集 実行 [YYYY-MM-DD]\n"
        "（英語互換）help / status / run slot ... / collect harvest ... / error detail"
    )


def main() -> int:
    args = parse_args()
    load_dotenv()
    token, channel_id = load_env()
    messages = api_get_messages(token, channel_id, args.limit)
    task_db = Path(args.task_db)
    memory_db = Path(args.memory_db)
    task_db.parent.mkdir(parents=True, exist_ok=True)
    memory_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(task_db)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS discord_task_events (
          message_id TEXT PRIMARY KEY,
          channel_id TEXT NOT NULL,
          author_id TEXT NOT NULL,
          raw_content TEXT NOT NULL,
          command_name TEXT,
          command_args_json TEXT,
          status TEXT NOT NULL,
          result_json TEXT,
          processed_at TEXT NOT NULL
        )
        """
    )
    handled = 0
    saved = 0
    executed = 0
    invalid = 0
    helped = 0
    try:
        for m in messages:
            mid = str(m.get("id", ""))
            if not mid:
                continue
            author = m.get("author") or {}
            if bool(author.get("bot")):
                continue
            if already_processed(conn, mid):
                continue
            content = str(m.get("content", "") or "")
            cmd, payload = parse_command(content)
            result = {}
            status = "ignored"
            mark_processing(
                conn,
                message_id=mid,
                channel_id=channel_id,
                author_id=str(author.get("id", "")),
                raw_content=content,
                command_name=str(cmd or ""),
                command_args=payload,
            )
            conn.commit()
            try:
                if cmd == "help":
                    status = "help"
                    helped += 1
                    if not args.dry_run:
                        api_post_reply(token, channel_id, mid, "処理: helpを返答")
                        api_post_reply(token, channel_id, mid, help_text())
                elif cmd == "status":
                    status = "executed"
                    executed += 1
                    exec_argv = build_exec(cmd, payload)
                    if exec_argv:
                        result = run_exec(exec_argv, args.exec_timeout_sec) if not args.dry_run else {"argv": exec_argv, "exit_code": 0}
                    if not args.dry_run:
                        rc = int(result.get("exit_code", 1))
                        api_post_reply(token, channel_id, mid, f"処理: status実行 rc={rc}")
                elif cmd == "error_detail":
                    status = "executed"
                    executed += 1
                    if not args.dry_run:
                        detail = load_scheduler_health_detail(str(payload.get("task") or "").strip())
                        api_post_reply(token, channel_id, mid, detail[:1800])
                elif cmd == "memory_add":
                    status = "executed"
                    executed += 1
                    rid = memory_add(
                        memory_db,
                        topic=str(payload.get("topic") or "general"),
                        memory_type=str(payload.get("memory_type") or "note"),
                        content=str(payload.get("content") or ""),
                        channel_id=channel_id,
                        message_id=mid,
                        author_id=str(author.get("id", "")),
                    )
                    result = {"memory_id": rid, **payload}
                    if not args.dry_run:
                        api_post_reply(token, channel_id, mid, f"処理: メモ保存 id={rid} topic={payload.get('topic','general')}")
                elif cmd == "memory_list":
                    status = "executed"
                    executed += 1
                    rows = memory_list(memory_db, str(payload.get("topic") or "general"), int(payload.get("limit") or 5))
                    result = {"rows": len(rows), **payload}
                    if not args.dry_run:
                        if not rows:
                            api_post_reply(token, channel_id, mid, "処理: メモ一覧 0件")
                        else:
                            lines = [f"処理: メモ一覧 topic={payload.get('topic')} 件数={len(rows)}"]
                            for r in rows:
                                lines.append(f"- #{r[0]} {r[1]} [{r[2]}] {str(r[3])[:80]}")
                            api_post_reply(token, channel_id, mid, "\n".join(lines)[:1800])
                elif cmd == "keyword_action":
                    status = "executed"
                    executed += 1
                    exec_argv = build_exec(cmd, payload)
                    if exec_argv:
                        result = run_exec(exec_argv, args.exec_timeout_sec) if not args.dry_run else {"argv": exec_argv, "exit_code": 0}
                    if not args.dry_run:
                        rc = int(result.get("exit_code", 1))
                        kw = str(payload.get("keyword") or "")
                        api_post_reply(token, channel_id, mid, f"処理: {kw} 実行 rc={rc}")
                elif cmd in {
                    "run_slot",
                    "collect_harvest",
                    "run_weekly_recent30",
                    "run_weekly_samples365",
                    "run_monthly_rot_a",
                    "run_monthly_rot_b",
                    "run_monthly_rot_c",
                    "fill_outcomes_full",
                }:
                    status = "executed"
                    executed += 1
                    exec_argv = build_exec(cmd, payload)
                    if exec_argv:
                        result = run_exec(exec_argv, args.exec_timeout_sec) if not args.dry_run else {"argv": exec_argv, "exit_code": 0}
                    if not args.dry_run:
                        rc = int(result.get("exit_code", 1))
                        api_post_reply(token, channel_id, mid, f"処理: {cmd} 実行 rc={rc}")
                else:
                    status = "invalid"
                    invalid += 1
                    result = payload
                    if not args.dry_run:
                        api_post_reply(token, channel_id, mid, "処理: 形式エラー（help参照）")
            except Exception as exc:
                status = "error"
                result = {"error": f"{type(exc).__name__}: {exc}", **payload}
            finalize_event(conn, message_id=mid, status=status, result=result)
            handled += 1
            saved += 1
        conn.commit()
    finally:
        conn.close()
    if args.post_run_summary and not args.dry_run and handled > 0:
        summary = f"処理: poll完了 handled={handled} executed={executed} invalid={invalid}"
        try:
            api_post_message(token, channel_id, summary)
        except Exception:
            # fallback: ignore summary failures
            pass
    print(f"handled={handled} dry_run={args.dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
