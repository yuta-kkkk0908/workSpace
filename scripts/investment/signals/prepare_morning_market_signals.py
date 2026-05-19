#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INBOX = ROOT / "topics" / "investment-research" / "inbox"
DEFAULT_DB = ROOT / "data" / "investment.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Prepare lightweight morning market-signals for the target date (DB-first)")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--fallback-days", type=int, default=3)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    return p.parse_args()


def find_latest_date(conn: sqlite3.Connection, date_str: str, fallback_days: int) -> str | None:
    base = datetime.strptime(date_str, "%Y-%m-%d").date()
    for i in range(1, max(0, fallback_days) + 1):
        d = (base - timedelta(days=i)).isoformat()
        n = conn.execute("SELECT COUNT(*) FROM signals WHERE date=?", (d,)).fetchone()[0]
        if n and int(n) > 0:
            return d
    return None


def write_audit_markdown(dst: Path, date_str: str, rows: list[sqlite3.Row], src_date: str | None) -> None:
    lines = [
        f"# {date_str} Market Signals",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {date_str}",
        "- mode: collect-and-update",
        "- caution: 売買助言ではなく、材料整理と確認観点。",
        "",
        "## Morning Lightweight Notes",
        f"- generatedAt: {date_str} 07:30 JST",
        f"- sourceCarryOverDate: {src_date or 'none'}",
        "- note: 当日朝の軽量収集モード。DB繰越データを土台に寄り前確認で更新する。",
        "",
        "## Signals",
    ]
    if not rows:
        lines.append("- N/C")
    else:
        for i, r in enumerate(rows, 1):
            lines.extend(
                [
                    f"### signal_{date_str.replace('-', '')}_{i:03d}: {(r['ticker'] or '')} {(r['company'] or '')}",
                    f"- ticker: {r['ticker'] or ''}",
                    f"- company: {r['company'] or ''}",
                    f"- source: {r['source'] or ''}",
                    f"- url: {r['url'] or ''}",
                    f"- publishedAt: {date_str}",
                    "- session: after_close",
                    f"- signalType: {r['signal_type'] or ''}",
                    "- signalRank: B",
                    f"- longSignalRank: {r['long_rank'] or 'C'}",
                    f"- shortSignalRank: {r['short_rank'] or 'C'}",
                    f"- expectedDirection: {r['expected_direction'] or 'unknown'}",
                    "",
                ]
            )
    dst.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"db not found: {args.db}")
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        existing = conn.execute("SELECT COUNT(*) FROM signals WHERE date=?", (args.date,)).fetchone()[0]
        rows_for_audit: list[sqlite3.Row] = []
        if existing and int(existing) > 0:
            rows_for_audit = conn.execute(
                """
                SELECT signal_id,ticker,company,signal_type,expected_direction,long_rank,short_rank,source,url
                FROM signals WHERE date=? ORDER BY signal_id
                """,
                (args.date,),
            ).fetchall()
            src_date = args.date
        else:
            src_date = find_latest_date(conn, args.date, args.fallback_days)
            if src_date:
                src_rows = conn.execute(
                    """
                    SELECT ticker,company,signal_type,expected_direction,long_rank,short_rank,source,url,session,
                           gate_status,material_signal_checked,external_context_checked,technical_signal_checked
                    FROM signals WHERE date=? ORDER BY signal_id
                    """,
                    (src_date,),
                ).fetchall()
                conn.execute("DELETE FROM signals WHERE date=?", (args.date,))
                ymd = args.date.replace("-", "")
                for i, r in enumerate(src_rows, 1):
                    sid = f"signal_{ymd}_{i:03d}"
                    conn.execute(
                        """
                        INSERT INTO signals(
                          signal_id,date,ticker,company,signal_type,expected_direction,long_rank,short_rank,
                          gate_status,url,source,session,material_signal_checked,external_context_checked,technical_signal_checked,
                          source_path,updated_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                        """,
                        (
                            sid,
                            args.date,
                            r["ticker"] or "",
                            r["company"] or "",
                            r["signal_type"] or "",
                            r["expected_direction"] or "",
                            r["long_rank"] or "C",
                            r["short_rank"] or "C",
                            r["gate_status"] or "pass",
                            r["url"] or "",
                            r["source"] or "",
                            r["session"] or "after_close",
                            r["material_signal_checked"] or "yes",
                            r["external_context_checked"] or "yes",
                            r["technical_signal_checked"] or "yes",
                            "db:carry-over",
                        ),
                    )
                conn.commit()
                rows_for_audit = conn.execute(
                    """
                    SELECT signal_id,ticker,company,signal_type,expected_direction,long_rank,short_rank,source,url
                    FROM signals WHERE date=? ORDER BY signal_id
                    """,
                    (args.date,),
                ).fetchall()
            else:
                src_date = None
                conn.execute("DELETE FROM signals WHERE date=?", (args.date,))
                conn.commit()
        out = INBOX / f"{args.date}-market-signals.md"
        write_audit_markdown(out, args.date, rows_for_audit, src_date)
    finally:
        conn.close()
    if src_date:
        print(f"prepared signals: date={args.date} sourceDate={src_date} rows={len(rows_for_audit)}")
    else:
        print(f"prepared minimal: date={args.date} rows=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
