#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.platform_core_bootstrap import ensure_platform_core_importable

ensure_platform_core_importable()
from platform_core.model_router import resolve_model

DEFAULT_OPS_DB = ROOT / "data" / "ops.db"
DEFAULT_CONTEXT_CHARS = 12000


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Execute improvement work items with Codex CLI")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_OPS_DB)
    p.add_argument("--limit", type=int, default=1)
    p.add_argument("--work-id", type=int, default=0)
    p.add_argument(
        "--model-route",
        default="improvement_execution_engine",
        help="Model routing key used to choose the default Codex CLI model.",
    )
    p.add_argument("--model", default="", help="Optional explicit model override for codex exec.")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--context-chars", type=int, default=DEFAULT_CONTEXT_CHARS)
    return p.parse_args()


def load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, value = s.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_items(conn: sqlite3.Connection, date_s: str, limit: int, work_id: int) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    if work_id > 0:
        row = conn.execute("SELECT * FROM improvement_work_items WHERE id=?", (work_id,)).fetchone()
        return [dict(row)] if row else []
    rows = conn.execute(
        """
        SELECT *
        FROM improvement_work_items
        WHERE candidate_date <= ?
          AND work_status IN ('doing', 'open')
        ORDER BY CASE work_status WHEN 'doing' THEN 0 ELSE 1 END, work_priority DESC, id ASC
        LIMIT ?
        """,
        (date_s, int(limit)),
    ).fetchall()
    return [dict(r) for r in rows]


def parse_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(value)
        except Exception:
            return default
    return default


def resolve_target_files(patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    seen: set[str] = set()
    for raw in patterns:
        pat = str(raw).strip()
        if not pat:
            continue
        if any(ch in pat for ch in "*?[]"):
            for path in sorted(ROOT.glob(pat)):
                if path.is_file():
                    rel = path.relative_to(ROOT)
                    key = str(rel)
                    if key not in seen:
                        seen.add(key)
                        files.append(path)
        else:
            path = ROOT / pat
            if path.is_dir():
                for child in sorted(path.rglob("*")):
                    if child.is_file():
                        rel = child.relative_to(ROOT)
                        key = str(rel)
                        if key not in seen:
                            seen.add(key)
                            files.append(child)
            elif path.is_file():
                rel = path.relative_to(ROOT)
                key = str(rel)
                if key not in seen:
                    seen.add(key)
                    files.append(path)
    return files


def read_context_file(path: Path, max_chars: int) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {
            "path": str(path.relative_to(ROOT)),
            "error": f"{type(exc).__name__}: {exc}",
        }
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated]...\n"
    return {
        "path": str(path.relative_to(ROOT)),
        "size": len(text),
        "content": text,
    }


