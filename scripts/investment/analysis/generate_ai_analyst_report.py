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
from utils.ai_model_router import resolve_model
from utils.openai_responses import call_openai_text

DEFAULT_DB = ROOT / "data" / "investment.db"
ARTIFACT_KEY = "ai_analyst_report"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate AI analyst report for scenario review")
    p.add_argument("--date", required=True)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--model-route", default="ai_analyst_report")
    p.add_argument("--long-n", type=int, default=3)
    p.add_argument("--short-n", type=int, default=3)
    p.add_argument("--watch-n", type=int, default=3)
    return p.parse_args()


def fetch_rows(conn: sqlite3.Connection, date_s: str, side: str, ctype: str, limit: int) -> list[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT ec.ticker, ec.company, ec.score, ec.gate_status, ec.signal_id, ec.url,
               s.signal_type, s.expected_direction, s.long_rank, s.short_rank,
               (
                 SELECT sc.sector_group FROM sector_context_rows sc
                 WHERE sc.ticker=ec.ticker
                 ORDER BY sc.date DESC LIMIT 1
               ) AS sector_group
        FROM entry_candidates ec
        LEFT JOIN signals s ON s.date=ec.date AND s.signal_id=ec.signal_id
        WHERE ec.date=? AND ec.side=? AND ec.candidate_type=?
        ORDER BY COALESCE(ec.score,-999) DESC, ec.ticker
        LIMIT ?
        """,
        (date_s, side, ctype, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_paper_stats(conn: sqlite3.Connection, date_s: str) -> dict:
    row = conn.execute(
        """
        SELECT
          SUM(CASE WHEN t5_return_pct IS NOT NULL THEN 1 ELSE 0 END) AS t5_n,
          AVG(t5_return_pct) AS t5_avg,
          AVG(CASE WHEN t5_return_pct > 0 THEN 1.0 ELSE 0.0 END) AS t5_wr
        FROM paper_trades
        WHERE entry_date<=?
        """,
        (date_s,),
    ).fetchone()
    if not row:
        return {"t5_n": 0, "t5_avg": None, "t5_wr": None}
    t5_n = int(row[0] or 0)
    t5_avg = float(row[1]) if row[1] is not None else None
    t5_wr = float(row[2]) * 100.0 if row[2] is not None else None
    return {"t5_n": t5_n, "t5_avg": t5_avg, "t5_wr": t5_wr}


def save_artifact(conn: sqlite3.Connection, date_s: str, payload: dict) -> None:
    conn.execute(
        """
        INSERT INTO collection_artifacts(artifact_key,artifact_date,artifact_type,payload_json,updated_at)
        VALUES(?,?,?,?,datetime('now'))
        ON CONFLICT(artifact_key,artifact_date) DO UPDATE SET
          payload_json=excluded.payload_json,
          updated_at=excluded.updated_at
        """,
        (ARTIFACT_KEY, date_s, "ai_analysis", json.dumps(payload, ensure_ascii=False)),
    )


def main() -> int:
    args = parse_args()
    provider, model = resolve_model(args.model_route)
    if provider != "openai":
        print(f"skip: provider unsupported {provider}")
        return 0
    conn = sqlite3.connect(args.db)
    try:
        long_rows = fetch_rows(conn, args.date, "long", "primary", args.long_n)
        short_rows = fetch_rows(conn, args.date, "short", "primary", args.short_n)
        watch_rows = fetch_rows(conn, args.date, "long", "watch", args.watch_n // 2 + args.watch_n % 2)
        watch_rows += fetch_rows(conn, args.date, "short", "watch", args.watch_n // 2)
        watch_rows = watch_rows[: args.watch_n]
        stats = fetch_paper_stats(conn, args.date)

        payload = {
            "date": args.date,
            "long": long_rows,
            "short": short_rows,
            "watch": watch_rows,
            "paper_trade_stats": stats,
            "constraints": {
                "no_new_facts": True,
                "unknown_if_unsure": True,
                "no_order_advice": True,
                "no_estimate_without_data": True,
            },
        }
        user_text = (
            "以下のDB情報のみを根拠に、投資分析官レポートを作成してください。\n"
            "売買推奨、発注指示、ロット判断は禁止。\n"
            "強気シナリオ/弱気シナリオ/見送り理由/追加確認ポイント/リスク警告を整理し、"
            "不明点は必ず「不明」と書いてください。\n"
            "勝率や期待値は入力の機械集計値がある場合のみ記載可。\n\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )
        text, raw = call_openai_text(
            model=model,
            system_text="あなたは投資助言者ではなく、情報整理担当の分析官です。",
            user_text=user_text,
        )
        out = {
            "date": args.date,
            "provider": provider,
            "model": model,
            "report": text,
            "input_snapshot": payload,
            "raw": raw,
        }
        save_artifact(conn, args.date, out)
        conn.commit()
    finally:
        conn.close()
    print(f"saved: collection_artifacts {ARTIFACT_KEY} {args.date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
