#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.platform_core_bootstrap import ensure_platform_core_importable

ensure_platform_core_importable()

DEFAULT_OPS_DB = ROOT / "data" / "ops.db"
DEFAULT_REPOSITORY = "yuta-kkkk0908/workSpace"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate Codex-log proposals from improvement candidates")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_OPS_DB)
    p.add_argument("--min-priority", type=int, default=75)
    p.add_argument("--max-issues", type=int, default=5)
    p.add_argument("--codex-webhook", default="", help="Override codex-log webhook URL")
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


def infer_repository_full_name() -> str:
    repo = (os.environ.get("GITHUB_REPOSITORY") or os.environ.get("GH_REPOSITORY") or "").strip()
    if repo:
        return repo
    try:
        import subprocess

        remote = subprocess.check_output(["git", "remote", "get-url", "origin"], cwd=str(ROOT), text=True).strip()
    except Exception:
        remote = ""
    if remote:
        if remote.startswith("git@github.com:"):
            return remote.split("git@github.com:", 1)[1].removesuffix(".git")
        if remote.startswith("https://github.com/"):
            return remote.split("https://github.com/", 1)[1].removesuffix(".git")
    return DEFAULT_REPOSITORY


def load_candidates(conn: sqlite3.Connection, date_s: str, min_priority: int, max_issues: int) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, candidate_date, source_key, title, category, source, description,
               impact_score, effort_score, priority, status, evidence_json
        FROM improvement_candidate
        WHERE candidate_date=? AND priority>=?
        ORDER BY priority DESC, id ASC
        LIMIT ?
        """,
        (date_s, int(min_priority), int(max_issues)),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_existing_proposal(conn: sqlite3.Connection, date_s: str, source_key: str, repository_full_name: str) -> dict[str, Any] | None:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT *
        FROM improvement_proposals
        WHERE candidate_date=? AND source_key=? AND repository_full_name=?
        """,
        (date_s, source_key, repository_full_name),
    ).fetchone()
    return dict(row) if row else None


def candidate_to_body(candidate: dict[str, Any]) -> dict[str, Any]:
    evidence = {}
    try:
        evidence = json.loads(candidate.get("evidence_json") or "{}")
    except Exception:
        evidence = {}
    source = str(candidate.get("source") or "unknown")
    category = str(candidate.get("category") or "other")
    description = str(candidate.get("description") or "").strip() or "不明"

    file_hints = {
        "ops": [
            "scripts/run_ops_scheduler.py",
            "scripts/check_scheduler_health.py",
            "scripts/data/ingest_ops_logs.py",
        ],
        "delivery": [
            "scripts/notify/*",
            "scripts/ops/*",
        ],
        "pipeline": [
            "scripts/run_ops_scheduler.py",
            "scripts/investment/analysis/*",
            "scripts/investment/signals/*",
        ],
        "analysis": [
            "scripts/investment/analysis/*",
            "scripts/data/init_investment_db.py",
        ],
        "needs": [
            "scripts/build_needs_ai_queue.py",
            "scripts/apply_needs_triage.py",
            "scripts/data/ingest_needs_db.py",
        ],
    }.get(category, ["不明"])

    expected_effect = {
        "ops": "再発障害の把握を早め、運用停止や再送の手戻りを減らす。",
        "delivery": "通知失敗の再発を抑え、監視の見落としを減らす。",
        "pipeline": "パイプラインの失敗箇所を明確化し、次回の障害切り分けを短縮する。",
        "analysis": "分析の論点整理を安定させ、監査と改善の往復を短くする。",
        "needs": "未整理ニーズの束ねと優先順位付けを安定化する。",
    }.get(category, "改善の再現性と追跡性を高める。")

    body_json = {
        "candidate": {
            "id": candidate.get("id"),
            "candidate_date": candidate.get("candidate_date"),
            "source_key": candidate.get("source_key"),
            "title": candidate.get("title"),
            "category": category,
            "source": source,
            "description": description,
            "impact_score": candidate.get("impact_score"),
            "effort_score": candidate.get("effort_score"),
            "priority": candidate.get("priority"),
            "status": candidate.get("status"),
            "evidence": evidence,
        },
        "proposal_template": {
            "phenomenon": description,
            "cause_candidates": [
                f"{source} に関連する再発条件の未整理",
                "現行の監視/再送/集計の閾値が実運用に合っていない可能性",
            ],
            "improvement_plan": [
                "再発条件を source_key 単位で追跡できるようにする",
                "検知条件と通知条件を分離する",
                "失敗時の記録を DB に集約する",
            ],
            "expected_effect": expected_effect,
            "file_hints": file_hints,
        },
    }
    body_lines = [
        "## 現象",
        description,
        "",
        "## 原因候補",
        f"- source: {source}",
        f"- category: {category}",
        "- 再発条件が未整理の可能性",
        "",
        "## 改善案",
        "- 再発条件を source_key 単位で追跡できるようにする",
        "- 検知・通知・再送の条件を分離する",
        "- 失敗時の記録を DB に集約する",
        "",
        "## 期待効果",
        f"- {expected_effect}",
        "",
        "## 実装対象ファイル候補",
    ]
    for hint in file_hints:
        body_lines.append(f"- {hint}")
    body_lines.extend(
        [
            "",
            "## 監査メモ",
            f"- priority: {candidate.get('priority')}",
            f"- impact_score: {candidate.get('impact_score')}",
            f"- effort_score: {candidate.get('effort_score')}",
            f"- source_key: {candidate.get('source_key')}",
            f"- evidence: {json.dumps(evidence, ensure_ascii=False)[:800]}",
        ]
    )
    return {
        "proposal_title": str(candidate.get("title") or "改善案"),
        "proposal_body": "\n".join(body_lines).strip() + "\n",
        "proposal_body_json": body_json,
        "labels_json": json.dumps([category, "improvement"], ensure_ascii=False),
        "priority": int(candidate.get("priority") or 0),
    }


