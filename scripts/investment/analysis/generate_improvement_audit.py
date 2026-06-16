#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.platform_core_bootstrap import ensure_platform_core_importable
from utils.env_loader import load_env_files

ensure_platform_core_importable()
from utils.investment_db_path import resolve_investment_db
from platform_core.model_router import resolve_model
from platform_core.openai_client import call_openai_text

DEFAULT_INVESTMENT_DB = resolve_investment_db()
DEFAULT_OPS_DB = ROOT / "data" / "ops.db"
DEFAULT_NEEDS_DB = ROOT / "data" / "needs.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Weekly improvement audit and candidate generation")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--window-days", type=int, default=7)
    p.add_argument("--ops-db", type=Path, default=DEFAULT_OPS_DB)
    p.add_argument("--investment-db", type=Path, default=DEFAULT_INVESTMENT_DB)
    p.add_argument("--needs-db", type=Path, default=DEFAULT_NEEDS_DB)
    p.add_argument("--model-route", default="improvement_audit_weekly")
    p.add_argument("--topn", type=int, default=10)
    return p.parse_args()


def load_dotenv() -> None:
    load_env_files(ROOT / ".env.local", ROOT / ".env")


def _date_bounds(date_s: str, window_days: int) -> tuple[str, str]:
    end = datetime.strptime(date_s, "%Y-%m-%d").date() + timedelta(days=1)
    start = end - timedelta(days=max(1, int(window_days)))
    return start.isoformat(), end.isoformat()


def _safe_json(value: str | None, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _parse_json_text(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(raw[start : end + 1])
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}
    return {}


def _stable_source_key(prefix: str, *parts: str) -> str:
    joined = "|".join(p.strip() for p in parts if p is not None and str(p).strip())
    digest = hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}.{digest}"


def fetch_task_error_seeds(conn: sqlite3.Connection, start_ts: str, end_ts: str) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(task_log_events)").fetchall()}
    has_source_key = "source_key" in columns
    source_key_expr = "COALESCE(NULLIF(source_key, ''), '')" if has_source_key else "''"
    source_key_group_expr = source_key_expr if has_source_key else "task_name"
    source_key_select_expr = source_key_expr if has_source_key else "task_name"
    rows = conn.execute(
        """
        SELECT
               {source_key_select_expr} AS source_key,
               task_name, level, COUNT(*) AS cnt, MAX(ts) AS last_ts,
               MAX(COALESCE(message, '')) AS sample_message
        FROM task_log_events
        WHERE ts >= ? AND ts < ?
          AND LOWER(level) IN ('error', 'exception', 'fatal')
        GROUP BY {source_key_group_expr}, task_name, level
        HAVING COUNT(*) >= 1
        ORDER BY cnt DESC, {source_key_group_expr}, task_name
        LIMIT 20
        """.format(
            source_key_select_expr=source_key_select_expr,
            source_key_group_expr=source_key_group_expr,
        ),
        (start_ts, end_ts),
    ).fetchall()
    seeds: list[dict[str, Any]] = []
    for row in rows:
        task = str(row["task_name"] or "unknown")
        source_key = str(row["source_key"] or f"ops.task.{task.lower()}")
        cnt = int(row["cnt"] or 0)
        msg = str(row["sample_message"] or "").strip()
        seeds.append(
            {
                "source_key": source_key,
                "title": f"{task} のエラー再発を確認",
                "category": "ops",
                "source": "ops.task_log_events",
                "description": f"過去{cnt}件のエラー/例外が記録されている。最新例: {msg or '不明'}",
                "impact_score": 90 if cnt >= 3 else 75,
                "effort_score": 30,
                "priority": 90 if cnt >= 3 else 75,
                "status": "open",
                "evidence": dict(row),
            }
        )
    return seeds


