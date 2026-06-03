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
    p = argparse.ArgumentParser(description="AI review for scenario promotion candidates")
    p.add_argument("--date", required=True)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--model-route", default="scenario_promotion_review")
    p.add_argument("--topn", type=int, default=10)
    return p.parse_args()


def fetch_candidates(conn: sqlite3.Connection, date_s: str, topn: int) -> list[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT side,ticker,company,score,gate_status,candidate_type,signal_id
        FROM entry_candidates
        WHERE date=? AND candidate_type='primary'
        ORDER BY COALESCE(score,-999) DESC, side, ticker
        LIMIT ?
        """,
        (date_s, topn),
    ).fetchall()
    return [dict(r) for r in rows]


def save_artifact(conn: sqlite3.Connection, date_s: str, payload: dict) -> None:
    conn.execute(
        """
        INSERT INTO collection_artifacts(artifact_key,artifact_date,artifact_type,payload_json,updated_at)
        VALUES(?,?,?,?,datetime('now'))
        ON CONFLICT(artifact_key,artifact_date) DO UPDATE SET
          payload_json=excluded.payload_json,
          updated_at=excluded.updated_at
        """,
        ("scenario_promotion_ai_review", date_s, "ai_review", json.dumps(payload, ensure_ascii=False)),
    )


def main() -> int:
    args = parse_args()
    provider, model = resolve_model(args.model_route)
    if provider != "openai":
        print(f"skip: provider unsupported {provider}")
        return 0
    conn = sqlite3.connect(args.db)
    try:
        cands = fetch_candidates(conn, args.date, args.topn)
        if not cands:
            print("skip: no primary candidates")
            return 0
        user_payload = json.dumps({"date": args.date, "candidates": cands}, ensure_ascii=False, indent=2)
        text, raw = call_openai_text(
            model=model,
            system_text="あなたは投資運用のシナリオ審査担当。売買助言は禁止。昇格判断の説明のみ。",
            user_text=(
                "以下の候補について、昇格優先(最大3)と見送り(最大3)を出し、理由を短く示してください。"
                "出力は日本語、箇条書き。"
                f"\n\n{user_payload}"
            ),
        )
        payload = {"date": args.date, "provider": provider, "model": model, "review": text, "raw": raw}
        save_artifact(conn, args.date, payload)
        conn.commit()
    finally:
        conn.close()
    print(f"saved: collection_artifacts scenario_promotion_ai_review {args.date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