def save_proposal(
    conn: sqlite3.Connection,
    *,
    date_s: str,
    source_key: str,
    repository_full_name: str,
    proposal_title: str,
    proposal_body: str,
    proposal_body_json: dict[str, Any],
    labels_json: str,
    priority: int,
    proposal_status: str,
    error_message: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO improvement_proposals(
          candidate_date, source_key, repository_full_name, proposal_title, proposal_body, proposal_body_json,
          labels_json, priority, proposal_status, error_message,
          created_at, updated_at
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))
        ON CONFLICT(candidate_date, source_key, repository_full_name) DO UPDATE SET
          proposal_title=excluded.proposal_title,
          proposal_body=excluded.proposal_body,
          proposal_body_json=excluded.proposal_body_json,
          labels_json=excluded.labels_json,
          priority=excluded.priority,
          proposal_status=excluded.proposal_status,
          error_message=excluded.error_message,
          updated_at=excluded.updated_at
        """,
        (
            date_s,
            source_key,
            repository_full_name,
            proposal_title,
            proposal_body,
            json.dumps(proposal_body_json, ensure_ascii=False),
            labels_json,
            int(priority),
            proposal_status,
            error_message,
        ),
    )


def update_candidate_status(conn: sqlite3.Connection, date_s: str, source_key: str, status: str) -> None:
    conn.execute(
        """
        UPDATE improvement_candidate
        SET status=?, updated_at=datetime('now')
        WHERE candidate_date=? AND source_key=?
        """,
        (status, date_s, source_key),
    )


def load_codex_webhook(explicit: str) -> str:
    if explicit.strip():
        return explicit.strip()
    return (
        os.environ.get("DISCORD_CODEX_LOGER_CHANNEL_HOOK", "").strip()
        or os.environ.get("DISCORD_CODEX_LOGGER_CHANNEL_HOOK", "").strip()
    )


def split_message(text: str, limit: int = 1800) -> list[str]:
    lines = text.splitlines()
    chunks: list[str] = []
    buf = ""
    for line in lines:
        candidate = f"{buf}\n{line}".strip("\n") if buf else line
        if len(candidate) <= limit:
            buf = candidate
            continue
        if buf:
            chunks.append(buf)
        if len(line) <= limit:
            buf = line
        else:
            for i in range(0, len(line), limit):
                chunks.append(line[i : i + limit])
            buf = ""
    if buf:
        chunks.append(buf)
    return chunks or [text[:limit]]


def post_codex_log(webhook_url: str, content: str) -> None:
    body = json.dumps({"content": content, "allowed_mentions": {"parse": []}}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "curl/8.8.0",
        },
    )
    with urllib.request.urlopen(req, timeout=20):
        return


def main() -> int:
    args = parse_args()
    load_dotenv()

    repository_full_name = infer_repository_full_name()
    webhook_url = load_codex_webhook(args.codex_webhook)

    conn = sqlite3.connect(args.db)
    try:
        candidates = load_candidates(conn, args.date, args.min_priority, args.max_issues)
        if not candidates:
            print("skip: no candidates for proposals")
            return 0

        saved = 0
        for candidate in candidates:
            proposal = candidate_to_body(candidate)
            existing = fetch_existing_proposal(conn, args.date, str(candidate["source_key"]), repository_full_name)
            if existing and str(existing.get("proposal_status") or "") in {"posted", "queued"}:
                continue

            proposal_status = "queued" if not webhook_url else "posted"
            error_message = None
            post_text = (
                f"[Improvement Proposal] {proposal['proposal_title']}\n"
                f"- date: {args.date}\n"
                f"- source_key: {candidate['source_key']}\n"
                f"- priority: {candidate.get('priority')}\n"
                f"- impact: {candidate.get('impact_score')} / effort: {candidate.get('effort_score')}\n"
                f"- repository: {repository_full_name}\n\n"
                f"{proposal['proposal_body']}"
            )
            if webhook_url:
                try:
                    for chunk in split_message(post_text):
                        post_codex_log(webhook_url, chunk)
                except Exception as exc:
                    proposal_status = "error"
                    error_message = f"{type(exc).__name__}: {exc}"

            save_proposal(
                conn,
                date_s=args.date,
                source_key=str(candidate["source_key"]),
                repository_full_name=repository_full_name,
                proposal_title=proposal["proposal_title"],
                proposal_body=proposal["proposal_body"],
                proposal_body_json=proposal["proposal_body_json"],
                labels_json=proposal["labels_json"],
                priority=int(proposal["priority"]),
                proposal_status=proposal_status,
                error_message=error_message,
            )
            if proposal_status in {"posted", "queued"}:
                update_candidate_status(conn, args.date, str(candidate["source_key"]), "reviewing")
            saved += 1

        conn.commit()
    finally:
        conn.close()

    print(f"saved: ops.db improvement_proposals {saved} rows")
    print(f"codex_log_webhook: {'set' if webhook_url else 'missing'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