def fetch_discord_error_seeds(conn: sqlite3.Connection, start_ts: str, end_ts: str) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT channel, level, message, COUNT(*) AS cnt
        FROM discord_log_events
        WHERE ts >= ? AND ts < ?
          AND LOWER(level) IN ('error', 'warn', 'warning')
        GROUP BY channel, level, message
        ORDER BY cnt DESC, channel
        LIMIT 20
        """,
        (start_ts, end_ts),
    ).fetchall()
    seeds: list[dict[str, Any]] = []
    for row in rows:
        msg = str(row["message"] or "").strip()
        channel = str(row["channel"] or "unknown")
        cnt = int(row["cnt"] or 0)
        normalized = msg.lower()
        if "429" in normalized or "rate limit" in normalized:
            impact = 85
            effort = 20
            category = "delivery"
            title = f"{channel} の Discord 送信レート制限を軽減"
        elif "403" in normalized or "forbidden" in normalized:
            impact = 90
            effort = 25
            category = "delivery"
            title = f"{channel} の Discord 権限/配信失敗を修正"
        else:
            impact = 70 if cnt == 1 else 80
            effort = 30
            category = "delivery"
            title = f"{channel} の Discord 通知失敗を点検"
        seeds.append(
            {
                "source_key": _stable_source_key("discord", channel, str(row["level"] or "").lower(), msg),
                "title": title,
                "category": category,
                "source": f"discord_log_events:{channel}",
                "description": f"Discordログに {cnt} 件の {str(row['level'] or '').upper()}。最新メッセージ: {msg or '不明'}",
                "impact_score": impact,
                "effort_score": effort,
                "priority": impact - effort,
                "status": "open",
                "evidence": dict(row),
            }
        )
    return seeds


def fetch_pipeline_error_seeds(conn: sqlite3.Connection, start_ts: str, end_ts: str) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT pipeline, slot, stage, status, level, COUNT(*) AS cnt, MAX(event_time) AS last_event_time
        FROM pipeline_events
        WHERE event_time >= ? AND event_time < ?
          AND (
            LOWER(COALESCE(status, '')) LIKE '%error%'
            OR LOWER(COALESCE(status, '')) LIKE '%fail%'
            OR LOWER(COALESCE(level, '')) IN ('error', 'warning')
          )
        GROUP BY pipeline, slot, stage, status, level
        ORDER BY cnt DESC, pipeline, stage
        LIMIT 20
        """,
        (start_ts, end_ts),
    ).fetchall()
    seeds: list[dict[str, Any]] = []
    for row in rows:
        pipeline = str(row["pipeline"] or "unknown")
        stage = str(row["stage"] or "unknown")
        status = str(row["status"] or row["level"] or "unknown")
        cnt = int(row["cnt"] or 0)
        seeds.append(
            {
                "source_key": f"pipeline.{pipeline}.{stage}",
                "title": f"{pipeline} / {stage} の失敗経路を点検",
                "category": "pipeline",
                "source": "pipeline_events",
                "description": f"期間内に {cnt} 件の {status} を検知。処理を止める前に再発条件を確認する。",
                "impact_score": 80 if cnt >= 2 else 65,
                "effort_score": 40,
                "priority": 80 if cnt >= 2 else 65,
                "status": "open",
                "evidence": dict(row),
            }
        )
    return seeds


def fetch_signal_quality_seeds(conn: sqlite3.Connection, date_s: str) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT artifact_key, artifact_date, artifact_type, payload_json, updated_at
        FROM collection_artifacts
        WHERE artifact_key IN ('signal_quality_ai_triage', 'scenario_promotion_ai_review', 'ai_analyst_report', 'weekly_tuning_ai_review')
          AND artifact_date <= ?
        ORDER BY artifact_date DESC, updated_at DESC
        LIMIT 8
        """,
        (date_s,),
    ).fetchall()
    seeds: list[dict[str, Any]] = []
    for row in rows:
        key = str(row["artifact_key"] or "artifact")
        payload = _safe_json(str(row["payload_json"] or "{}"), {})
        summary_bits: list[str] = []
        if isinstance(payload, dict):
            for field in ("review", "analysis", "report"):
                if payload.get(field):
                    summary_bits.append(str(payload[field]).strip())
                    break
            if not summary_bits:
                summary_bits.append(json.dumps(payload, ensure_ascii=False)[:240])
        else:
            summary_bits.append(str(payload)[:240])
        seeds.append(
            {
                "source_key": f"artifact.{key}.{str(row['artifact_date'] or '')}",
                "title": f"{key} の改善論点を整理",
                "category": "analysis",
                "source": f"collection_artifacts:{key}",
                "description": summary_bits[0] or "不明",
                "impact_score": 70,
                "effort_score": 35,
                "priority": 65,
                "status": "open",
                "evidence": {
                    "artifact_key": key,
                    "artifact_date": row["artifact_date"],
                    "artifact_type": row["artifact_type"],
                    "updated_at": row["updated_at"],
                },
            }
        )
    return seeds


def fetch_need_backlog_seed(conn: sqlite3.Connection, date_s: str) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS total_rows
            FROM need_items
            WHERE date >= date(?, '-7 day')
            """,
            (date_s,),
        ).fetchone()
    except sqlite3.OperationalError:
        return []
    total_rows = int(row["total_rows"] or 0) if row else 0
    if total_rows < 20:
        return []
    return [
        {
            "source_key": f"needs.backlog.{date_s}",
            "title": "needs バックログの滞留を抑える",
            "category": "needs",
            "source": "needs.db",
            "description": f"過去7日で need_items が {total_rows} 件。分類・統合・昇格の滞留が起きやすい。",
            "impact_score": 60,
            "effort_score": 25,
            "priority": 55,
            "status": "open",
            "evidence": {"total_rows_7d": total_rows},
        }
    ]


