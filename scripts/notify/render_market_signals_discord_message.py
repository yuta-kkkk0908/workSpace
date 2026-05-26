#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "prompts"
DEFAULT_DB = ROOT / "data" / "investment.db"


def expected_direction_ja(v: str) -> str:
    return {
        "up": "上昇",
        "up_watch": "上昇監視",
        "down": "下落",
        "down_watch": "下落監視",
        "neutral": "中立",
        "unknown": "不明",
    }.get((v or "").strip(), v or "")


def rank_ja(v: str) -> str:
    s = (v or "").strip()
    if not s:
        return "不明"
    if s.lower() == "none":
        return "該当なし"
    if s.lower() == "unknown":
        return "不明"
    return s


def signal_type_ja(v: str) -> str:
    mapping = {
        "self_buyback": "自社株買い",
        "earnings_positive": "好決算",
        "earnings_negative": "悪決算",
        "technical_breakout": "テクニカル上放れ",
        "technical_breakdown": "テクニカル下放れ",
        "rebound_long_candidate": "押し目ロング候補",
        "rebound_short_candidate": "戻り売りショート候補",
        "news_material": "ニュース材料",
    }
    raw = (v or "").strip()
    if not raw or raw.lower() == "unknown":
        return ""
    parts = [p.strip() for p in re.split(r"\s*/\s*|\s*,\s*", raw) if p.strip()]
    if len(parts) <= 1:
        return mapping.get(raw, raw)
    return " / ".join(mapping.get(p, p) for p in parts)


def gate_ja(v: str) -> str:
    s = (v or "").lower()
    exact = {
        "hold_credit_unknown": "信用可否未確認（保留）",
        "hold_borrow_unknown": "売建可否未確認（保留）",
        "hold_non_marginable": "信用対象外（保留）",
        "pass": "通過",
        "fail": "非通過",
    }
    if s in exact:
        return exact[s]
    if "pass" in s:
        return "通過"
    if "fail" in s:
        return "非通過"
    if "hold" in s:
        return "要確認（保留）"
    if "watch" in s:
        return "監視"
    return v or ""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render market-signals into Discord-ready message text (DB-first)")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--slot", default="", help="optional scheduler slot (e.g. inv-noon)")
    return p.parse_args()