def build_context(item: dict[str, Any], max_chars: int) -> dict[str, Any]:
    work = parse_json(item.get("work_body_json"), {})
    proposal = parse_json(work.get("proposal"), {})
    work_section = parse_json(work.get("work"), {})
    target_patterns = parse_json(work_section.get("target_files"), [])
    if not isinstance(target_patterns, list):
        target_patterns = []
    target_files = resolve_target_files([str(x) for x in target_patterns])
    context_files = [read_context_file(p, max_chars) for p in target_files[:8]]
    git_status = subprocess.run(
        ["git", "status", "--short"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    git_diff_stat = subprocess.run(
        ["git", "diff", "--stat"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return {
        "proposal": proposal,
        "work": work_section,
        "target_patterns": [str(x) for x in target_patterns],
        "resolved_target_files": [str(p.relative_to(ROOT)) for p in target_files],
        "context_files": context_files,
        "git_status": git_status,
        "git_diff_stat": git_diff_stat,
    }


def build_prompt(item: dict[str, Any], context: dict[str, Any]) -> str:
    payload = {
        "work_item": {
            "id": item.get("id"),
            "proposal_id": item.get("proposal_id"),
            "candidate_date": item.get("candidate_date"),
            "source_key": item.get("source_key"),
            "repository_full_name": item.get("repository_full_name"),
            "work_title": item.get("work_title"),
            "work_status": item.get("work_status"),
            "work_priority": item.get("work_priority"),
            "work_plan_json": parse_json(item.get("work_plan_json"), {}),
            "target_files_json": parse_json(item.get("target_files_json"), []),
            "validation_commands_json": parse_json(item.get("validation_commands_json"), []),
            "review_status": item.get("review_status"),
        },
        "context": context,
    }
    return (
        "あなたはこのリポジトリの実装担当です。"
        "Codex CLI として、このワークツリー上のファイルを直接改修してください。\n"
        "DBにある work item を読み、必要最小限の変更を実施してください。"
        "変更できない場合は blocked を返してください。\n"
        "出力は JSON だけにしてください。JSON 形式:\n"
        "{\n"
        '  "status": "done" | "blocked",\n'
        '  "summary": "短い要約",\n'
        '  "validation_commands": ["cmd1", "cmd2"],\n'
        '  "blocked_reason": "必要時のみ",\n'
        '  "notes": "任意"\n'
        "}\n"
        "ルール:\n"
        "- 変更は resolved_target_files とその周辺の必要最小限に限る\n"
        "- 不明な場合は blocked を返す\n"
        "- 余計な説明文や markdown は返さない\n"
        "- 既存の意味を壊さず、最小変更にする\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def codex_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["done", "blocked"]},
            "summary": {"type": "string"},
            "validation_commands": {
                "type": "array",
                "items": {"type": "string"},
            },
            "blocked_reason": {"type": "string"},
            "notes": {"type": "string"},
        },
        "required": ["status", "summary", "validation_commands", "blocked_reason", "notes"],
        "additionalProperties": False,
    }


def run_codex_exec(prompt: str, model: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="codex-exec-") as tmpdir:
        tmp = Path(tmpdir)
        schema_path = tmp / "output-schema.json"
        message_path = tmp / "last-message.json"
        schema_path.write_text(json.dumps(codex_output_schema(), ensure_ascii=False, indent=2), encoding="utf-8")

        cmd = [
            "codex",
            "exec",
            "--cd",
            str(ROOT),
            "--sandbox",
            "workspace-write",
            "--ephemeral",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(message_path),
        ]
        if model.strip():
            cmd.extend(["--model", model.strip()])
        cmd.append("-")

        proc = subprocess.run(
            cmd,
            input=prompt,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        final_message = ""
        if message_path.exists():
            final_message = message_path.read_text(encoding="utf-8", errors="replace").strip()

        return {
            "command": cmd,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-8000:],
            "stderr": proc.stderr[-8000:],
            "final_message": final_message,
        }


def run_validation_commands(commands: list[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for cmd in commands:
        if not cmd or not str(cmd).strip():
            continue
        parts = shlex.split(str(cmd))
        if not parts:
            continue
        proc = subprocess.run(
            parts,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        results.append(
            {
                "command": cmd,
                "returncode": proc.returncode,
                "stdout": proc.stdout[-4000:],
                "stderr": proc.stderr[-4000:],
            }
        )
        if proc.returncode != 0:
            break
    return results


def git_changed_files() -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def git_diff_summary() -> dict[str, Any]:
    proc = subprocess.run(
        ["git", "diff", "--stat"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "returncode": proc.returncode,
        "stat": proc.stdout.strip(),
        "error": proc.stderr.strip(),
    }


def update_work_item(
    conn: sqlite3.Connection,
    *,
    work_id: int,
    fields: dict[str, Any],
) -> None:
    parts: list[str] = []
    values: list[Any] = []
    for key, value in fields.items():
        parts.append(f"{key}=?")
        values.append(value)
    parts.append("updated_at=?")
    values.append(now_iso())
    values.append(work_id)
    sql = f"UPDATE improvement_work_items SET {', '.join(parts)} WHERE id=?"
    conn.execute(sql, values)


def main() -> int:
    args = parse_args()
    load_dotenv()
    _provider, route_model = resolve_model(args.model_route)
    model = args.model.strip() or route_model

    conn = sqlite3.connect(args.db)
    try:
        items = load_items(conn, args.date, args.limit, args.work_id)
        if not items:
            print("skip: no work items")
            return 0

        processed = 0
        for item in items:
            context = build_context(item, args.context_chars)
            prompt = build_prompt(item, context)
            now_s = now_iso()
            attempt_count = int(item.get("attempt_count") or 0) + 1
            update_work_item(
                conn,
                work_id=int(item["id"]),
                fields={
                    "attempt_count": attempt_count,
                    "last_attempt_at": now_s,
                    "work_status": "doing",
                },
            )
            conn.commit()

            if args.dry_run:
                result: dict[str, Any] = {
                    "status": "blocked",
                    "summary": "dry-run",
                    "validation_commands": [],
                    "blocked_reason": "dry_run enabled",
                    "notes": "",
                    "codex_run": {"command": [], "returncode": 0, "stdout": "", "stderr": ""},
                }
                raw_text = json.dumps(result, ensure_ascii=False)
            else:
                codex_run = run_codex_exec(prompt, model)
                raw_text = codex_run["final_message"]
                try:
                    result = json.loads(raw_text) if raw_text else {}
                except Exception:
                    result = {}
                if not isinstance(result, dict) or not result:
                    result = {
                        "status": "blocked",
                        "summary": "codex output parse failed",
                        "validation_commands": [],
                        "blocked_reason": "codex output could not be parsed as JSON",
                        "notes": (raw_text or codex_run["stderr"] or codex_run["stdout"])[:4000],
                    }
                if codex_run["returncode"] != 0 and str(result.get("status") or "").strip() != "done":
                    result["status"] = "blocked"
                    if not str(result.get("blocked_reason") or "").strip():
                        result["blocked_reason"] = (
                            codex_run["stderr"].strip()
                            or codex_run["stdout"].strip()
                            or f"codex exec failed with exit code {codex_run['returncode']}"
                        )
                result["codex_run"] = {
                    "command": codex_run["command"],
                    "returncode": codex_run["returncode"],
                    "stdout": codex_run["stdout"],
                    "stderr": codex_run["stderr"],
                }
                raw_text = raw_text or ""

            status = str(result.get("status") or "blocked")
            blocked_reason = str(result.get("blocked_reason") or "").strip()

            validation_commands = result.get("validation_commands")
            if not isinstance(validation_commands, list):
                validation_commands = []
            if not validation_commands:
                validation_commands = parse_json(item.get("validation_commands_json"), [])
            if not isinstance(validation_commands, list):
                validation_commands = []

            validation_results: list[dict[str, Any]] = []
            if status != "blocked" and validation_commands:
                validation_results = run_validation_commands([str(x) for x in validation_commands])
                failed = next((r for r in validation_results if int(r.get("returncode") or 0) != 0), None)
                if failed:
                    status = "blocked"
                    blocked_reason = f"validation failed: {failed['command']}"

            changed_files = git_changed_files() if status != "blocked" else []
            diff_summary = git_diff_summary() if status != "blocked" else {}
            final_status = "done" if status == "done" else "blocked"

            execution_result = {
                "tool": "codex exec",
                "model": model,
                "model_route": args.model_route,
                "status": result.get("status", status),
                "summary": result.get("summary", ""),
                "context": {
                    "target_patterns": context["target_patterns"],
                    "resolved_target_files": context["resolved_target_files"],
                    "git_status": context["git_status"],
                    "git_diff_stat": context["git_diff_stat"],
                },
                "codex_run": result.get("codex_run", {}),
                "final_message": raw_text[:20000],
            }
            validation_result = {
                "commands": validation_commands,
                "results": validation_results,
            }

            update_fields: dict[str, Any] = {
                "execution_commands_json": json.dumps(
                    [" ".join(result.get("codex_run", {}).get("command", ["codex", "exec"]))] if not args.dry_run else ["dry-run"],
                    ensure_ascii=False,
                ),
                "validation_commands_json": json.dumps(validation_commands, ensure_ascii=False),
                "execution_result_json": json.dumps(execution_result, ensure_ascii=False),
                "validation_result_json": json.dumps(validation_result, ensure_ascii=False),
                "changed_files_json": json.dumps(changed_files, ensure_ascii=False),
                "diff_summary_json": json.dumps(diff_summary, ensure_ascii=False),
                "work_status": final_status,
                "review_status": "ready" if final_status == "done" else "pending",
                "blocked_reason": blocked_reason or None,
                "error_message": blocked_reason or None,
            }
            if final_status == "done":
                update_fields["completed_at"] = now_iso()
            update_work_item(conn, work_id=int(item["id"]), fields=update_fields)
            conn.commit()
            processed += 1

        print(f"executed: improvement_work_items {processed} rows")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
