#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "prompts"
DEFAULT_DB = ROOT / "data" / "investment.db"


def direction_ja(v: str) -> str:
    return {
        "long": "ロング",
        "short": "ショート",
        "up": "上昇",
        "down": "下落",
    }.get((v or "").strip(), v or "")


def hold_days_ja(v: str) -> str:
    x = (v or "").strip().upper()
    if x == "T+1":
        return "1営業日程度"
    if x == "T+5":
        return "3-5営業日程度"
    if x == "T+20":
        return "10-20営業日程度"
    return "未定（短期監視）"


def invalidation_ja(row: dict) -> str:
    skips = row.get("skipConditions", []) or []
    if skips:
        return str(skips[0])
    return str(row.get("invalidationCondition", "") or "前提が崩れた場合は見送り/撤退")


def rationale_ja(row: dict) -> str:
    trigger = str(row.get("trigger", "") or "")
    repro = str(row.get("ruleReproducibility", "") or "")
    wr = str(row.get("estimatedWinRate", "") or "")
    status = str(row.get("ruleStatus", "") or "")
    parts = [p for p in [trigger, repro, f"ruleStatus={status}" if status else "", wr] if p]
    return " / ".join(parts) if parts else "根拠情報不足"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render opening scenarios into Discord-ready message text")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    return p.parse_args()


def load_rows_from_db(db_path: Path, date_str: str) -> list[dict]:
    if not db_path.exists():
        raise SystemExit(f"db not found: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT scenario_index,ticker,company,direction,scenario_tier,scenario_score,rule_hit_count,
                   estimated_winrate_text
            FROM opening_scenarios
            WHERE scenario_date=? AND source_kind='scenario'
            ORDER BY scenario_index
            """,
            (date_str,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        raise SystemExit(f"opening_scenarios not found in DB for {date_str}")
    return [dict(r) for r in rows]


def build_message(date: str, rows: list[dict]) -> str:
    lines = [
        f"寄り付きシナリオ {date}",
        f"- 参照日: {date}",
        f"- 件数: {len(rows)}",
        "",
    ]
    if not rows:
        lines.append("- 変化なし（N/C）")
        return "\n".join(lines)

    for i, r in enumerate(rows, 1):
        lines.extend(
            [
                f"{i}. {r.get('ticker','')} {r.get('company','')} [{direction_ja(r.get('direction',''))}]",
                f"  方向: {direction_ja(r.get('direction',''))}",
                f"  品質: score={r.get('scenario_score',0)} / ruleHits={r.get('rule_hit_count',0)} / {r.get('estimated_winrate_text','')}",
                f"  補足: 種別={r.get('scenario_tier','trade')}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    rows = load_rows_from_db(args.db, args.date)
    message = build_message(args.date, rows)

    out_txt = OUT_DIR / "opening-scenarios-discord-message.txt"
    out_md = OUT_DIR / "opening-scenarios-discord-message.md"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_txt.write_text(message, encoding="utf-8")
    out_md.write_text("```text\n" + message + "```\n", encoding="utf-8")
    print(f"wrote {out_txt.relative_to(ROOT)}")
    print(f"wrote {out_md.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