def load_signals_from_db(db_path: Path, date_str: str) -> list[dict[str, str]]:
    if not db_path.exists():
        raise SystemExit(f"db not found: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT s.signal_id,s.ticker,s.company,s.expected_direction,s.long_rank,s.short_rank,s.signal_type,s.url,s.source,s.gate_status,
                   s.material_signal_checked,s.external_context_checked,s.technical_signal_checked,
                   (
                     SELECT s2.company FROM signals s2
                     WHERE s2.ticker=s.ticker
                       AND s2.company IS NOT NULL
                       AND TRIM(s2.company) <> ''
                       AND LOWER(TRIM(s2.company)) <> 'unknown'
                       AND TRIM(s2.company) <> '不明'
                     ORDER BY s2.date DESC
                     LIMIT 1
                   ) AS company_fallback,
                   (
                     SELECT ep.company FROM execution_plan ep
                     WHERE ep.ticker=s.ticker
                       AND ep.company IS NOT NULL
                       AND TRIM(ep.company) <> ''
                     ORDER BY ep.plan_date DESC
                     LIMIT 1
                   ) AS company_from_plan,
                   (
                     SELECT ec.company FROM entry_candidates ec
                     WHERE ec.ticker=s.ticker
                       AND ec.company IS NOT NULL
                       AND TRIM(ec.company) <> ''
                     ORDER BY ec.date DESC
                     LIMIT 1
                   ) AS company_from_candidate,
                   (
                     SELECT sc.sector_group FROM sector_context_rows sc
                     WHERE sc.ticker=s.ticker
                     ORDER BY sc.date DESC LIMIT 1
                   ) AS sector_group,
                   (
                     SELECT sr.borrow_status FROM short_readiness_rows sr
                     WHERE sr.ticker=s.ticker
                     ORDER BY sr.date DESC LIMIT 1
                   ) AS borrow_status
            FROM signals s
            WHERE s.date=?
            ORDER BY signal_id
            """,
            (date_str,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def load_entry_candidates_from_db(db_path: Path, date_str: str, limit: int = 3) -> list[dict[str, str]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT ec.ticker, ec.company, ec.side, ec.score, ec.long_rank, ec.short_rank, ec.url,
                   (
                     SELECT sc.sector_group FROM sector_context_rows sc
                     WHERE sc.ticker=ec.ticker
                     ORDER BY sc.date DESC LIMIT 1
                   ) AS sector_group
            FROM entry_candidates ec
            WHERE ec.date=?
            ORDER BY COALESCE(ec.score, -9999) DESC, ec.updated_at DESC
            LIMIT ?
            """,
            (date_str, limit),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def is_non_marginable(borrow_status: str) -> bool:
    s = (borrow_status or "").strip().lower()
    if s == "manual_non_marginable":
        return True
    if s == "manual_marginable":
        return False
    if not s or s == "unknown":
        return False
    bad_tokens = ["不可", "対象外", "なし", "no", "ng", "×", "✕", "x"]
    return any(tok in s for tok in bad_tokens)


def sanitize_source_url(url: str, source: str = "") -> str:
    uu = (url or "").strip()
    if uu.startswith("http://") or uu.startswith("https://"):
        return uu
    ss = (source or "").strip()
    if ss.startswith("http://") or ss.startswith("https://"):
        return ss
    return "一次情報URL未設定"


def build_message(
    date_str: str,
    rows: list[dict[str, str]],
    slot: str = "",
    fallback_rows: list[dict[str, str]] | None = None,
) -> str:
    excluded_non_margin = 0
    excluded_rows: list[dict[str, str]] = []
    kept: list[dict[str, str]] = []
    for r in rows:
        if is_non_marginable(str(r.get("borrow_status", ""))):
            excluded_non_margin += 1
            excluded_rows.append(r)
            continue
        kept.append(r)
    rows = kept

    lines = [
        f"シグナル速報 {date_str}",
        f"- 参照日: {date_str}",
        f"- 件数: {len(rows)}",
        f"- 信用取引不可除外: {excluded_non_margin}件",
        "",
    ]
    if not rows:
        lines.append("- 変化なし（N/C）")
        if fallback_rows:
            lines.extend(
                [
                    "",
                    "補完候補（entry_candidates上位）:",
                ]
            )
            for i, r in enumerate(fallback_rows, 1):
                ticker = (r.get("ticker", "") or "").strip()
                company = (r.get("company", "") or "").strip()
                side = (r.get("side", "") or "").strip()
                score = r.get("score", None)
                sector = (r.get("sector_group", "") or "不明").strip() or "不明"
                lr = rank_ja(r.get("long_rank", ""))
                sr = rank_ja(r.get("short_rank", ""))
                source_url = sanitize_source_url(r.get("url", ""))
                head = f"{ticker} {company}".strip()
                score_text = f"{score}" if score is not None else "-"
                lines.extend(
                    [
                        f"{i}. {head} ({sector}) / {side} / score={score_text}",
                        f"  補完理由: signal不足時の候補提示 / L:{lr} S:{sr}",
                        f"  出典: {source_url}",
                        "",
                    ]
                )
        if excluded_rows:
            lines.extend(
                [
                    "",
                    "参考（信用取引不可で除外）:",
                ]
            )
            for i, r in enumerate(excluded_rows[:3], 1):
                ticker = (r.get("ticker", "") or "").strip()
                company = (r.get("company", "") or "").strip() or (r.get("company_fallback", "") or "").strip()
                head = f"{ticker} {company}".strip()
                source_url = sanitize_source_url(r.get("url", ""), r.get("source", ""))
                lines.extend(
                    [
                        f"{i}. {head} / 除外理由: 信用取引不可",
                        f"  出典: {source_url}",
                    ]
                )
        return "\n".join(lines)
    for i, r in enumerate(rows, 1):
        exp = expected_direction_ja(r.get("expected_direction", ""))
        lr = rank_ja(r.get("long_rank", ""))
        sr = rank_ja(r.get("short_rank", ""))
        stype = signal_type_ja(r.get("signal_type", ""))
        gate = gate_ja(r.get("gate_status", ""))
        hit = 0
        if gate == "通過":
            hit += 1
        if (r.get("material_signal_checked") or "").lower() == "yes":
            hit += 1
        if (r.get("external_context_checked") or "").lower() == "yes":
            hit += 1
        if (r.get("technical_signal_checked") or "").lower() == "yes":
            hit += 1
        sector = (r.get("sector_group", "") or "不明").strip() or "不明"
        company = (r.get("company", "") or "").strip()
        if not company:
            company = (r.get("company_fallback", "") or "").strip()
        if not company:
            company = (r.get("company_from_plan", "") or "").strip()
        if not company:
            company = (r.get("company_from_candidate", "") or "").strip()
        if company in {"不明", "unknown", "UNKNOWN", "-"}:
            company = ""
        header_name = f"{r.get('ticker','')} {company}".strip()
        source_url = sanitize_source_url(r.get("url", ""), r.get("source", ""))
        rationale = stype if stype else "判定情報不足（分類未設定）"
        lines.extend(
            [
                f"{i}. {header_name} ({sector}) / {exp} / L:{lr} S:{sr}",
                f"  根拠: {rationale} / ruleHits={hit}",
                f"  出典: {source_url}",
                "",
            ]
        )
    if (slot or "").strip() == "inv-noon":
        lines.extend(
            [
                "VWAP運用（昼）:",
                "- ロング: 価格がVWAPを下回ったら継続見直し/撤退候補",
                "- ショート: 価格がVWAPを上回ったら継続見直し/撤退候補",
                "- VWAP逆行中の追撃・ナンピンは禁止",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    rows = load_signals_from_db(args.db, args.date)
    fallback_rows: list[dict[str, str]] = load_entry_candidates_from_db(args.db, args.date, limit=3)
    msg = build_message(args.date, rows, args.slot, fallback_rows=fallback_rows)

    out_txt = OUT_DIR / "market-signals-discord-message.txt"
    out_md = OUT_DIR / "market-signals-discord-message.md"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_txt.write_text(msg, encoding="utf-8")
    out_md.write_text("```text\n" + msg + "```\n", encoding="utf-8")
    print(f"wrote {out_txt.relative_to(ROOT)}")
    print(f"wrote {out_md.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
