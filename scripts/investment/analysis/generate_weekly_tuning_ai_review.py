#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.platform_core_bootstrap import ensure_platform_core_importable

ensure_platform_core_importable()
from utils.investment_db_path import resolve_investment_db
from platform_core.model_router import resolve_model
from platform_core.openai_client import call_openai_text

DEFAULT_DB = resolve_investment_db()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AI weekly tuning review from DB artifacts")
    p.add_argument("--date", required=True)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--model-route", default="weekly_tuning_ai_review")
    return p.parse_args()


def load_artifact(conn: sqlite3.Connection, key: str, date_s: str) -> dict:
    row = conn.execute(
        """
        SELECT payload_json FROM collection_artifacts
        WHERE artifact_key=? AND artifact_date=?
        ORDER BY updated_at DESC LIMIT 1
        """,
        (key, date_s),
    ).fetchone()
    if not row or not row[0]:
        return {}
    try:
        return json.loads(str(row[0]))
    except Exception:
        return {}


def main() -> int:
    args = parse_args()
    provider, model = resolve_model(args.model_route)
    if provider != "openai":
        print(f"skip: provider unsupported {provider}")
        return 0
    conn = sqlite3.connect(args.db)
    try:
        weekly = load_artifact(conn, "weekly_tuning_review", args.date)
        kpi = load_artifact(conn, "signal_pipeline_kpi", args.date)
        if not weekly and not kpi:
            print("skip: no weekly artifacts")
            return 0
        prompt_payload = {"date": args.date, "weekly_tuning_review": weekly, "signal_pipeline_kpi": kpi}
        text, raw = call_openai_text(
            model=model,
            system_text="あなたは投資運用の改善レビュー担当。売買助言は禁止。",
            user_text=(
                "週次チューニングのレビューを作成してください。"
                "1) 先週の要点 2) ボトルネック 3) 次週の実験タスク(3件まで) を短く。"
                f"\n\n{json.dumps(prompt_payload, ensure_ascii=False, indent=2)}"
            ),
        )
        out = {"date": args.date, "provider": provider, "model": model, "review": text, "raw": raw}
        conn.execute(
            """
            INSERT INTO collection_artifacts(artifact_key,artifact_date,artifact_type,payload_json,updated_at)
            VALUES(?,?,?,?,datetime('now'))
            ON CONFLICT(artifact_key,artifact_date) DO UPDATE SET
              payload_json=excluded.payload_json,
              updated_at=excluded.updated_at
            """,
            ("weekly_tuning_ai_review", args.date, "ai_review", json.dumps(out, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()
    print(f"saved: collection_artifacts weekly_tuning_ai_review {args.date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