def build_seed_list(ops_db: Path, investment_db: Path, needs_db: Path, date_s: str, window_days: int) -> list[dict[str, Any]]:
    start, end = _date_bounds(date_s, window_days)
    start_ts = f"{start} 00:00:00"
    end_ts = f"{end} 00:00:00"

    seeds: list[dict[str, Any]] = []

    if ops_db.exists():
        conn = sqlite3.connect(ops_db)
        try:
            seeds.extend(fetch_task_error_seeds(conn, start_ts, end_ts))
            seeds.extend(fetch_discord_error_seeds(conn, start_ts, end_ts))
        finally:
            conn.close()

    if investment_db.exists():
        conn = sqlite3.connect(investment_db)
        try:
            seeds.extend(fetch_pipeline_error_seeds(conn, start_ts, end_ts))
            seeds.extend(fetch_signal_quality_seeds(conn, date_s))
        finally:
            conn.close()

    if needs_db.exists():
        conn = sqlite3.connect(needs_db)
        try:
            seeds.extend(fetch_need_backlog_seed(conn, date_s))
        finally:
            conn.close()

    unique: dict[str, dict[str, Any]] = {}
    for seed in seeds:
        key = str(seed.get("source_key") or "").strip()
        if not key:
            continue
        existing = unique.get(key)
        if existing is None or int(seed.get("priority", 0)) > int(existing.get("priority", 0)):
            unique[key] = seed
    ordered = sorted(unique.values(), key=lambda x: (-int(x.get("priority", 0)), str(x.get("title", ""))))
    return ordered


def build_prompt_payload(date_s: str, window_days: int, seeds: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "date": date_s,
        "window_days": window_days,
        "constraints": {
            "no_new_facts": True,
            "unknown_if_unsure": True,
            "do_not_invent_sources": True,
            "no_issue_creation": True,
        },
        "seed_candidates": [
            {
                "source_key": s["source_key"],
                "title": s["title"],
                "category": s["category"],
                "source": s["source"],
                "description": s["description"],
                "impact_score": s["impact_score"],
                "effort_score": s["effort_score"],
                "priority": s["priority"],
                "status": s["status"],
                "evidence": s["evidence"],
            }
            for s in seeds
        ],
    }


