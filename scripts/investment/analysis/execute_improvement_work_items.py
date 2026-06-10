#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.platform_core_bootstrap import ensure_platform_core_importable
from utils.env_loader import load_env_files

ensure_platform_core_importable()
from platform_core.model_router import resolve_model

DEFAULT_OPS_DB = ROOT / "data" / "ops.db"
DEFAULT_CONTEXT_CHARS = 12000
WORKTREE_BASE = ROOT.parent / ".codex-worktrees"
GITHUB_API_BASE = "https://api.github.com"
MAX_IMPROVEMENT_ROUNDS = 2
AUDIT_LOG_DDL = """
CREATE TABLE IF NOT EXISTS improvement_audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  work_item_id INTEGER NOT NULL,
  proposal_id INTEGER NOT NULL,
  candidate_date TEXT NOT NULL,
  source_key TEXT NOT NULL,
  attempt_no INTEGER NOT NULL DEFAULT 0,
  stage TEXT NOT NULL,
  round_no INTEGER NOT NULL DEFAULT 0,
  event_type TEXT NOT NULL DEFAULT 'stage',
  status TEXT,
  summary TEXT,
  blocked_reason TEXT,
  input_json TEXT NOT NULL DEFAULT '{}',
  output_json TEXT NOT NULL DEFAULT '{}',
  validation_json TEXT NOT NULL DEFAULT '{}',
  review_json TEXT NOT NULL DEFAULT '{}',
  branch_name TEXT,
  commit_sha TEXT,
  pr_url TEXT,
  created_at TEXT NOT NULL
)
"""


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
    load_env_files(ROOT / ".env.local", ROOT / ".env")


def get_github_token() -> str:
    return (
        os.getenv("GITHUB_TOKEN", "").strip()
        or os.getenv("GH_TOKEN", "").strip()
    )


def slugify_branch_component(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:48] or "item"


def make_branch_name(item: dict[str, Any]) -> str:
    item_id = int(item["id"])
    source_key = slugify_branch_component(str(item.get("source_key") or "item"))
    return f"improvement/item-{item_id}-{source_key}"


def run_git(base_dir: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(base_dir), *args],
        cwd=base_dir,
        capture_output=True,
        text=True,
        check=check,
    )


