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


def clean_company_name(v: str) -> str:
    s = (v or "").strip()
    if not s:
        return ""
    # Remove accidental direction labels mixed into company text.
    s = s.replace("ロング", "").replace("ショート", "")
    s = s.replace("[", " ").replace("]", " ")
    s = " ".join(s.split()).strip()
    return s


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
            SELECT os.scenario_index,os.ticker,
                   COALESCE(
                     NULLIF(TRIM(os.company),''),
                     (
                       SELECT NULLIF(TRIM(s.company),'') FROM signals s
                       WHERE s.ticker=os.ticker
                       ORDER BY s.date DESC, s.signal_id DESC LIMIT 1
                     ),
                     (
                       SELECT NULLIF(TRIM(t.company),'') FROM tdnet_disclosures t
                       WHERE t.ticker=os.ticker AND COALESCE(NULLIF(TRIM(t.company),''),'')<>''
                       ORDER BY t.date DESC, t.disclosed_at DESC LIMIT 1
                     ),
                     (
                       SELECT NULLIF(TRIM(i.name),'') FROM instruments i
                       WHERE i.ticker=os.ticker
                       LIMIT 1
                     ),
                     ''
                   ) AS company,
                   os.direction,os.scenario_tier,os.scenario_score,os.rule_hit_count,
                   os.estimated_winrate_text,
                   (
                     SELECT sc.sector_group FROM sector_context_rows sc
                     WHERE sc.ticker=os.ticker
                     ORDER BY sc.date DESC LIMIT 1
                   ) AS sector_group
            FROM opening_scenarios os
            WHERE os.scenario_date=? AND os.source_kind='scenario'
            ORDER BY scenario_index
            """,
            (date_str,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def load_zero_case_stats(db_path: Path, date_str: str) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    try:
        trade_count = conn.execute(
            "SELECT COUNT(*) FROM opening_scenarios WHERE scenario_date=? AND source_kind='scenario'",
            (date_str,),
        ).fetchone()[0]
        rejected_count = conn.execute(
            "SELECT COUNT(*) FROM opening_scenarios WHERE scenario_date=? AND source_kind='rejected'",
            (date_str,),
        ).fetchone()[0]
        candidate_count = conn.execute(
            "SELECT COUNT(*) FROM entry_candidates WHERE date=?",
            (date_str,),
        ).fetchone()[0]
        execution_count = conn.execute(
            "SELECT COUNT(*) FROM execution_plan WHERE plan_date=?",
            (date_str,),
        ).fetchone()[0]
    finally:
        conn.close()
    return {
        "trade_count": int(trade_count or 0),
        "rejected_count": int(rejected_count or 0),
        "candidate_count": int(candidate_count or 0),
        "execution_count": int(execution_count or 0),
    }


def gate_ja(v: str) -> str:
    s = (v or "").strip().lower()
    return {
        "hold_credit_unknown": "信用可否未確認",
        "hold_borrow_unknown": "売建可否未確認",
        "hold_non_marginable": "信用対象外",
        "pass": "通過",
    }.get(s, (v or "判定不明"))


def load_rejected_rows_from_db(db_path: Path, date_str: str, limit: int = 8) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT os.ticker,
                   COALESCE(
                     NULLIF(TRIM(os.company),''),
                     (
                       SELECT NULLIF(TRIM(s.company),'') FROM signals s
                       WHERE s.ticker=os.ticker
                       ORDER BY s.date DESC, s.signal_id DESC LIMIT 1
                     ),
                     (
                       SELECT NULLIF(TRIM(t.company),'') FROM tdnet_disclosures t
                       WHERE t.ticker=os.ticker AND COALESCE(NULLIF(TRIM(t.company),''),'')<>''
                       ORDER BY t.date DESC, t.disclosed_at DESC LIMIT 1
                     ),
                     (
                       SELECT NULLIF(TRIM(i.name),'') FROM instruments i
                       WHERE i.ticker=os.ticker
                       LIMIT 1
                     ),
                     ''
                   ) AS company,
                   os.direction, os.scenario_score, os.rule_hit_count, os.estimated_winrate_text,
                   (
                     SELECT s.gate_status FROM signals s
                     WHERE s.date=? AND s.ticker=os.ticker
                     ORDER BY s.signal_id DESC LIMIT 1
                   ) AS gate_status
            FROM opening_scenarios os
            WHERE os.scenario_date=? AND os.source_kind='rejected'
            ORDER BY COALESCE(os.scenario_score, -9999) DESC, os.scenario_index
            LIMIT ?
            """,
            (date_str, date_str, limit),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def build_message(date: str, rows: list[dict], zero_case_stats: dict[str, int], rejected_rows: list[dict]) -> str:
    lines = [
        f"寄り付きシナリオ {date}",
        f"- 参照日: {date}",
        f"- 件数: {len(rows)}",
        "",
    ]
    if not rows:
        lines.append("- 変化なし（N/C）")
        lines.append(
            f"- 内訳: 候補={zero_case_stats.get('candidate_count',0)} / trade採用={zero_case_stats.get('trade_count',0)} / watch判定={zero_case_stats.get('rejected_count',0)} / 実行計画={zero_case_stats.get('execution_count',0)}"
        )
        lines.extend(
            [
                "",
                "返信対象（watch/保留）:",
            ]
        )
        if rejected_rows:
            for i, r in enumerate(rejected_rows, 1):
                lines.append(
                    f"{i}. {r.get('ticker','')} {clean_company_name(r.get('company','')) or '不明'} [{direction_ja(r.get('direction',''))}] / {gate_ja(r.get('gate_status',''))}"
                )
        else:
            lines.append("- 該当なし")
        lines.extend(
            [
                "",
                "返信コマンド例:",
                "- entry 100 4022 / entry lots=100 price=4022",
                "- exit tp 4070 / exit reason=sl / cancel",
                "- credit ng|ok|unknown",
                "",
            ]
        )
        return "\n".join(lines)

    for i, r in enumerate(rows, 1):
        sector = (r.get("sector_group", "") or "不明").strip() or "不明"
        company = clean_company_name(r.get("company", "")) or "不明"
        lines.extend(
            [
                f"{i}. {r.get('ticker','')} {company} ({sector}) [{direction_ja(r.get('direction',''))}]",
                f"  方向: {direction_ja(r.get('direction',''))}",
                f"  品質: score={r.get('scenario_score',0)} / ruleHits={r.get('rule_hit_count',0)} / {r.get('estimated_winrate_text','')}",
                f"  補足: 種別={r.get('scenario_tier','trade')}",
                "",
            ]
        )
    lines.extend(
        [
            "返信対象（watch/保留）:",
        ]
    )
    if rejected_rows:
        for i, r in enumerate(rejected_rows, 1):
            lines.append(
                f"{i}. {r.get('ticker','')} {clean_company_name(r.get('company','')) or '不明'} [{direction_ja(r.get('direction',''))}] / {gate_ja(r.get('gate_status',''))}"
            )
    else:
        lines.append("- 該当なし")
    lines.extend(
        [
            "",
            "返信コマンド例:",
            "- entry 100 4022 / entry lots=100 price=4022",
            "- exit tp 4070 / exit reason=sl / cancel",
            "- credit ng|ok|unknown",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    rows = load_rows_from_db(args.db, args.date)
    zero_case_stats = load_zero_case_stats(args.db, args.date)
    rejected_rows = load_rejected_rows_from_db(args.db, args.date, limit=8)
    message = build_message(args.date, rows, zero_case_stats, rejected_rows)

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