def build_prompt_text(payload: dict[str, Any]) -> str:
    return (
        "あなたは workSpace の改善監査官です。新規事実を作らず、入力の範囲だけで改善候補を整理してください。\n"
        "売買判断はしません。Issue はまだ起票しません。\n"
        "出力は必ず JSON のみ。Markdown や説明文は不要です。\n"
        "JSON 形式:\n"
        "{\n"
        '  "summary": "週次の要点を1-3文で",\n'
        '  "top_candidates": [\n'
        "    {\n"
        '      "source_key": "input の source_key をそのまま使う",\n'
        '      "title": "短い改善タイトル",\n'
        '      "category": "ops|delivery|pipeline|analysis|needs|other",\n'
        '      "source": "入力の source をそのまま使う",\n'
        '      "description": "何が起きているかを短く",\n'
        '      "impact_score": 0-100,\n'
        '      "effort_score": 0-100,\n'
        '      "priority": 0-100,\n'
        '      "status": "open"\n'
        "    }\n"
        "  ],\n"
        '  "duplicates": ["重複している source_key があれば列挙"],\n'
        '  "trend_notes": ["傾向や再発条件を短く"],\n'
        '  "next_checks": ["翌週までに確認したい観点を3件まで"]\n'
        "}\n"
        "制約:\n"
        "- top_candidates は最大10件\n"
        "- 返す候補は seed_candidates の source_key に一致するものだけ\n"
        "- 不明は不明と書く\n"
        "- 数値は 0-100 の整数\n"
        "- priority は impact を高く、effort を低く見た相対評価\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def parse_top_candidates(text: str, seeds_by_key: dict[str, dict[str, Any]]) -> dict[str, Any]:
    parsed = _parse_json_text(text)
    if not parsed:
        return {}
    items = parsed.get("top_candidates")
    if not isinstance(items, list):
        parsed["top_candidates"] = []
        return parsed
    normalized: list[dict[str, Any]] = []
    for item in items[:10]:
        if not isinstance(item, dict):
            continue
        key = str(item.get("source_key") or "").strip()
        if key not in seeds_by_key:
            continue
        seed = seeds_by_key[key]
        normalized.append(
            {
                "source_key": key,
                "title": str(item.get("title") or seed["title"]).strip(),
                "category": str(item.get("category") or seed["category"]).strip(),
                "source": str(item.get("source") or seed["source"]).strip(),
                "description": str(item.get("description") or seed["description"]).strip(),
                "impact_score": int(item.get("impact_score") or seed["impact_score"]),
                "effort_score": int(item.get("effort_score") or seed["effort_score"]),
                "priority": int(item.get("priority") or seed["priority"]),
                "status": str(item.get("status") or "open").strip() or "open",
                "evidence": seed["evidence"],
            }
        )
    parsed["top_candidates"] = normalized
    return parsed


def fallback_audit(seeds: list[dict[str, Any]]) -> dict[str, Any]:
    top = []
    for seed in seeds[:10]:
        top.append(
            {
                "source_key": seed["source_key"],
                "title": seed["title"],
                "category": seed["category"],
                "source": seed["source"],
                "description": seed["description"],
                "impact_score": int(seed["impact_score"]),
                "effort_score": int(seed["effort_score"]),
                "priority": int(seed["priority"]),
                "status": seed["status"],
                "evidence": seed["evidence"],
            }
        )
    return {
        "summary": "AI 出力の解析に失敗したため、ヒューリスティック候補を採用した。",
        "top_candidates": top,
        "duplicates": [],
        "trend_notes": ["AI 出力解析失敗のため、候補は機械抽出を優先"],
        "next_checks": ["週次監査 JSON 出力の整形を確認"],
    }


def save_run(conn: sqlite3.Connection, date_s: str, window_days: int, provider: str, model: str, summary: dict[str, Any], report_text: str, raw_text: str) -> None:
    conn.execute(
        """
        INSERT INTO improvement_audit_runs(
          audit_date, window_days, model_provider, model_name, summary_json, report_text, raw_json, created_at
        )
        VALUES(?,?,?,?,?,?,?,datetime('now'))
        ON CONFLICT(audit_date) DO UPDATE SET
          window_days=excluded.window_days,
          model_provider=excluded.model_provider,
          model_name=excluded.model_name,
          summary_json=excluded.summary_json,
          report_text=excluded.report_text,
          raw_json=excluded.raw_json,
          created_at=excluded.created_at
        """,
        (
            date_s,
            window_days,
            provider,
            model,
            json.dumps(summary, ensure_ascii=False),
            report_text,
            raw_text,
        ),
    )


def upsert_candidates(conn: sqlite3.Connection, date_s: str, candidates: list[dict[str, Any]]) -> int:
    rows = 0
    for item in candidates:
        evidence = item.get("evidence") or {}
        conn.execute(
            """
            INSERT INTO improvement_candidate(
              candidate_date, source_key, title, category, source, description,
              impact_score, effort_score, priority, status, evidence_json, created_at, updated_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))
            ON CONFLICT(candidate_date, source_key) DO UPDATE SET
              title=excluded.title,
              category=excluded.category,
              source=excluded.source,
              description=excluded.description,
              impact_score=excluded.impact_score,
              effort_score=excluded.effort_score,
              priority=excluded.priority,
              status=excluded.status,
              evidence_json=excluded.evidence_json,
              created_at=improvement_candidate.created_at,
              updated_at=excluded.updated_at
            """,
            (
                date_s,
                item["source_key"],
                item["title"],
                item["category"],
                item["source"],
                item["description"],
                int(item.get("impact_score", 0)),
                int(item.get("effort_score", 0)),
                int(item.get("priority", 0)),
                item.get("status", "open"),
                json.dumps(evidence, ensure_ascii=False),
            ),
        )
        rows += 1
    return rows


def render_markdown(date_s: str, audit: dict[str, Any], candidates: list[dict[str, Any]], payload: dict[str, Any]) -> str:
    lines = [
        f"# {date_s} improvement audit",
        "",
        f"- window_days: {payload['window_days']}",
        f"- candidate_count: {len(candidates)}",
        "",
        "## Summary",
        str(audit.get("summary") or "不明"),
        "",
        "## Top Candidates",
    ]
    for item in candidates[:10]:
        lines.extend(
            [
                f"- {item['title']} [{item['category']}]",
                f"  - source: {item['source']}",
                f"  - priority: {item['priority']} / impact: {item['impact_score']} / effort: {item['effort_score']}",
                f"  - source_key: {item['source_key']}",
                f"  - description: {item['description']}",
            ]
        )
    if audit.get("duplicates"):
        lines.append("")
        lines.append("## Duplicates")
        for dup in audit.get("duplicates", []):
            lines.append(f"- {dup}")
    if audit.get("trend_notes"):
        lines.append("")
        lines.append("## Trend Notes")
        for note in audit.get("trend_notes", []):
            lines.append(f"- {note}")
    if audit.get("next_checks"):
        lines.append("")
        lines.append("## Next Checks")
        for note in audit.get("next_checks", []):
            lines.append(f"- {note}")
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    args = parse_args()
    load_dotenv()

    provider, model = resolve_model(args.model_route)
    if provider != "openai":
        print(f"skip: provider unsupported {provider}")
        return 0

    seeds = build_seed_list(args.ops_db, args.investment_db, args.needs_db, args.date, args.window_days)
    if not seeds:
        print("skip: no audit seeds")
        return 0
    candidate_limit = max(1, min(int(args.topn or 10), 10))
    seed_limit = max(20, candidate_limit * 2)
    seeds = seeds[:seed_limit]
    seeds_by_key = {str(seed["source_key"]): seed for seed in seeds}
    payload = build_prompt_payload(args.date, args.window_days, seeds)

    text, raw = call_openai_text(
        model=model,
        system_text="あなたは workSpace の改善監査官です。推測はせず、入力された情報だけで候補を整理します。",
        user_text=build_prompt_text(payload),
    )
    audit = parse_top_candidates(text, seeds_by_key)
    if not audit:
        audit = fallback_audit(seeds)

    selected_candidates = audit.get("top_candidates", [])
    if not isinstance(selected_candidates, list):
        selected_candidates = []
    if not selected_candidates:
        selected_candidates = fallback_audit(seeds)["top_candidates"]
    selected_candidates = selected_candidates[:candidate_limit]
    report_text = render_markdown(args.date, audit, selected_candidates, payload)
    raw_json = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)

    conn = sqlite3.connect(args.ops_db)
    try:
        conn.execute("DELETE FROM improvement_candidate WHERE candidate_date=?", (args.date,))
        save_run(conn, args.date, args.window_days, provider, model, audit, report_text, raw_json)
        inserted = upsert_candidates(conn, args.date, selected_candidates)
        conn.commit()
    finally:
        conn.close()
    print(f"saved: ops.db improvement_audit_runs {args.date}")
    print(f"saved: ops.db improvement_candidate {len(selected_candidates)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
