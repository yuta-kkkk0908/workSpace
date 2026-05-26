#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INBOX = ROOT / "topics" / "investment-research" / "inbox"
DEFAULT_DB = ROOT / "data" / "investment.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate technical daily signals from facts_price_daily and upsert into signals table")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--lookback-days", type=int, default=80)
    p.add_argument("--max-signals", type=int, default=40)
    p.add_argument("--min-volume", type=int, default=50000)
    return p.parse_args()


def sma(vals: list[float], n: int) -> float | None:
    if len(vals) < n:
        return None
    return sum(vals[-n:]) / n


def stddev(vals: list[float], n: int) -> float | None:
    if len(vals) < n:
        return None
    w = vals[-n:]
    mu = sum(w) / n
    var = sum((x - mu) ** 2 for x in w) / n
    return math.sqrt(var)


def classify(rows: list[sqlite3.Row], min_volume: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    by_ticker: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        by_ticker[str(r["ticker"])].append(r)
    for ticker, ts in by_ticker.items():
        ts.sort(key=lambda x: x["date"])
        if len(ts) < 30:
            continue
        today = ts[-1]
        prev = ts[-2]
        vol = int(today["volume"] or 0)
        if vol < min_volume:
            continue
        closes = [float(x["close"]) for x in ts if x["close"] is not None]
        opens = [float(x["open"]) for x in ts if x["open"] is not None]
        highs = [float(x["high"]) for x in ts if x["high"] is not None]
        lows = [float(x["low"]) for x in ts if x["low"] is not None]
        if len(closes) < 25 or len(opens) < 3 or len(highs) < 3 or len(lows) < 3:
            continue

        ma25_t = sma(closes, 25)
        ma25_p = sma(closes[:-1], 25)
        bb_mid_t = sma(closes, 20)
        bb_std_t = stddev(closes, 20)
        bb_mid_p = sma(closes[:-1], 20)
        bb_std_p = stddev(closes[:-1], 20)
        if ma25_t is None or ma25_p is None or bb_mid_t is None or bb_std_t is None or bb_mid_p is None or bb_std_p is None:
            continue

        c_t = float(today["close"])
        o_t = float(today["open"])
        h_t = float(today["high"])
        l_t = float(today["low"])
        c_p = float(prev["close"])
        o_p = float(prev["open"])
        h_p = float(prev["high"])
        l_p = float(prev["low"])

        upper_t = bb_mid_t + 2.0 * bb_std_t
        lower_t = bb_mid_t - 2.0 * bb_std_t
        upper_p = bb_mid_p + 2.0 * bb_std_p
        lower_p = bb_mid_p - 2.0 * bb_std_p

        # MA反発: 前日までMA25タッチ/割れ -> 当日終値がMA25回復
        if l_p <= ma25_p and c_t > ma25_t and c_t > c_p:
            out.append(
                {
                    "ticker": ticker,
                    "signal_type": "technical_ma_rebound",
                    "expected_direction": "up",
                    "long_rank": "B",
                    "short_rank": "none",
                    "score": round((c_t - ma25_t) / max(ma25_t, 1.0) * 100.0, 3),
                    "note": "prev_low<=MA25 and close reclaimed MA25",
                }
            )

        # ボリンジャー追従（上）: 2日連続で+2σ超え
        if c_p > upper_p and c_t > upper_t and c_t > c_p:
            out.append(
                {
                    "ticker": ticker,
                    "signal_type": "technical_bb_follow_up",
                    "expected_direction": "up",
                    "long_rank": "B+",
                    "short_rank": "none",
                    "score": round((c_t - upper_t) / max(abs(upper_t), 1.0) * 100.0, 3),
                    "note": "2-day close above upper band",
                }
            )

        # ボリンジャー反発（上）: 前日-2σ割れ -> 当日-1σ(下限寄り)を回復
        if l_p < lower_p and c_t > lower_t and c_t > o_t:
            out.append(
                {
                    "ticker": ticker,
                    "signal_type": "technical_bb_rebound_up",
                    "expected_direction": "up_watch",
                    "long_rank": "B",
                    "short_rank": "none",
                    "score": round((c_t - lower_t) / max(abs(lower_t), 1.0) * 100.0, 3),
                    "note": "rebound from below lower band",
                }
            )

        # 3本陽線（簡易）: 3連続陽線 + 高値/安値切り上げ
        c1, c2, c3 = closes[-3], closes[-2], closes[-1]
        o1, o2, o3 = opens[-3], opens[-2], opens[-1]
        h1, h2, h3 = highs[-3], highs[-2], highs[-1]
        l1, l2, l3 = lows[-3], lows[-2], lows[-1]
        if c1 > o1 and c2 > o2 and c3 > o3 and h1 < h2 < h3 and l1 < l2 < l3:
            out.append(
                {
                    "ticker": ticker,
                    "signal_type": "technical_three_white_soldiers",
                    "expected_direction": "up",
                    "long_rank": "A-",
                    "short_rank": "none",
                    "score": round((c3 - c1) / max(c1, 1.0) * 100.0, 3),
                    "note": "3 bullish candles with rising highs/lows",
                }
            )

        # 3本陰線反発監視: 3連続陰線の翌反発候補（watch）
        if c1 < o1 and c2 < o2 and c3 < o3 and c_t > o_t and l_t > l_p:
            out.append(
                {
                    "ticker": ticker,
                    "signal_type": "technical_three_black_rebound_watch",
                    "expected_direction": "up_watch",
                    "long_rank": "B",
                    "short_rank": "none",
                    "score": round((c_t - o_t) / max(o_t, 1.0) * 100.0, 3),
                    "note": "possible rebound after 3 bearish candles",
                }
            )
    return out


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"db not found: {args.db}")
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        d0 = datetime.strptime(args.date, "%Y-%m-%d").date()
        min_date = (d0 - timedelta(days=max(30, args.lookback_days))).isoformat()
        rows = conn.execute(
            """
            WITH universe AS (
              SELECT DISTINCT ticker
              FROM facts_price_daily
              WHERE date=?
            )
            SELECT f.date,f.ticker,f.open,f.high,f.low,f.close,f.volume
            FROM facts_price_daily f
            JOIN universe u ON u.ticker=f.ticker
            WHERE f.date BETWEEN ? AND ?
            ORDER BY f.ticker,f.date
            """,
            (args.date, min_date, args.date),
        ).fetchall()
        candidates = classify(rows, args.min_volume)
        # 重複ticker×signal_typeの後勝ち防止
        uniq: dict[tuple[str, str], dict[str, str]] = {}
        for r in candidates:
            uniq[(r["ticker"], r["signal_type"])] = r
        final_rows = sorted(uniq.values(), key=lambda x: float(x.get("score", 0.0)), reverse=True)[: args.max_signals]

        # 当日technicalシグナルを置換
        conn.execute("DELETE FROM signals WHERE date=? AND source='technical_daily'", (args.date,))
        ymd = args.date.replace("-", "")
        for i, r in enumerate(final_rows, start=1):
            sid = f"signal_{ymd}_tech_{i:03d}"
            conn.execute(
                """
                INSERT INTO signals(
                  signal_id,date,ticker,company,signal_type,expected_direction,long_rank,short_rank,
                  gate_status,url,source,session,material_signal_checked,external_context_checked,technical_signal_checked,
                  source_path,payload_json,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                """,
                (
                    sid,
                    args.date,
                    r.get("ticker", ""),
                    "",
                    r.get("signal_type", ""),
                    r.get("expected_direction", "unknown"),
                    r.get("long_rank", "B"),
                    r.get("short_rank", "none"),
                    "pass",
                    "",
                    "technical_daily",
                    "after_close",
                    "yes",
                    "yes",
                    "yes",
                    "db:facts_price_daily",
                    str(r),
                ),
            )
        conn.commit()
    finally:
        conn.close()

    out = INBOX / f"{args.date}-technical-signals.md"
    lines = [f"# {args.date} Technical Signals", "", f"- count: {len(final_rows)}", "- source: facts_price_daily", ""]
    for r in final_rows:
        lines.append(f"- {r['ticker']} {r['signal_type']} dir={r['expected_direction']} longRank={r['long_rank']} score={r['score']} note={r['note']}")
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} signals={len(final_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
