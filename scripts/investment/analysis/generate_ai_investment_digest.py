#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
import sys
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.platform_core_bootstrap import ensure_platform_core_importable

ensure_platform_core_importable()
from utils.investment_db_path import resolve_investment_db
from platform_core.model_router import resolve_model
from platform_core.openai_client import call_openai_text

DEFAULT_DB = resolve_investment_db()
DEFAULT_OUT = ROOT / "prompts" / "ai-investment-digest.txt"
DEFAULT_JSON = ROOT / "prompts" / "ai-investment-digest.json"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate AI investment digest from DB and write Discord-ready text.")
    p.add_argument("--date", default=date.today().isoformat(), help="Target date (YYYY-MM-DD)")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--out-json", type=Path, default=DEFAULT_JSON)
    p.add_argument("--model", default="", help="Optional explicit model override.")
    p.add_argument("--model-route", default="investment_digest")
    p.add_argument("--dry-run", action="store_true")
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
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def fetch_stats(conn: sqlite3.Connection, target_date: str) -> dict:
    def one(sql: str, params: tuple = ()) -> int:
        row = conn.execute(sql, params).fetchone()
        return int(row[0] or 0) if row else 0

    def rows(sql: str, params: tuple = ()) -> list[dict]:
        out: list[dict] = []
        for r in conn.execute(sql, params).fetchall():
            out.append(dict(r))
        return out

    stats = {
        "date": target_date,
        "signals_total": one("SELECT COUNT(*) FROM signals WHERE date=?", (target_date,)),
        "entry_candidates_total": one("SELECT COUNT(*) FROM entry_candidates WHERE date=?", (target_date,)),
        "open_trades_total": one("SELECT COUNT(*) FROM paper_trades WHERE status='open'"),
        "gate_summary": rows(
            """
            SELECT COALESCE(gate_status,'unknown') AS gate_status, COUNT(*) AS cnt
            FROM signals
            WHERE date=?
            GROUP BY COALESCE(gate_status,'unknown')
            ORDER BY cnt DESC
            """,
            (target_date,),
        ),
        "long_top": rows(
            """
            SELECT ticker, company, score, candidate_type, signal_id
            FROM entry_candidates
            WHERE date=? AND side='long'
            ORDER BY COALESCE(score, -999) DESC, ticker
            LIMIT 5
            """,
            (target_date,),
        ),
        "short_top": rows(
            """
            SELECT ticker, company, score, candidate_type, signal_id
            FROM entry_candidates
            WHERE date=? AND side='short'
            ORDER BY COALESCE(score, -999) DESC, ticker
            LIMIT 5
            """,
            (target_date,),
        ),
        "scenario_promote_long": rows(
            """
            SELECT ticker, company, score, signal_id, gate_status
            FROM entry_candidates
            WHERE date=? AND side='long' AND candidate_type='primary'
              AND COALESCE(score,0) >= 8
              AND LOWER(COALESCE(gate_status,'')) IN ('pass','')
            ORDER BY COALESCE(score, -999) DESC, ticker
            LIMIT 5
            """,
            (target_date,),
        ),
        "scenario_promote_short": rows(
            """
            SELECT ticker, company, score, signal_id, gate_status
            FROM entry_candidates
            WHERE date=? AND side='short' AND candidate_type='primary'
              AND COALESCE(score,0) >= 8
              AND LOWER(COALESCE(gate_status,'')) IN ('pass','')
            ORDER BY COALESCE(score, -999) DESC, ticker
            LIMIT 5
            """,
            (target_date,),
        ),
    }
    return stats


