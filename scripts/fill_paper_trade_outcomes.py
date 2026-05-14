#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "investment.db"
CACHE = ROOT / ".cache/market-outcomes/yahoo-chart-cache.json"


def epoch(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=JST)
    return int(dt.timestamp())


def load_cache() -> dict:
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_prices(ticker: str, start: str, end: str, cache: dict) -> list[dict]:
    for suffix in (".T", ".N", ".S", ".F"):
        symbol = f"{ticker}{suffix}"
        key = f"{symbol}:{start}:{end}"
        if key in cache and cache[key]:
            return cache[key]
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{symbol}?period1={epoch(start)}&period2={epoch(end)}&interval=1d"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            cache[key] = []
            continue
        result = (data.get("chart", {}).get("result") or [None])[0]
        if not result:
            cache[key] = []
            continue
        timestamps = result.get("timestamp") or []
        quote = (result.get("indicators", {}).get("quote") or [{}])[0]
        close = quote.get("close") or []
        rows = []
        for i, ts in enumerate(timestamps):
            c = close[i] if i < len(close) else None
            if c is None or (isinstance(c, float) and math.isnan(c)):
                continue
            rows.append(
                {
                    "date": datetime.fromtimestamp(ts, JST).strftime("%Y-%m-%d"),
                    "close": float(c),
                }
            )
        cache[key] = rows
        time.sleep(0.12)
        if rows:
            return rows
    return []


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def judge(ret: float | None, threshold: float) -> str | None:
    if ret is None:
        return None
    if ret >= threshold:
        return "win"
    if ret <= -threshold:
        return "loss"
    return "flat"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fill T+1/T+5/T+20 outcomes for paper_trades")
    p.add_argument("--date", help="entry date YYYY-MM-DD (optional)")
    p.add_argument("--mode", default="backtest", choices=["backtest", "live", "all"])
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--as-of", default=date.today().isoformat(), help="only use prices up to this date")
    p.add_argument("--shares-per-lot", type=int, default=100)
    p.add_argument("--judge-threshold-pct", type=float, default=0.5)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    db = Path(args.db)
    as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date()
    cache = load_cache()

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        where = ["status in ('open_pending_outcome','open_partial')"]
        params: list[object] = []
        if args.date:
            where.append("entry_date=?")
            params.append(args.date)
        if args.mode != "all":
            where.append("mode=?")
            params.append(args.mode)
        sql = (
            "select trade_id,entry_date,ticker,side,lots,planned_entry_price,mode "
            "from paper_trades where " + " and ".join(where) + " order by entry_date,ticker"
        )
        trades = conn.execute(sql, params).fetchall()

        updated = 0
        for t in trades:
            entry_date = t["entry_date"]
            start = (datetime.strptime(entry_date, "%Y-%m-%d").date() - timedelta(days=7)).strftime("%Y-%m-%d")
            end = (datetime.strptime(entry_date, "%Y-%m-%d").date() + timedelta(days=45)).strftime("%Y-%m-%d")
            rows = fetch_prices(t["ticker"], start, end, cache)
            if not rows:
                continue
            rows = [r for r in rows if datetime.strptime(r["date"], "%Y-%m-%d").date() <= as_of]
            if not rows:
                continue
            base_idx = next((i for i, r in enumerate(rows) if r["date"] >= entry_date), None)
            if base_idx is None:
                continue
            future = rows[base_idx:]
            if not future:
                continue
            base = float(t["planned_entry_price"] or future[0]["close"])
            side_sign = 1.0 if t["side"] == "long" else -1.0
            qty = int(t["lots"] or 1) * int(args.shares_per_lot)

            def ret_at(n: int) -> float | None:
                if len(future) <= n:
                    return None
                px = float(future[n]["close"])
                return ((px / base) - 1.0) * 100.0 * side_sign

            t1 = ret_at(1)
            t5 = ret_at(5)
            t20 = ret_at(20)
            t1_pnl = None if t1 is None else base * (t1 / 100.0) * qty
            t5_pnl = None if t5 is None else base * (t5 / 100.0) * qty
            t20_pnl = None if t20 is None else base * (t20 / 100.0) * qty

            status = "open_pending_outcome"
            if t20 is not None:
                status = "closed_t20_ready"
            elif t1 is not None or t5 is not None:
                status = "open_partial"

            conn.execute(
                """
                update paper_trades
                   set t1_return_pct=?, t5_return_pct=?, t20_return_pct=?,
                       t1_pnl_jpy=?, t5_pnl_jpy=?, t20_pnl_jpy=?,
                       t1_judge=?, t5_judge=?, t20_judge=?,
                       status=?, updated_at=?
                 where trade_id=?
                """,
                (
                    t1,
                    t5,
                    t20,
                    t1_pnl,
                    t5_pnl,
                    t20_pnl,
                    judge(t1, args.judge_threshold_pct),
                    judge(t5, args.judge_threshold_pct),
                    judge(t20, args.judge_threshold_pct),
                    status,
                    now_iso(),
                    t["trade_id"],
                ),
            )
            updated += 1
        conn.commit()
    finally:
        conn.close()
    save_cache(cache)
    print(f"updated paper trades: {updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
