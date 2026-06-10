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


def run_codex_exec(prompt: str, model: str, worktree_root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="codex-exec-") as tmpdir:
        tmp = Path(tmpdir)
        schema_path = tmp / "output-schema.json"
        message_path = tmp / "last-message.json"
        schema_path.write_text(json.dumps(codex_output_schema(), ensure_ascii=False, indent=2), encoding="utf-8")

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


def main() -> int:
    args = parse_args()
    load_dotenv()
    _provider, route_model = resolve_model(args.model_route)
    model = args.model.strip() or route_model
    github_token = get_github_token()

    conn = sqlite3.connect(args.db)
    try:
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
                    prompt = build_prompt(item, context)
                    codex_run = run_codex_exec(prompt, model, worktree_root)
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

                if status != "blocked" and validation_commands:
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
                    "worktree_root": str(worktree_root) if worktree_root else "",
                    "branch_name": branch_name,
                    "commit_sha": commit_sha,
                    "pr_url": pr_url,
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