def build_user_prompt(stats: dict) -> str:
    payload = json.dumps(stats, ensure_ascii=False, indent=2)
    return (
        "以下は investment.db から抽出した当日スナップショットです。\n"
        "売買助言はせず、運用者向けの分析結果を日本語で作成してください。\n"
        "出力形式:\n"
        "1) 本日の分析サマリ（4行以内）\n"
        "2) シグナル品質分析（ロング/ショートの偏り、gate傾向、注意点）\n"
        "3) シナリオ昇格候補（long/short 最大3件ずつ、理由付き）\n"
        "4) 昇格見送り候補（最大3件、見送り理由を明記）\n"
        "5) 次アクション（明日までに確認すべき分析タスク2-4件）\n\n"
        f"{payload}"
    )


def make_dry_run_message(stats: dict) -> str:
    long_items = [f"- {r.get('ticker')}: score={r.get('score')}" for r in stats.get("long_top", [])[:3]]
    short_items = [f"- {r.get('ticker')}: score={r.get('score')}" for r in stats.get("short_top", [])[:3]]
    gates = ", ".join(f"{g['gate_status']}={g['cnt']}" for g in stats.get("gate_summary", [])) or "none"
    lines = [
        f"[DRY RUN] AI Investment Digest {stats['date']}",
        "",
        "1) 本日の分析サマリ",
        f"- signals={stats['signals_total']}, candidates={stats['entry_candidates_total']}, openTrades={stats['open_trades_total']}",
        f"- gate: {gates}",
        "",
        "2) シグナル品質分析",
        "- gate_statusと候補件数の偏りを確認する想定",
        "",
        "3) シナリオ昇格候補",
        *(long_items or ["- なし"]),
        "",
        *(short_items or ["- なし"]),
        "",
        "4) 昇格見送り候補",
        "- DRY RUNのため見送り分析は未生成",
        "",
        "5) 次アクション",
        "- 昇格候補の根拠データ（signal/gate/score）を点検",
        "- opening_scenarios への反映ルール妥当性を確認",
        "",
        "補助情報: 注目ショート候補",
        *(short_items or ["- なし"]),
    ]
    return "\n".join(lines).strip() + "\n"


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def save_digest_to_db(db_path: Path, target_date: str, text: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO daily_digest(topic,date,path,summary,updated_at)
            VALUES(?,?,?,?,datetime('now'))
            ON CONFLICT(topic,date) DO UPDATE SET
              path=excluded.path,
              summary=excluded.summary,
              updated_at=excluded.updated_at
            """,
            ("ai-investment-digest", target_date, "db:daily_digest:ai-investment-digest", text),
        )
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    args = parse_args()
    load_dotenv()
    if not args.db.exists():
        raise SystemExit(f"DB not found: {args.db}")

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    stats = fetch_stats(conn, args.date)
    conn.close()

    provider, route_model = resolve_model(args.model_route)
    model = args.model.strip() or route_model
    if provider != "openai":
        raise SystemExit(f"unsupported provider for this script: {provider}")

    if args.dry_run:
        digest_text = make_dry_run_message(stats)
        raw_response: dict = {"mode": "dry-run"}
    else:
        digest_text, raw_response = call_openai_text(
            model=model,
            system_text="あなたは投資情報の運用アナリストです。簡潔で実務的に、材料整理のみを返してください。",
            user_text=build_user_prompt(stats),
        )

    final_text = f"AsOf: {datetime.now().strftime('%Y-%m-%d %H:%M')} JST\n{digest_text.strip()}\n"
    db_saved = False
    try:
        save_digest_to_db(args.db, args.date, final_text)
        db_saved = True
        print(f"saved_to_db: {args.db} topic=ai-investment-digest date={args.date}")
    except Exception as e:
        print(f"[warn] db_save_failed: {e}")

    if not db_saved:
        ensure_parent(args.out)
        args.out.write_text(final_text, encoding="utf-8")
        ensure_parent(args.out_json)
        args.out_json.write_text(
            json.dumps(
                {
                    "date": args.date,
                    "dry_run": bool(args.dry_run),
                    "model": model,
                    "provider": provider,
                    "stats": stats,
                    "response": raw_response,
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "fallback": "file",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"fallback_written: {args.out}")
        print(f"fallback_written: {args.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
