#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"
JST = timezone(timedelta(hours=9))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill daily OHLCV into facts_price_daily with progress tracking")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--target-bars", type=int, default=200, choices=[200, 500])
    p.add_argument("--max-tickers", type=int, default=60)
    p.add_argument("--sleep", type=float, default=0.2)
    p.add_argument("--jitter", type=float, default=0.2)
    p.add_argument("--timeout", type=float, default=15.0)
    return p.parse_args()


def epoch(date_str: str) -> int:
    return int(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=JST).timestamp())


def choose_universe(conn: sqlite3.Connection) -> list[str]:
    tickers: set[str] = set()
    for table in ("signals", "tdnet_disclosures", "credit_status_rows", "backtest_outcomes", "facts_price_daily", "instruments"):
        try:
            rows = conn.execute(f"SELECT DISTINCT ticker FROM {table} WHERE COALESCE(ticker,'')<>''").fetchall()
        except sqlite3.OperationalError:
            continue
        for (t,) in rows:
            s = str(t or "").strip()
            if s:
                tickers.add(s)
    return sorted(tickers)


def fetch_rows(ticker: str, start: str, end: str, timeout: float) -> tuple[str, list[dict]]:
    for suffix in (".T", ".N", ".S", ".F"):
        symbol = f"{ticker}{suffix}"
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{symbol}?period1={epoch(start)}&period2={epoch(end)}&interval=1d"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            continue
        result = (data.get("chart", {}).get("result") or [None])[0]
        if not result:
            continue
        timestamps = result.get("timestamp") or []
        quote = (result.get("indicators", {}).get("quote") or [{}])[0]
        adj = (result.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or []
        out: list[dict] = []
        for idx, ts in enumerate(timestamps):
            close_raw = adj[idx] if idx < len(adj) and adj[idx] is not None else (quote.get("close") or [None])[idx]
            if close_raw is None:
                continue
            o = (quote.get("open") or [None])[idx]
            h = (quote.get("high") or [None])[idx]
            l = (quote.get("low") or [None])[idx]
            v = (quote.get("volume") or [None])[idx]
            out.append(
                {
                    "date": datetime.fromtimestamp(ts, JST).strftime("%Y-%m-%d"),
                    "open": float(o) if o is not None else float(close_raw),
                    "high": float(h) if h is not None else float(close_raw),
                    "low": float(l) if l is not None else float(close_raw),
                    "close": float(close_raw),
                    "volume": int(v) if v is not None else None,
                    "symbol": symbol,
                }
            )
        if out:
            return symbol, out
    return "", []


def main() -> int:
    args = parse_args()
    target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    start = (target_date - timedelta(days=max(730, args.target_bars * 3))).strftime("%Y-%m-%d")
    end = (target_date + timedelta(days=1)).strftime("%Y-%m-%d")
    now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    conn = sqlite3.connect(args.db)
    try:
        universe = choose_universe(conn)
        if not universe:
            print("price_backfill no_tickers")
            return 0
        planned: list[str] = []
        for ticker in universe:
            row = conn.execute(
                """
                SELECT bars_collected,target_bars
                FROM collection_progress
                WHERE source='price_backfill_yahoo' AND partition_key=?
                """,
                (ticker,),
            ).fetchone()
            bars_collected = int((row[0] if row else 0) or 0)
            prev_target = int((row[1] if row else 0) or 0)
            effective_target = max(args.target_bars, prev_target)
            if bars_collected < effective_target:
                planned.append(ticker)
        planned = planned[: max(1, args.max_tickers)]
        success = 0
        for ticker in planned:
            try:
                symbol, rows = fetch_rows(ticker, start, end, args.timeout)
                if not rows:
                    conn.execute(
                        """
                        INSERT INTO collection_progress(source,partition_key,last_date,status,bars_collected,target_bars,last_run_at,error_message,updated_at)
                        VALUES('price_backfill_yahoo',?,?,?,?,?,?,?,?)
                        ON CONFLICT(source,partition_key) DO UPDATE SET
                          status=excluded.status,
                          target_bars=excluded.target_bars,
                          last_run_at=excluded.last_run_at,
                          error_message=excluded.error_message,
                          updated_at=excluded.updated_at
                        """,
                        (ticker, None, "error", 0, args.target_bars, now_utc, "fetch_failed", now_utc),
                    )
                    conn.commit()
                    continue
                source_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                for r in rows:
                    conn.execute(
                        """
                        INSERT INTO facts_price_daily(
                          date,ticker,open,high,low,close,volume,source_kind,source_url,fetched_at,updated_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(date,ticker) DO UPDATE SET
                          open=excluded.open,
                          high=excluded.high,
                          low=excluded.low,
                          close=excluded.close,
                          volume=excluded.volume,
                          source_kind=excluded.source_kind,
                          source_url=excluded.source_url,
                          fetched_at=excluded.fetched_at,
                          updated_at=excluded.updated_at
                        """,
                        (
                            r["date"],
                            ticker,
                            r["open"],
                            r["high"],
                            r["low"],
                            r["close"],
                            r["volume"],
                            "yahoo_chart",
                            source_url,
                            now_utc,
                            now_utc,
                        ),
                    )
                conn.execute(
                    """
                    INSERT INTO instruments(ticker,source_kind,updated_at)
                    VALUES(?,?,?)
                    ON CONFLICT(ticker) DO UPDATE SET
                      updated_at=excluded.updated_at
                    """,
                    (ticker, "derived", now_utc),
                )
                bars = int(
                    conn.execute("SELECT COUNT(*) FROM facts_price_daily WHERE ticker=?", (ticker,)).fetchone()[0]
                    or 0
                )
                conn.execute(
                    """
                    INSERT INTO collection_progress(source,partition_key,last_date,status,bars_collected,target_bars,last_run_at,error_message,updated_at)
                    VALUES('price_backfill_yahoo',?,?,?,?,?,?,?,?)
                    ON CONFLICT(source,partition_key) DO UPDATE SET
                      last_date=excluded.last_date,
                      status=excluded.status,
                      bars_collected=excluded.bars_collected,
                      target_bars=excluded.target_bars,
                      last_run_at=excluded.last_run_at,
                      error_message=excluded.error_message,
                      updated_at=excluded.updated_at
                    """,
                    (
                        ticker,
                        args.date,
                        "ok" if bars >= args.target_bars else "partial",
                        bars,
                        args.target_bars,
                        now_utc,
                        "",
                        now_utc,
                    ),
                )
                conn.commit()
                success += 1
                time.sleep(max(0.0, args.sleep + random.uniform(0.0, max(0.0, args.jitter))))
            except Exception as e:
                conn.execute(
                    """
                    INSERT INTO collection_progress(source,partition_key,last_date,status,bars_collected,target_bars,last_run_at,error_message,updated_at)
                    VALUES('price_backfill_yahoo',?,?,?,?,?,?,?,?)
                    ON CONFLICT(source,partition_key) DO UPDATE SET
                      status=excluded.status,
                      target_bars=excluded.target_bars,
                      last_run_at=excluded.last_run_at,
                      error_message=excluded.error_message,
                      updated_at=excluded.updated_at
                    """,
                    (ticker, None, "error", 0, args.target_bars, now_utc, str(e)[:240], now_utc),
                )
                conn.commit()
        print(f"price_backfill target={args.target_bars} planned={len(planned)} success={success}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

