#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
JST = timezone(timedelta(hours=9))
DEFAULT_DB = ROOT / "data" / "investment.db"
DEFAULT_OUTPUT = ROOT / "topics/investment-research/inbox/{date}-rough-backtest-stratified-analysis.md"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Analyze rough market outcomes from DB (DB-first).")
    p.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--output", type=Path, default=None)
    return p.parse_args()


def parse_outcomes_from_db(db_path: Path, date_str: str) -> list[dict[str, str]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT b.ticker,b.signal_date,b.disclosure_category,b.signal_type,b.expected_direction,b.long_rank,b.short_rank,
                   b.outcome_type,b.t1_judge,b.t5_judge,b.t20_judge,
                   s.session,
                   mc.market_context,mc.context_source,
                   mrc.margin_bucket,
                   sc.sector_group,sc.sector_profile,
                   smc.sector_market_context,smc.proxy_name,smc.relative_to_topix_pct,
                   tc.technical_status,tc.technical_pattern,tc.ma_trend,tc.close_vs_ma25_bucket,tc.rsi14_bucket,tc.macd_bucket,tc.bollinger_bucket,tc.breakout20
            FROM backtest_outcomes b
            LEFT JOIN signals s ON s.date=b.date AND s.signal_id=b.source_signal_id
            LEFT JOIN market_context_rows mc ON mc.date=b.date AND mc.ticker=b.ticker AND mc.signal_date=b.signal_date
            LEFT JOIN margin_context_rows mrc ON mrc.date=b.date AND mrc.ticker=b.ticker
            LEFT JOIN sector_context_rows sc ON sc.date=b.date AND sc.ticker=b.ticker
            LEFT JOIN sector_market_context_rows smc ON smc.date=b.date AND smc.ticker=b.ticker AND smc.signal_date=b.signal_date
            LEFT JOIN technical_context_rows tc ON tc.date=b.date AND tc.ticker=b.ticker AND tc.signal_date=b.signal_date
            WHERE b.date=?
            """,
            (date_str,),
        ).fetchall()
    finally:
        conn.close()
    out: list[dict[str, str]] = []
    for r in rows:
        out.append(
            {
                "ticker": r["ticker"] or "",
                "signalDate": r["signal_date"] or "",
                "category": r["disclosure_category"] or "unknown",
                "signalType": r["signal_type"] or "unknown",
                "expected": r["expected_direction"] or "unknown",
                "longRank": r["long_rank"] or "unknown",
                "shortRank": r["short_rank"] or "unknown",
                "outcomeType": r["outcome_type"] or "unknown",
                "t1": r["t1_judge"] or "unknown",
                "t5": r["t5_judge"] or "unknown",
                "t20": r["t20_judge"] or "unknown",
                "session": r["session"] or "unknown",
                "marketContext": r["market_context"] or "unknown",
                "marketContextSource": r["context_source"] or "unknown",
                "marginBucket": r["margin_bucket"] or "unknown",
                "sectorGroup": r["sector_group"] or "unknown",
                "sectorProfile": r["sector_profile"] or "unknown",
                "sectorMarketContext": r["sector_market_context"] or "unknown",
                "sectorProxy": r["proxy_name"] or "unknown",
                "sectorRelativeToTopixPct": r["relative_to_topix_pct"] or "unknown",
                "technicalStatus": r["technical_status"] or "unknown",
                "technicalPattern": r["technical_pattern"] or "unknown",
                "maTrend": r["ma_trend"] or "unknown",
                "closeVsMA25Bucket": r["close_vs_ma25_bucket"] or "unknown",
                "rsi14Bucket": r["rsi14_bucket"] or "unknown",
                "macdBucket": r["macd_bucket"] or "unknown",
                "bollingerBucket": r["bollinger_bucket"] or "unknown",
                "breakout20": r["breakout20"] or "unknown",
            }
        )
    return out


def summarize(rows: list[dict[str, str]], dim: str) -> list[str]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for r in rows:
        grouped[r.get(dim) or "unknown"]["rows"] += 1
        grouped[r.get(dim) or "unknown"]["win"] += 1 if r.get("t1") == "win" else 0
    out = []
    for k in sorted(grouped):
        c = grouped[k]
        out.append(f"- {k}: rows={c['rows']} t1_win={c['win']}")
    return out


def main() -> int:
    args = parse_args()
    rows = parse_outcomes_from_db(args.db, args.date)
    out = args.output or Path(str(DEFAULT_OUTPUT).format(date=args.date))
    lines = [
        f"# {args.date} Rough Backtest Stratified Analysis",
        "",
        f"- analyzedRows: {len(rows)}",
        "",
        "## By Category",
        *summarize(rows, "category"),
        "",
        "## By Session",
        *summarize(rows, "session"),
        "",
        "## By Market Context",
        *summarize(rows, "marketContext"),
        "",
        "## By Margin Bucket",
        *summarize(rows, "marginBucket"),
        "",
        "## By Sector Profile",
        *summarize(rows, "sectorProfile"),
        "",
        "## By Technical Pattern",
        *summarize(rows, "technicalPattern"),
    ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