def git_output(base_dir: Path, args: list[str]) -> str:
    proc = run_git(base_dir, args, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def create_worktree_branch(item: dict[str, Any], base_dir: Path, branch_name: str | None) -> Path:
    item_id = int(item["id"])
    source_key = str(item.get("source_key") or "item").replace("/", "-")
    worktree_root = base_dir / f"item-{item_id}-{source_key}"
    clean_worktree_dir(worktree_root)
    worktree_root.parent.mkdir(parents=True, exist_ok=True)
    if branch_name:
        subprocess.run(
            ["git", "-C", str(ROOT), "worktree", "add", "-B", branch_name, str(worktree_root), "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    else:
        subprocess.run(
            ["git", "-C", str(ROOT), "worktree", "add", "--detach", str(worktree_root), "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    return worktree_root


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


def extract_target_patterns(item: dict[str, Any]) -> list[str]:
    work = parse_json(item.get("work_body_json"), {})
    work_section = parse_json(work.get("work"), {})
    target_patterns = parse_json(work_section.get("target_files"), [])
    if not isinstance(target_patterns, list):
        return []
    return [str(x) for x in target_patterns if str(x).strip()]


def resolve_target_files(base_dir: Path, patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    seen: set[str] = set()
    for raw in patterns:
        pat = str(raw).strip()
        if not pat:
            continue
        if any(ch in pat for ch in "*?[]"):
            for path in sorted(base_dir.glob(pat)):
                if path.is_file():
                    rel = path.relative_to(base_dir)
                    key = str(rel)
                    if key not in seen:
                        seen.add(key)
                        files.append(path)
        else:
            path = base_dir / pat
            if path.is_dir():
                for child in sorted(path.rglob("*")):
                    if child.is_file():
                        rel = child.relative_to(base_dir)
                        key = str(rel)
                        if key not in seen:
                            seen.add(key)
                            files.append(child)
            elif path.is_file():
                rel = path.relative_to(base_dir)
                key = str(rel)
                if key not in seen:
                    seen.add(key)
                    files.append(path)
    return files


def read_context_file(base_dir: Path, path: Path, max_chars: int) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {
            "path": str(path.relative_to(base_dir)),
            "error": f"{type(exc).__name__}: {exc}",
        }
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated]...\n"
    return {
        "path": str(path.relative_to(base_dir)),
        "size": len(text),
        "content": text,
    }


def copy_selected_files(source_dir: Path, dest_dir: Path, files: list[Path]) -> None:
    for src in files:
        rel = src.relative_to(source_dir)
        dst = dest_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def clean_worktree_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def cleanup_worktree(worktree_root: Path) -> None:
    keep = os.getenv("KEEP_IMPROVEMENT_WORKTREE", "").strip().lower() in {"1", "true", "yes"}
    if keep:
        return
    subprocess.run(
        ["git", "-C", str(ROOT), "worktree", "remove", "--force", str(worktree_root)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    clean_worktree_dir(worktree_root)
    subprocess.run(
        ["git", "-C", str(ROOT), "worktree", "prune"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        if WORKTREE_BASE.exists() and not any(WORKTREE_BASE.iterdir()):
            WORKTREE_BASE.rmdir()
    except OSError:
        pass


def build_context(item: dict[str, Any], base_dir: Path, max_chars: int) -> dict[str, Any]:
    work = parse_json(item.get("work_body_json"), {})
    proposal = parse_json(work.get("proposal"), {})
    work_section = parse_json(work.get("work"), {})
    target_patterns = extract_target_patterns(item)
    target_files = resolve_target_files(base_dir, target_patterns)
    context_files = [read_context_file(base_dir, p, max_chars) for p in target_files[:8]]
    git_status = subprocess.run(
        ["git", "status", "--short"],
        cwd=base_dir,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    git_diff_stat = subprocess.run(
        ["git", "diff", "--stat"],
        cwd=base_dir,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return {
        "proposal": proposal,
        "work": work_section,
        "target_patterns": target_patterns,
        "resolved_target_files": [str(p.relative_to(base_dir)) for p in target_files],
        "context_files": context_files,
        "git_status": git_status,
        "git_diff_stat": git_diff_stat,
    }


def github_api_request(
    method: str,
    path: str,
    token: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "aios-improvement-executor/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{GITHUB_API_BASE}{path}", data=body, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else {}


def get_default_branch(repository_full_name: str, token: str) -> str:
    try:
        repo = github_api_request("GET", f"/repos/{repository_full_name}", token)
        branch = str(repo.get("default_branch") or "").strip()
        if branch:
            return branch
    except Exception:
        pass
    return "main"


def get_remote_push_url(repository_full_name: str, token: str) -> str:
    encoded = urllib.parse.quote(token, safe="")
    return f"https://x-access-token:{encoded}@github.com/{repository_full_name}.git"


def commit_changes(worktree_root: Path, message: str) -> str:
    run_git(worktree_root, ["add", "-A"])
    proc = run_git(worktree_root, ["commit", "-m", message], check=False)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "git commit failed").strip())
    sha = git_output(worktree_root, ["rev-parse", "HEAD"])
    if not sha:
        raise RuntimeError("git rev-parse HEAD failed")
    return sha


def commit_changed_files(worktree_root: Path, commit_sha: str) -> list[str]:
    proc = run_git(worktree_root, ["show", "--pretty=", "--name-only", commit_sha], check=False)
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def commit_diff_summary(worktree_root: Path, commit_sha: str) -> dict[str, Any]:
    proc = run_git(worktree_root, ["show", "--stat", "--format=", commit_sha], check=False)
    return {
        "returncode": proc.returncode,
        "stat": proc.stdout.strip(),
        "error": proc.stderr.strip(),
    }


def push_branch(worktree_root: Path, branch_name: str, repository_full_name: str, token: str) -> None:
    remote_url = get_remote_push_url(repository_full_name, token)
    proc = subprocess.run(
        ["git", "-C", str(worktree_root), "push", "-u", remote_url, f"HEAD:refs/heads/{branch_name}"],
        cwd=worktree_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "git push failed").strip())


def create_pull_request(
    repository_full_name: str,
    token: str,
    *,
    branch_name: str,
    base_branch: str,
    title: str,
    body: str,
) -> dict[str, Any]:
    payload = {
        "title": title,
        "head": branch_name,
        "base": base_branch,
        "body": body,
        "draft": True,
    }
    return github_api_request("POST", f"/repos/{repository_full_name}/pulls", token, payload)


def build_prompt(item: dict[str, Any], context: dict[str, Any]) -> str:
    return build_prompt_with_feedback(item, context, "")


def build_prompt_with_feedback(item: dict[str, Any], context: dict[str, Any], feedback: str) -> str:
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
        "feedback": feedback,
    }
    return (
        "あなたはこのリポジトリの実装担当です。"
        "Codex CLI として、このワークツリー上のファイルを直接改修してください。\n"
        "DBにある work item を読み、必要最小限の変更を実施してください。"
        "変更できない場合は blocked を返してください。\n"
        "前回の検証結果や自己レビューの指摘があれば、それを優先して反映してください。\n"
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


def codex_review_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["done", "revise", "blocked"]},
            "summary": {"type": "string"},
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {"type": "string"},
                        "message": {"type": "string"},
                        "file": {"type": "string"},
                    },
                    "required": ["severity", "message", "file"],
                    "additionalProperties": False,
                },
            },
            "blocked_reason": {"type": "string"},
            "notes": {"type": "string"},
        },
        "required": ["status", "summary", "findings", "blocked_reason", "notes"],
        "additionalProperties": False,
    }


def run_codex_exec(prompt: str, model: str, worktree_root: Path) -> dict[str, Any]:
    return run_codex_json_stage(prompt, model, worktree_root, codex_output_schema(), "codex-exec")


def run_codex_review(prompt: str, model: str, worktree_root: Path) -> dict[str, Any]:
    return run_codex_json_stage(prompt, model, worktree_root, codex_review_output_schema(), "codex-review")


def run_codex_json_stage(
    prompt: str,
    model: str,
    worktree_root: Path,
    output_schema: dict[str, Any],
    temp_prefix: str,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"{temp_prefix}-") as tmpdir:
        tmp = Path(tmpdir)
        schema_path = tmp / "output-schema.json"
        message_path = tmp / "last-message.json"
        schema_path.write_text(json.dumps(output_schema, ensure_ascii=False, indent=2), encoding="utf-8")

        cmd = [
            "codex",
            "exec",
            "--cd",
            str(worktree_root),
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
            cwd=worktree_root,
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


def parse_codex_json_result(raw_text: str, codex_run: dict[str, Any], *, stage: str) -> dict[str, Any]:
    try:
        result = json.loads(raw_text) if raw_text else {}
    except Exception:
        result = {}
    if not isinstance(result, dict) or not result:
        if stage == "review":
            result = {
                "status": "blocked",
                "summary": "codex review parse failed",
                "findings": [],
                "blocked_reason": "codex review output could not be parsed as JSON",
                "notes": (raw_text or codex_run.get("stderr") or codex_run.get("stdout") or "")[:4000],
            }
        else:
            result = {
                "status": "blocked",
                "summary": "codex output parse failed",
                "validation_commands": [],
                "blocked_reason": "codex output could not be parsed as JSON",
                "notes": (raw_text or codex_run.get("stderr") or codex_run.get("stdout") or "")[:4000],
            }
    if stage == "review" and not isinstance(result.get("findings"), list):
        result["findings"] = []
    if stage != "review" and not isinstance(result.get("validation_commands"), list):
        result["validation_commands"] = []
    if codex_run.get("returncode") != 0 and str(result.get("status") or "").strip() != "done":
        result["status"] = "blocked"
        if not str(result.get("blocked_reason") or "").strip():
            result["blocked_reason"] = (
                str(codex_run.get("stderr") or "").strip()
                or str(codex_run.get("stdout") or "").strip()
                or f"codex exec failed with exit code {codex_run.get('returncode')}"
            )
    result["codex_run"] = {
        "command": codex_run.get("command", []),
        "returncode": codex_run.get("returncode", 0),
        "stdout": codex_run.get("stdout", ""),
        "stderr": codex_run.get("stderr", ""),
    }
    return result


def summarize_validation_results(validation_results: list[dict[str, Any]]) -> str:
    if not validation_results:
        return "validation commands: none"
    lines: list[str] = []
    for row in validation_results:
        lines.append(f"`{row.get('command')}` => {int(row.get('returncode') or 0)}")
    return "\n".join(lines)


def build_review_prompt(
    item: dict[str, Any],
    context: dict[str, Any],
    execution_result: dict[str, Any],
    validation_result: dict[str, Any],
) -> str:
    payload = {
        "work_item": {
            "id": item.get("id"),
            "proposal_id": item.get("proposal_id"),
            "candidate_date": item.get("candidate_date"),
            "source_key": item.get("source_key"),
            "repository_full_name": item.get("repository_full_name"),
            "work_title": item.get("work_title"),
        },
        "context": context,
        "execution_result": execution_result,
        "validation_result": validation_result,
    }
    return (
        "あなたはこの変更の自己レビュー担当です。"
        "ワークツリー上の変更と検証結果を確認し、実装と契約のずれを洗い出してください。\n"
        "問題が残っているなら status=revise を返し、改善指示を短く具体化してください。"
        "致命的で先に進めないなら blocked を返してください。\n"
        "出力は JSON だけにしてください。JSON 形式:\n"
        "{\n"
        '  "status": "done" | "revise" | "blocked",\n'
        '  "summary": "短い要約",\n'
        '  "findings": [{"severity": "low|medium|high", "message": "...", "file": "..."}],\n'
        '  "blocked_reason": "必要時のみ",\n'
        '  "notes": "任意"\n'
        "}\n"
        "ルール:\n"
        "- 提案・契約・検証結果の食い違いを優先して見る\n"
        "- 変更が足りない場合は revise を返す\n"
        "- 余計な説明文や markdown は返さない\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def run_validation_commands(base_dir: Path, commands: list[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for cmd in commands:
        if not cmd or not str(cmd).strip():
            continue
        raw_cmd = str(cmd).strip()
        if os.name == "nt":
            proc = subprocess.run(
                raw_cmd,
                cwd=base_dir,
                capture_output=True,
                text=True,
                shell=True,
                check=False,
            )
        else:
            proc = subprocess.run(
                ["bash", "-lc", raw_cmd],
                cwd=base_dir,
                capture_output=True,
                text=True,
                check=False,
            )
        results.append(
            {
                "command": raw_cmd,
                "returncode": proc.returncode,
                "stdout": proc.stdout[-4000:],
                "stderr": proc.stderr[-4000:],
            }
        )
        if proc.returncode != 0:
            break
    return results


def git_changed_files(base_dir: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=base_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def git_diff_summary(base_dir: Path) -> dict[str, Any]:
    proc = subprocess.run(
        ["git", "diff", "--stat"],
        cwd=base_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "returncode": proc.returncode,
        "stat": proc.stdout.strip(),
        "error": proc.stderr.strip(),
    }


def sync_worktree_inputs(item: dict[str, Any], worktree_root: Path) -> dict[str, Any]:
    target_patterns = extract_target_patterns(item)
    target_files = resolve_target_files(ROOT, target_patterns)
    copy_selected_files(ROOT, worktree_root, target_files)
    context = build_context(item, worktree_root, DEFAULT_CONTEXT_CHARS)
    return context


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


def ensure_audit_log_schema(conn: sqlite3.Connection) -> None:
    conn.execute(AUDIT_LOG_DDL)
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_improvement_audit_log_work_item_stage
          ON improvement_audit_log(work_item_id, stage, round_no, id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_improvement_audit_log_created_at
          ON improvement_audit_log(created_at)
        """
    )


def ensure_work_item_audit_link_schema(conn: sqlite3.Connection) -> None:
    cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(improvement_work_items)").fetchall()}
    if "audit_log_ids_json" not in cols:
        conn.execute(
            "ALTER TABLE improvement_work_items ADD COLUMN audit_log_ids_json TEXT NOT NULL DEFAULT '[]'"
        )


def insert_audit_log(
    conn: sqlite3.Connection,
    *,
    item: dict[str, Any],
    attempt_no: int,
    stage: str,
    round_no: int,
    event_type: str,
    status: str | None,
    summary: str | None,
    blocked_reason: str | None,
    input_payload: dict[str, Any],
    output_payload: dict[str, Any],
    validation_payload: dict[str, Any],
    review_payload: dict[str, Any],
    branch_name: str = "",
    commit_sha: str = "",
    pr_url: str = "",
) -> int:
    cur = conn.execute(
        """
        INSERT INTO improvement_audit_log(
            work_item_id, proposal_id, candidate_date, source_key, attempt_no,
            stage, round_no, event_type, status, summary, blocked_reason,
            input_json, output_json, validation_json, review_json,
            branch_name, commit_sha, pr_url, created_at
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            int(item.get("id") or 0),
            int(item.get("proposal_id") or 0),
            str(item.get("candidate_date") or ""),
            str(item.get("source_key") or ""),
            int(attempt_no or 0),
            str(stage or ""),
            int(round_no or 0),
            str(event_type or "stage"),
            status,
            summary,
            blocked_reason,
            json.dumps(input_payload, ensure_ascii=False),
            json.dumps(output_payload, ensure_ascii=False),
            json.dumps(validation_payload, ensure_ascii=False),
            json.dumps(review_payload, ensure_ascii=False),
            branch_name or None,
            commit_sha or None,
            pr_url or None,
            now_iso(),
        ),
    )
    return int(cur.lastrowid or 0)


def main() -> int:
    args = parse_args()
    load_dotenv()
    _provider, route_model = resolve_model(args.model_route)
    model = args.model.strip() or route_model
    github_token = get_github_token()

    conn = sqlite3.connect(args.db)
    try:
        ensure_audit_log_schema(conn)
        ensure_work_item_audit_link_schema(conn)
        conn.commit()
        items = load_items(conn, args.date, args.limit, args.work_id)
        if not items:
            print("skip: no work items")
            return 0

        processed = 0
        for item in items:
            worktree_root: Path | None = None
            branch_name = ""
            commit_sha = ""
            pr_url = ""
            attempt_count = 0
            context: dict[str, Any] = {
                "target_patterns": [],
                "resolved_target_files": [],
                "git_status": "",
                "git_diff_stat": "",
            }
            result: dict[str, Any] = {}
            raw_text = ""
            status = "blocked"
            blocked_reason = ""
            validation_commands: list[str] = []
            validation_results: list[dict[str, Any]] = []
            review_result: dict[str, Any] = {}
            round_history: list[dict[str, Any]] = []
            audit_log_ids: list[int] = []
            try:
                if args.dry_run:
                    worktree_root = create_worktree_branch(item, WORKTREE_BASE, None)
                    context = sync_worktree_inputs(item, worktree_root)
                    result = {
                        "status": "blocked",
                        "summary": "dry-run",
                        "validation_commands": [],
                        "blocked_reason": "dry_run enabled",
                        "notes": "",
                        "codex_run": {"command": [], "returncode": 0, "stdout": "", "stderr": ""},
                    }
                    raw_text = json.dumps(result, ensure_ascii=False)
                else:
                    if not github_token:
                        update_work_item(
                            conn,
                            work_id=int(item["id"]),
                            fields={
                                "work_status": "blocked",
                                "review_status": "pending",
                                "blocked_reason": "GITHUB_TOKEN is empty",
                                "error_message": "GITHUB_TOKEN is empty",
                            },
                        )
                        conn.commit()
                        processed += 1
                        continue
                    now_s = now_iso()
                    attempt_count = int(item.get("attempt_count") or 0) + 1
                    branch_name = make_branch_name(item)
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
                    worktree_root = create_worktree_branch(item, WORKTREE_BASE, branch_name)
                    context = sync_worktree_inputs(item, worktree_root)
                    retry_feedback = ""
                    for round_no in range(1, MAX_IMPROVEMENT_ROUNDS + 1):
                        prompt = build_prompt_with_feedback(item, context, retry_feedback)
                        codex_run = run_codex_exec(prompt, model, worktree_root)
                        raw_text = codex_run["final_message"]
                        result = parse_codex_json_result(raw_text, codex_run, stage="exec")
                        validation_failed = False

                        validation_commands = result.get("validation_commands")
                        if not isinstance(validation_commands, list):
                            validation_commands = []
                        if not validation_commands:
                            validation_commands = parse_json(item.get("validation_commands_json"), [])
                        if not isinstance(validation_commands, list):
                            validation_commands = []

                        validation_results = []
                        if str(result.get("status") or "").strip() != "blocked" and validation_commands:
                            validation_results = run_validation_commands(worktree_root or ROOT, [str(x) for x in validation_commands])
                            failed = next((r for r in validation_results if int(r.get("returncode") or 0) != 0), None)
                            if failed:
                                validation_failed = True
                                result["status"] = "blocked"
                                blocked_reason = f"validation failed: {failed['command']}"
                                result["blocked_reason"] = blocked_reason
                                retry_feedback = (
                                    "前回の検証で失敗しました。"
                                    f"失敗コマンド: {failed['command']}. "
                                    f"stdout: {failed.get('stdout', '')[:1000]}. "
                                    f"stderr: {failed.get('stderr', '')[:1000]}."
                                )
                            else:
                                blocked_reason = ""
                        elif str(result.get("status") or "").strip() == "blocked":
                            blocked_reason = str(result.get("blocked_reason") or "").strip()

                        round_record: dict[str, Any] = {
                            "round": round_no,
                            "execution": {
                                "status": result.get("status", "blocked"),
                                "summary": result.get("summary", ""),
                                "codex_run": result.get("codex_run", {}),
                                "final_message": raw_text[:20000],
                            },
                            "validation": {
                                "commands": validation_commands,
                                "results": validation_results,
                            },
                        }

                        audit_log_ids.append(
                            insert_audit_log(
                                conn,
                                item=item,
                                attempt_no=attempt_count,
                                stage="execution",
                                round_no=round_no,
                                event_type="stage",
                                status=str(result.get("status") or "blocked"),
                                summary=str(result.get("summary") or ""),
                                blocked_reason=str(result.get("blocked_reason") or "") or None,
                                input_payload={
                                    "prompt": prompt,
                                    "feedback": retry_feedback,
                                    "context": context,
                                },
                                output_payload={
                                    "codex_run": result.get("codex_run", {}),
                                    "parsed_result": {
                                        "status": result.get("status"),
                                        "summary": result.get("summary"),
                                        "blocked_reason": result.get("blocked_reason"),
                                        "notes": result.get("notes"),
                                        "validation_commands": validation_commands,
                                    },
                                },
                                validation_payload={
                                    "commands": validation_commands,
                                    "results": validation_results,
                                },
                                review_payload={},
                                branch_name=branch_name,
                                commit_sha=commit_sha,
                                pr_url=pr_url,
                            )
                        )

                        if str(result.get("status") or "").strip() == "blocked" and not blocked_reason:
                            blocked_reason = str(result.get("blocked_reason") or "").strip()

                        if validation_failed:
                            audit_log_ids.append(
                                insert_audit_log(
                                    conn,
                                    item=item,
                                    attempt_no=attempt_count,
                                    stage="validation",
                                    round_no=round_no,
                                    event_type="stage",
                                    status="blocked",
                                    summary=str(result.get("summary") or ""),
                                    blocked_reason=blocked_reason or None,
                                    input_payload={"commands": validation_commands},
                                    output_payload={"results": validation_results},
                                    validation_payload={
                                        "commands": validation_commands,
                                        "results": validation_results,
                                    },
                                    review_payload={},
                                    branch_name=branch_name,
                                    commit_sha=commit_sha,
                                    pr_url=pr_url,
                                )
                            )
                            round_history.append(round_record)
                            if round_no >= MAX_IMPROVEMENT_ROUNDS:
                                status = "blocked"
                                blocked_reason = blocked_reason or "validation failed and retry budget exhausted"
                                break
                            blocked_reason = ""
                            continue

                        audit_log_ids.append(
                            insert_audit_log(
                                conn,
                                item=item,
                                attempt_no=attempt_count,
                                stage="validation",
                                round_no=round_no,
                                event_type="stage",
                                status=str(result.get("status") or "blocked"),
                                summary=str(result.get("summary") or ""),
                                blocked_reason=blocked_reason or None,
                                input_payload={"commands": validation_commands},
                                output_payload={"results": validation_results},
                                validation_payload={
                                    "commands": validation_commands,
                                    "results": validation_results,
                                },
                                review_payload={},
                                branch_name=branch_name,
                                commit_sha=commit_sha,
                                pr_url=pr_url,
                            )
                        )

                        if str(result.get("status") or "").strip() != "blocked" and not blocked_reason:
                            review_prompt = build_review_prompt(
                                item,
                                context,
                                {
                                    "status": result.get("status", "blocked"),
                                    "summary": result.get("summary", ""),
                                    "codex_run": result.get("codex_run", {}),
                                    "final_message": raw_text[:20000],
                                    "validation_commands": validation_commands,
                                },
                                round_record["validation"],
                            )
                            review_codex_run = run_codex_review(review_prompt, model, worktree_root)
                            review_raw_text = review_codex_run["final_message"]
                            review_result = parse_codex_json_result(review_raw_text, review_codex_run, stage="review")
                            round_record["review"] = {
                                "status": review_result.get("status", "blocked"),
                                "summary": review_result.get("summary", ""),
                                "findings": review_result.get("findings", []),
                                "codex_run": review_result.get("codex_run", {}),
                                "final_message": review_raw_text[:20000],
                            }

                            audit_log_ids.append(
                                insert_audit_log(
                                    conn,
                                    item=item,
                                    attempt_no=attempt_count,
                                    stage="review",
                                    round_no=round_no,
                                    event_type="stage",
                                    status=str(review_result.get("status") or "blocked"),
                                    summary=str(review_result.get("summary") or ""),
                                    blocked_reason=str(review_result.get("blocked_reason") or "") or None,
                                    input_payload={
                                        "prompt": review_prompt,
                                        "execution_result": {
                                            "status": result.get("status"),
                                            "summary": result.get("summary"),
                                        },
                                        "validation_result": round_record["validation"],
                                    },
                                    output_payload={
                                        "codex_run": review_codex_run,
                                        "parsed_result": review_result,
                                    },
                                    validation_payload=round_record["validation"],
                                    review_payload=review_result,
                                    branch_name=branch_name,
                                    commit_sha=commit_sha,
                                    pr_url=pr_url,
                                )
                            )

                            if str(review_result.get("status") or "").strip() == "done":
                                status = "done"
                                blocked_reason = ""
                                round_history.append(round_record)
                                break

                            if str(review_result.get("status") or "").strip() == "revise":
                                findings = review_result.get("findings", [])
                                finding_lines = []
                                if isinstance(findings, list):
                                    for finding in findings[:6]:
                                        if isinstance(finding, dict):
                                            finding_lines.append(
                                                f"[{finding.get('severity', 'medium')}] {finding.get('file', '')}: {finding.get('message', '')}"
                                            )
                                retry_feedback = "\n".join(
                                    [
                                        f"自己レビューで修正要求あり: {review_result.get('summary', '')}",
                                        *finding_lines,
                                        str(review_result.get("notes") or "").strip(),
                                    ]
                                ).strip()
                                blocked_reason = ""
                                round_history.append(round_record)
                                if round_no >= MAX_IMPROVEMENT_ROUNDS:
                                    status = "blocked"
                                    blocked_reason = "self review requested revision but retry budget exhausted"
                                    break
                                continue

                            status = "blocked"
                            blocked_reason = str(review_result.get("blocked_reason") or "").strip() or "self review blocked"
                            round_history.append(round_record)
                            break

                        if str(result.get("status") or "").strip() == "blocked":
                            status = "blocked"
                            round_history.append(round_record)
                            break

                        round_history.append(round_record)
                        status = "done"
                        blocked_reason = ""
                        break

                    if round_history:
                        latest_round = round_history[-1]
                        latest_execution = latest_round.get("execution", {})
                        result = {
                            "status": status,
                            "summary": latest_execution.get("summary", ""),
                            "validation_commands": latest_round.get("validation", {}).get("commands", []),
                            "blocked_reason": blocked_reason,
                            "notes": str((latest_round.get("review") or {}).get("notes") or ""),
                            "codex_run": latest_execution.get("codex_run", {}),
                            "final_message": latest_execution.get("final_message", ""),
                        }
                        if latest_round.get("review"):
                            result["self_review"] = latest_round["review"]

                status = str(status or result.get("status") or "blocked")
                blocked_reason = str(blocked_reason or result.get("blocked_reason") or "").strip()

                validation_commands = result.get("validation_commands")
                if not isinstance(validation_commands, list):
                    validation_commands = []
                if not validation_commands:
                    validation_commands = parse_json(item.get("validation_commands_json"), [])
                if not isinstance(validation_commands, list):
                    validation_commands = []

                if not validation_results and status != "blocked" and validation_commands:
                    validation_results = run_validation_commands(worktree_root or ROOT, [str(x) for x in validation_commands])
                    failed = next((r for r in validation_results if int(r.get("returncode") or 0) != 0), None)
                    if failed:
                        status = "blocked"
                        blocked_reason = f"validation failed: {failed['command']}"

                if status == "done" and not args.dry_run:
                    if not branch_name:
                        branch_name = make_branch_name(item)
                    title = str(item.get("work_title") or f"improvement item {item.get('id')}")
                    commit_message = f"improvement: {title}".strip()
                    commit_sha = commit_changes(worktree_root or ROOT, commit_message)
                    update_work_item(
                        conn,
                        work_id=int(item["id"]),
                        fields={
                            "branch_name": branch_name,
                            "commit_sha": commit_sha,
                        },
                    )
                    conn.commit()
                    push_branch(worktree_root or ROOT, branch_name, str(item.get("repository_full_name") or ""), github_token)
                    base_branch = get_default_branch(str(item.get("repository_full_name") or ""), github_token)
                    pr_body_lines = [
                        f"## Work Item",
                        f"- id: {item.get('id')}",
                        f"- source_key: {item.get('source_key')}",
                        f"- candidate_date: {item.get('candidate_date')}",
                        "",
                        "## Summary",
                        str(result.get("summary") or "").strip(),
                        "",
                        "## Validation",
                    ]
                    if validation_results:
                        for r in validation_results:
                            pr_body_lines.append(
                                f"- `{r.get('command')}` => {int(r.get('returncode') or 0)}"
                            )
                    else:
                        pr_body_lines.append("- validation commands: none")
                    pr_body_lines.extend(
                        [
                            "",
                            "## Codex",
                            f"- model: {model}",
                            f"- route: {args.model_route}",
                            f"- commit: `{commit_sha}`",
                        ]
                    )
                    pr = create_pull_request(
                        str(item.get("repository_full_name") or ""),
                        github_token,
                        branch_name=branch_name,
                        base_branch=base_branch,
                        title=title,
                        body="\n".join(pr_body_lines).strip() + "\n",
                    )
                    pr_url = str(pr.get("html_url") or "").strip()
                    if pr_url:
                        update_work_item(
                            conn,
                            work_id=int(item["id"]),
                            fields={
                                "pr_url": pr_url,
                            },
                        )
                        conn.commit()

                changed_files = commit_changed_files(worktree_root or ROOT, commit_sha) if commit_sha else []
                diff_summary = commit_diff_summary(worktree_root or ROOT, commit_sha) if commit_sha else {}
                final_status = "done" if status == "done" and (args.dry_run or pr_url or commit_sha) else "blocked"
                if status == "done" and not args.dry_run and not pr_url:
                    final_status = "blocked"
                    if not blocked_reason:
                        blocked_reason = "pull request creation failed"

                audit_log_ids.append(
                    insert_audit_log(
                        conn,
                        item=item,
                        attempt_no=attempt_count,
                        stage="final",
                        round_no=len(round_history),
                        event_type="final",
                        status=final_status,
                        summary=str(result.get("summary") or ""),
                        blocked_reason=blocked_reason or None,
                        input_payload={
                            "rounds": round_history,
                            "validation_commands": validation_commands,
                        },
                        output_payload={
                            "final_status": final_status,
                            "branch_name": branch_name,
                            "commit_sha": commit_sha,
                            "pr_url": pr_url,
                        },
                        validation_payload={
                            "commands": validation_commands,
                            "results": validation_results,
                        },
                        review_payload=result.get("self_review", review_result) or {},
                        branch_name=branch_name,
                        commit_sha=commit_sha,
                        pr_url=pr_url,
                    )
                )

                execution_result = {
                    "tool": "codex exec",
                    "model": model,
                    "model_route": args.model_route,
                    "status": status,
                    "summary": result.get("summary", ""),
                    "rounds": round_history,
                    "context": {
                        "target_patterns": context["target_patterns"],
                        "resolved_target_files": context["resolved_target_files"],
                        "git_status": context["git_status"],
                        "git_diff_stat": context["git_diff_stat"],
                    },
                    "codex_run": result.get("codex_run", {}),
                    "final_message": raw_text[:20000],
                    "worktree_root": str(worktree_root) if worktree_root else "",
                    "branch_name": branch_name,
                    "commit_sha": commit_sha,
                    "pr_url": pr_url,
                    "self_review": result.get("self_review", review_result),
                }
                validation_result = {
                    "commands": validation_commands,
                    "results": validation_results,
                    "rounds": [
                        {
                            "round": round_item.get("round"),
                            "validation": round_item.get("validation", {}),
                            "review": round_item.get("review"),
                        }
                        for round_item in round_history
                    ],
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
                    "audit_log_ids_json": json.dumps(audit_log_ids, ensure_ascii=False),
                    "work_status": final_status,
                    "review_status": "ready" if final_status == "done" else "pending",
                    "blocked_reason": blocked_reason or None,
                    "error_message": blocked_reason or None,
                    "branch_name": branch_name or None,
                    "commit_sha": commit_sha or None,
                    "pr_url": pr_url or None,
                }
                if final_status == "done":
                    update_fields["completed_at"] = now_iso()
                if not args.dry_run:
                    update_work_item(conn, work_id=int(item["id"]), fields=update_fields)
                    conn.commit()
                processed += 1
            except Exception as exc:
                blocked_reason = blocked_reason or f"{type(exc).__name__}: {exc}"
                result = result or {"status": "blocked", "summary": "", "codex_run": {}}
                changed_files = commit_changed_files(worktree_root or ROOT, commit_sha) if commit_sha else []
                diff_summary = commit_diff_summary(worktree_root or ROOT, commit_sha) if commit_sha else {}
                if not args.dry_run:
                    update_fields = {
                        "work_status": "blocked",
                        "review_status": "pending",
                        "blocked_reason": blocked_reason,
                        "error_message": blocked_reason,
                        "branch_name": branch_name or None,
                        "commit_sha": commit_sha or None,
                        "pr_url": pr_url or None,
                        "audit_log_ids_json": json.dumps(audit_log_ids, ensure_ascii=False),
                        "execution_commands_json": json.dumps(
                            [" ".join(result.get("codex_run", {}).get("command", ["codex", "exec"]))] if result.get("codex_run") else [],
                            ensure_ascii=False,
                        ),
                        "validation_commands_json": json.dumps(validation_commands, ensure_ascii=False),
                        "execution_result_json": json.dumps(
                            {
                                "tool": "codex exec",
                                "model": model,
                                "model_route": args.model_route,
                                "status": "blocked",
                                "summary": str(result.get("summary") or ""),
                                "context": context,
                                "codex_run": result.get("codex_run", {}),
                                "final_message": raw_text[:20000],
                                "worktree_root": str(worktree_root) if worktree_root else "",
                                "branch_name": branch_name,
                                "commit_sha": commit_sha,
                                "pr_url": pr_url,
                            },
                            ensure_ascii=False,
                        ),
                        "validation_result_json": json.dumps(
                            {"commands": validation_commands, "results": validation_results},
                            ensure_ascii=False,
                        ),
                        "changed_files_json": json.dumps(changed_files, ensure_ascii=False),
                        "diff_summary_json": json.dumps(diff_summary, ensure_ascii=False),
                    }
                    update_work_item(conn, work_id=int(item["id"]), fields=update_fields)
                    audit_log_ids.append(
                        insert_audit_log(
                            conn,
                            item=item,
                            attempt_no=attempt_count,
                            stage="final",
                            round_no=len(round_history),
                            event_type="error",
                            status="blocked",
                            summary=str(result.get("summary") or ""),
                            blocked_reason=blocked_reason,
                            input_payload={
                                "rounds": round_history,
                                "validation_commands": validation_commands,
                            },
                            output_payload={
                                "error": blocked_reason,
                                "branch_name": branch_name,
                                "commit_sha": commit_sha,
                                "pr_url": pr_url,
                            },
                            validation_payload={
                                "commands": validation_commands,
                                "results": validation_results,
                            },
                            review_payload=result.get("self_review", review_result) or {},
                            branch_name=branch_name,
                            commit_sha=commit_sha,
                            pr_url=pr_url,
                        )
                    )
                    update_work_item(
                        conn,
                        work_id=int(item["id"]),
                        fields={"audit_log_ids_json": json.dumps(audit_log_ids, ensure_ascii=False)},
                    )
                    conn.commit()
                processed += 1
            finally:
                if worktree_root and worktree_root != ROOT:
                    cleanup_worktree(worktree_root)

        print(f"executed: improvement_work_items {processed} rows")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
