#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db

DEFAULT_DB = resolve_investment_db()
CACHE = ROOT / ".cache" / "market-outcomes" / "yahoo-intraday-cache.json"
JST = timezone(timedelta(hours=9))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Collect intraday snapshots for today's signals")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--slot", default="inv-noon")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--cache-only", action="store_true")
    return p.parse_args()


def epoch_jst(d: str, hour: int = 0, minute: int = 0) -> int:
    dt = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=JST, hour=hour, minute=minute, second=0, microsecond=0)
    return int(dt.timestamp())


def load_cache() -> dict:
    if not CACHE.exists():
        return {}
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(cache: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def fetch_intraday_rows(ticker: str, date_str: str, cache: dict, cache_only: bool) -> tuple[list[dict], str]:
    start = epoch_jst(date_str, 0, 0)
    end = epoch_jst((datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d"), 0, 0)
    for suffix in (".T", ".N", ".S", ".F"):
        symbol = f"{ticker}{suffix}"
        key = f"{symbol}:{date_str}:15m"
        if key in cache and cache[key]:
            return cache[key], "cache_yahoo_intraday_15m"
        if cache_only:
            continue
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{symbol}?period1={start}&period2={end}&interval=15m&includePrePost=false"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
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
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        vols = quote.get("volume") or []
        rows: list[dict] = []
        for i, ts in enumerate(timestamps):
            if i >= len(closes) or closes[i] is None:
                continue
            c = float(closes[i])
            o = float(opens[i]) if i < len(opens) and opens[i] is not None else c
            h = float(highs[i]) if i < len(highs) and highs[i] is not None else c
            l = float(lows[i]) if i < len(lows) and lows[i] is not None else c
            v = int(vols[i]) if i < len(vols) and vols[i] is not None else 0
            rows.append(
                {
                    "ts": ts,
                    "time": datetime.fromtimestamp(ts, JST).strftime("%Y-%m-%d %H:%M:%S"),
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": v,
                }
            )
        cache[key] = rows
        time.sleep(0.1)
        if rows:
            return rows, "yahoo_intraday_15m"
    return [], "missing"


def pick_noon_snapshot(rows: list[dict], date_str: str) -> dict | None:
    limit = datetime.strptime(f"{date_str} 11:30:00", "%Y-%m-%d %H:%M:%S").replace(tzinfo=JST).timestamp()
    am = [r for r in rows if r.get("ts", 0) <= limit]
    if not am:
        return None
    cum_pv = 0.0
    cum_v = 0
    for r in am:
        v = int(r.get("volume", 0) or 0)
        c = float(r.get("close", 0.0) or 0.0)
        if v > 0:
            cum_pv += c * v
            cum_v += v
    last = am[-1]
    vwap = (cum_pv / cum_v) if cum_v > 0 else float(last.get("close", 0.0) or 0.0)
    return {
        "snapshot_time": str(last.get("time") or f"{date_str} 11:30:00"),
        "price": float(last.get("close", 0.0) or 0.0),
        "vwap": vwap,
        "volume": sum(int(r.get("volume", 0) or 0) for r in am),
        "bars": len(am),
    }


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cache = load_cache()
    try:
        tickers = [str(r["ticker"]) for r in conn.execute("SELECT DISTINCT ticker FROM signals WHERE date=? AND COALESCE(ticker,'')<>''", (args.date,)).fetchall()]
        if not tickers:
            print(f"intraday_snapshot date={args.date} tickers=0")
            return 0
        conn.execute("DELETE FROM market_signal_snapshots WHERE date=? AND slot=?", (args.date, args.slot))
        inserted = 0
        for ticker in tickers:
            rows, source_kind = fetch_intraday_rows(ticker, args.date, cache, args.cache_only)
            snap = pick_noon_snapshot(rows, args.date)
            if not snap:
                continue
            prev = conn.execute(
                """
                SELECT close, volume FROM facts_price_daily
                WHERE ticker=? AND date < ?
                ORDER BY date DESC LIMIT 1
                """,
                (ticker, args.date),
            ).fetchone()
            prev_close = float(prev["close"]) if prev and prev["close"] is not None else None
            ret_pct = ((snap["price"] / prev_close - 1.0) * 100.0) if prev_close and prev_close > 0 else None
            avg_vol = conn.execute(
                """
                SELECT AVG(volume) AS avgv FROM (
                  SELECT volume FROM facts_price_daily
                  WHERE ticker=? AND date < ? AND volume IS NOT NULL
                  ORDER BY date DESC LIMIT 20
                )
                """,
                (ticker, args.date),
            ).fetchone()
            avgv = float(avg_vol["avgv"]) if avg_vol and avg_vol["avgv"] is not None else None
            vol_ratio = (snap["volume"] / avgv) if avgv and avgv > 0 else None
            vgap = ((snap["price"] / snap["vwap"] - 1.0) * 100.0) if snap["vwap"] else None
            conn.execute(
                """
                INSERT INTO market_signal_snapshots(
                  date,ticker,slot,snapshot_time,price,vwap,vwap_gap_pct,return_pct,volume,volume_ratio,
                  source_kind,source_ref,payload_json,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                """,
                (
                    args.date,
                    ticker,
                    args.slot,
                    snap["snapshot_time"],
                    snap["price"],
                    snap["vwap"],
                    vgap,
                    ret_pct,
                    snap["volume"],
                    vol_ratio,
                    source_kind,
                    "query1.finance.yahoo.com chart interval=15m",
                    json.dumps({"bars": snap["bars"]}, ensure_ascii=False),
                ),
            )
            inserted += 1
        conn.commit()
    finally:
        conn.close()
    save_cache(cache)
    print(f"intraday_snapshot date={args.date} slot={args.slot} inserted={inserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
