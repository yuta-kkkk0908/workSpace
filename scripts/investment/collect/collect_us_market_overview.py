#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CACHE = ROOT / ".cache/market-outcomes/yahoo-us-market-overview-cache.json"
JST = timezone(timedelta(hours=9))
SOURCE_DIR = ROOT / "topics/investment-research/source"

if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db

DEFAULT_DB = resolve_investment_db()

SYMBOLS = {
    "sp500": "^GSPC",
    "nasdaq": "^IXIC",
    "dow": "^DJI",
    "vix": "^VIX",
    "usdjpy": "JPY=X",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Collect a compact US market overview for the morning report")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--cache-only", action="store_true", help="Use existing cache only; do not fetch network data.")
    return p.parse_args()


def epoch(date_str: str) -> int:
    return int(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=JST).timestamp())


def load_cache() -> dict:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(cache: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_symbol(symbol: str, start: str, end: str, cache: dict, cache_only: bool = False) -> list[dict]:
    key = f"{symbol}:{start}:{end}"
    if key in cache:
        return cache[key]
    if cache_only:
        return []
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{symbol}?period1={epoch(start)}&period2={epoch(end)}&interval=1d"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        cache[key] = []
        return []
    result = (data.get("chart", {}).get("result") or [None])[0]
    rows: list[dict] = []
    if result:
        timestamps = result.get("timestamp") or []
        quote = (result.get("indicators", {}).get("quote") or [{}])[0]
        adj = (result.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or []
        close = quote.get("close") or []
        for idx, ts in enumerate(timestamps):
            c = adj[idx] if idx < len(adj) and adj[idx] is not None else (close[idx] if idx < len(close) else None)
            if c is None or (isinstance(c, float) and math.isnan(c)):
                continue
            rows.append({"date": datetime.fromtimestamp(ts, JST).strftime("%Y-%m-%d"), "close": round(float(c), 4)})
    cache[key] = rows
    time.sleep(0.1)
    return rows


def pct(current: float | None, prev: float | None) -> float | None:
    if current is None or prev in (None, 0):
        return None
    return round((current / prev - 1) * 100, 3)


def row_at_or_before(rows: list[dict], date: str) -> tuple[int | None, dict | None]:
    idx = None
    row = None
    for i, candidate in enumerate(rows):
        if candidate["date"] <= date:
            idx = i
            row = candidate
        else:
            break
    return idx, row


def prev_row(rows: list[dict], idx: int | None) -> dict | None:
    if idx is None or idx <= 0:
        return None
    return rows[idx - 1]


def format_move(value: float | None, is_fx: bool = False) -> str:
    if value is None:
        return "不明"
    sign = "+" if value > 0 else ""
    if is_fx:
        return f"{sign}{value:.2f}%"
    return f"{sign}{value:.1f}%"


def build_sector_impact(
    sp500_pct: float | None,
    nasdaq_pct: float | None,
    dow_pct: float | None,
    vix_pct: float | None,
    usdjpy_pct: float | None,
) -> str:
    parts: list[str] = []
    if nasdaq_pct is not None and nasdaq_pct >= 0.5:
        parts.append("半導体・グロースに追い風")
    elif nasdaq_pct is not None and nasdaq_pct <= -0.5:
        parts.append("半導体・グロースは注意")

    if dow_pct is not None and dow_pct >= 0.5:
        parts.append("バリュー・景気敏感にやや追い風")
    elif dow_pct is not None and dow_pct <= -0.5:
        parts.append("バリュー・景気敏感はやや注意")

    if usdjpy_pct is not None and usdjpy_pct >= 0.2:
        parts.append("輸出・機械・自動車に追い風")
    elif usdjpy_pct is not None and usdjpy_pct <= -0.2:
        parts.append("輸出・機械・自動車はやや逆風")

    if vix_pct is not None and vix_pct >= 3.0:
        parts.append("高PER・リスク資産は注意")
    elif vix_pct is not None and vix_pct <= -3.0 and sp500_pct is not None and sp500_pct >= 0:
        parts.append("リスク選好がやや改善")

    if not parts:
        return "セクター優位はまだ薄い"
    uniq: list[str] = []
    for item in parts:
        if item not in uniq:
            uniq.append(item)
    return " / ".join(uniq)


def build_overview(date_str: str, series: dict[str, list[dict]]) -> dict:
    summary_items: list[str] = []
    prices: dict[str, dict[str, float | str | None]] = {}
    session_date = ""
    for key, rows in series.items():
        idx, row = row_at_or_before(rows, date_str)
        prev = prev_row(rows, idx)
        current = float(row["close"]) if row else None
        previous = float(prev["close"]) if prev else None
        change = pct(current, previous)
        prices[key] = {
            "date": row["date"] if row else None,
            "close": current,
            "prev_date": prev["date"] if prev else None,
            "prev_close": previous,
            "pct": change,
        }
        if key in {"sp500", "nasdaq", "dow", "vix", "usdjpy"} and row:
            session_date = session_date or row["date"]
        if key in {"sp500", "nasdaq", "dow"}:
            label = {"sp500": "S&P500", "nasdaq": "Nasdaq", "dow": "Dow"}[key]
            summary_items.append(f"{label} {format_move(change)}")

    vix_pct = prices.get("vix", {}).get("pct") if prices.get("vix") else None
    usdjpy_pct = prices.get("usdjpy", {}).get("pct") if prices.get("usdjpy") else None
    sp500_pct = prices.get("sp500", {}).get("pct") if prices.get("sp500") else None
    nasdaq_pct = prices.get("nasdaq", {}).get("pct") if prices.get("nasdaq") else None
    dow_pct = prices.get("dow", {}).get("pct") if prices.get("dow") else None
    if prices.get("vix", {}).get("close") is not None:
        summary_items.append(f"VIX {format_move(vix_pct)}")
    if prices.get("usdjpy", {}).get("close") is not None:
        usd_close = float(prices["usdjpy"]["close"]) if prices["usdjpy"]["close"] is not None else None
        summary_items.append(f"USDJPY {usd_close:.2f} ({format_move(usdjpy_pct, is_fx=True)})" if usd_close is not None else "USDJPY 不明")

    return {
        "date": date_str,
        "usSessionDate": session_date or None,
        "summary": " / ".join(summary_items) if summary_items else "米市場データを取得できませんでした",
        "sectorImpact": build_sector_impact(sp500_pct, nasdaq_pct, dow_pct, vix_pct, usdjpy_pct),
        "prices": prices,
        "source": "Yahoo Finance chart API via query1.finance.yahoo.com",
        "caution": "米市場の終値ベース概況。日本市場の寄り付きは他要因でも変動する。",
    }


def render_markdown(payload: dict) -> str:
    lines = [
        f"# {payload['date']} US Market Overview",
        "",
        f"- usSessionDate: {payload.get('usSessionDate') or 'unknown'}",
        f"- 米市場概況: {payload.get('summary') or 'unknown'}",
        f"- 日本セクター影響: {payload.get('sectorImpact') or 'unknown'}",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"db not found: {args.db}")
    start = (datetime.strptime(args.date, "%Y-%m-%d").date() - timedelta(days=10)).isoformat()
    end = (datetime.strptime(args.date, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
    cache = load_cache()
    series = {name: fetch_symbol(symbol, start, end, cache, cache_only=args.cache_only) for name, symbol in SYMBOLS.items()}
    save_cache(cache)
    payload = build_overview(args.date, series)

    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    out_json = SOURCE_DIR / f"{args.date}-us-market-overview.json"
    out_md = SOURCE_DIR / f"{args.date}-us-market-overview.md"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(render_markdown(payload), encoding="utf-8")

    conn = sqlite3.connect(args.db)
    try:
        conn.execute(
            """
            INSERT INTO collection_artifacts(artifact_key,artifact_date,artifact_type,payload_json,updated_at)
            VALUES(?,?,?,?,datetime('now'))
            ON CONFLICT(artifact_key,artifact_date) DO UPDATE SET
              artifact_type=excluded.artifact_type,
              payload_json=excluded.payload_json,
              updated_at=excluded.updated_at
            """,
            ("us_market_overview", args.date, "market_overview", json.dumps(payload, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()

    print(f"wrote {out_json.relative_to(ROOT)}")
    print(f"wrote {out_md.relative_to(ROOT)}")
    print(f"saved: collection_artifacts us_market_overview {args.date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
