#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.platform_core_bootstrap import ensure_platform_core_importable

ensure_platform_core_importable()

DEFAULT_OPS_DB = ROOT / "data" / "ops.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Materialize improvement proposals into DB work items")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_OPS_DB)
    p.add_argument("--limit", type=int, default=20)
    return p.parse_args()


def load_proposals(conn: sqlite3.Connection, date_s: str, limit: int) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT *
        FROM improvement_proposals
        WHERE candidate_date <= ?
          AND proposal_status IN ('posted', 'queued')
        ORDER BY candidate_date DESC, priority DESC, id ASC
        LIMIT ?
        """,
        (date_s, int(limit)),
    ).fetchall()
    return [dict(r) for r in rows]


def has_work_item(conn: sqlite3.Connection, proposal_id: int) -> bool:
    row = conn.execute("SELECT 1 FROM improvement_work_items WHERE proposal_id=?", (proposal_id,)).fetchone()
    return bool(row)


def build_work_json(proposal: dict[str, Any]) -> dict[str, Any]:
    proposal_body_json: dict[str, Any] = {}
    try:
        raw = proposal.get("proposal_body_json") or "{}"
        if isinstance(raw, str):
            parsed = json.loads(raw)
            proposal_body_json = parsed if isinstance(parsed, dict) else {}
        elif isinstance(raw, dict):
            proposal_body_json = raw
    except Exception:
        proposal_body_json = {}

    plan = []
    target_files: list[str] = []
    proposal_template = proposal_body_json.get("proposal_template")
    if isinstance(proposal_template, dict):
        maybe_plan = proposal_template.get("improvement_plan")
        if isinstance(maybe_plan, list):
            plan = [str(x) for x in maybe_plan if str(x).strip()]
        maybe_files = proposal_template.get("file_hints")
        if isinstance(maybe_files, list):
            target_files = [str(x) for x in maybe_files if str(x).strip()]

    next_action = plan[0] if plan else str(proposal.get("proposal_body") or "").splitlines()[0:1]
    if isinstance(next_action, list):
        next_action = next_action[0] if next_action else "proposal を確認する"

    py_files = [p for p in target_files if p.endswith(".py") and "*" not in p and "?" not in p]
    validation_commands: list[str] = []
    if py_files:
        validation_commands.append("python3 -m py_compile " + " ".join(py_files))
    else:
        validation_commands.append("python3 -m pytest -q")

    return {
        "source": "improvement_proposals",
        "proposal": {
            "id": proposal.get("id"),
            "candidate_date": proposal.get("candidate_date"),
            "source_key": proposal.get("source_key"),
            "repository_full_name": proposal.get("repository_full_name"),
            "proposal_title": proposal.get("proposal_title"),
            "proposal_body_json": proposal_body_json,
            "labels_json": proposal.get("labels_json"),
            "priority": proposal.get("priority"),
            "proposal_status": proposal.get("proposal_status"),
            "error_message": proposal.get("error_message"),
        },
        "work": {
            "summary": str(proposal.get("proposal_title") or "改善案"),
            "next_action": next_action or "proposal を確認する",
            "improvement_plan": plan,
            "target_files": target_files,
            "acceptance_criteria": [
                "変更内容が proposal の目的と一致している",
                "検証コマンドが少なくとも 1 件記録されている",
                "work item の状態遷移が DB に残る",
            ],
            "validation_commands": validation_commands,
            "ready_for_codex": True,
        },
    }


def save_work_item(conn: sqlite3.Connection, proposal: dict[str, Any], work_json: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO improvement_work_items(
            proposal_id, candidate_date, source_key, repository_full_name, work_title, work_body_json,
            work_plan_json, target_files_json, execution_commands_json, validation_commands_json,
            execution_result_json, validation_result_json, changed_files_json, diff_summary_json,
            work_status, work_priority, review_status, claimed_by, claimed_at, started_at, completed_at,
            branch_name, commit_sha, pr_url, blocked_reason, attempt_count, last_attempt_at, error_message,
          created_at, updated_at
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))
        ON CONFLICT(proposal_id) DO UPDATE SET
          candidate_date=excluded.candidate_date,
          source_key=excluded.source_key,
          repository_full_name=excluded.repository_full_name,
          work_title=excluded.work_title,
          work_body_json=excluded.work_body_json,
          work_plan_json=excluded.work_plan_json,
          target_files_json=excluded.target_files_json,
          execution_commands_json=excluded.execution_commands_json,
          validation_commands_json=excluded.validation_commands_json,
          execution_result_json=excluded.execution_result_json,
          validation_result_json=excluded.validation_result_json,
          changed_files_json=excluded.changed_files_json,
          diff_summary_json=excluded.diff_summary_json,
          work_priority=excluded.work_priority,
          review_status=excluded.review_status,
          blocked_reason=excluded.blocked_reason,
          error_message=excluded.error_message,
          updated_at=excluded.updated_at
        """,
        (
            int(proposal["id"]),
            str(proposal["candidate_date"]),
            str(proposal["source_key"]),
            str(proposal["repository_full_name"]),
            str(proposal["proposal_title"] or "改善案"),
            json.dumps(work_json, ensure_ascii=False),
            json.dumps(
                {
                    "goal": str(proposal.get("proposal_title") or "改善案"),
                    "steps": [
                        "対象ファイルと周辺コードを読む",
                        "必要な変更を実施する",
                        "検証コマンドを実行する",
                        "変更と検証結果をDBに残す",
                    ],
                    "acceptance_criteria": work_json["work"]["acceptance_criteria"],
                    "next_action": work_json["work"]["next_action"],
                },
                ensure_ascii=False,
            ),
            json.dumps(work_json["work"]["target_files"], ensure_ascii=False),
            json.dumps([], ensure_ascii=False),
            json.dumps(work_json["work"]["validation_commands"], ensure_ascii=False),
            json.dumps({}, ensure_ascii=False),
            json.dumps({}, ensure_ascii=False),
            json.dumps([], ensure_ascii=False),
            json.dumps({}, ensure_ascii=False),
            "open",
            int(proposal.get("priority") or 0),
            "pending",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            0,
            None,
            None,
        ),
    )


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    try:
        proposals = load_proposals(conn, args.date, args.limit)
        if not proposals:
            print("skip: no proposals to materialize")
            return 0

        created = 0
        updated = 0
        for proposal in proposals:
            proposal_id = int(proposal["id"])
            existed = has_work_item(conn, proposal_id)
            work_json = build_work_json(proposal)
            save_work_item(conn, proposal, work_json)
            if existed:
                updated += 1
            else:
                created += 1

        conn.commit()
    finally:
        conn.close()

    print(f"materialized: improvement_work_items created={created} updated={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
