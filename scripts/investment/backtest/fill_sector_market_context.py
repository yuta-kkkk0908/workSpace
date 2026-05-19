#!/usr/bin/env python3
"""Build rough sector/proxy market context for investment outcome rows.

This supplements static sector profiles with reaction-day proxy ETF/index
returns. It is deliberately rough and meant for post-hoc signal reading, not
trading advice.
"""
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
CACHE = ROOT / ".cache/market-outcomes/yahoo-sector-proxy-cache.json"
JST = timezone(timedelta(hours=9))
DEFAULT_OUTPUT = ROOT / "topics/investment-research/inbox/{date}-sector-market-context-data.json"
DEFAULT_DB = ROOT / "data" / "investment.db"

sys.path.insert(0, str(ROOT / "scripts/investment/analysis"))
import analyze_market_outcomes as outcomes  # noqa: E402


PROFILE_PROXY = {
    "semiconductor_cycle_sensitive": ("2644.T", "global_x_japan_semiconductor"),
    "growth_sensitive": ("2516.T", "tse_growth_250_etf"),
    "risk_appetite_sensitive": ("2516.T", "tse_growth_250_etf"),
    "rate_sensitive": ("1343.T", "tokyo_reit_etf"),
    "rate_sensitive_financial": ("1615.T", "topix_banks_etf"),
    "market_volume_sensitive": ("1615.T", "topix_banks_etf"),
    "export_fx_cyclical": ("1624.T", "topix_machinery_etf"),
    "global_trade_sensitive": ("1629.T", "topix_commercial_wholesale_etf"),
    "cyclical_input_cost_sensitive": ("1629.T", "topix_commercial_wholesale_etf"),
    "domestic_consumption_sensitive": ("1617.T", "topix_foods_etf"),
    "domestic_defensive": ("1617.T", "topix_foods_etf"),
    "defensive_growth_sensitive": ("1617.T", "topix_foods_etf"),
    "domestic_defensive_order_sensitive": ("1624.T", "topix_machinery_etf"),
    "domestic_order_sensitive": ("1624.T", "topix_machinery_etf"),
    "domestic_service_cycle": ("2516.T", "tse_growth_250_etf"),
    "ad_cycle_sensitive": ("2516.T", "tse_growth_250_etf"),
    "policy_rate_sensitive": ("1627.T", "topix_electric_power_gas_etf"),
    "binary_event_sensitive": ("2516.T", "tse_growth_250_etf"),
    "deal_terms_sensitive": ("1306.T", "topix_etf_fallback"),
    "unknown": ("1306.T", "topix_etf_fallback"),
}

BASE_PROXY = ("1306.T", "topix_etf")


def epoch(date: str) -> int:
    return int(datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=JST).timestamp())


def add_days(date: str, days: int) -> str:
    return (datetime.strptime(date, "%Y-%m-%d").date() + timedelta(days=days)).strftime("%Y-%m-%d")


def load_cache() -> dict:
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_symbol(symbol: str, start: str, end: str, cache: dict, cache_only: bool = False) -> list[dict]:
    key = f"{symbol}:{start}:{end}"
    if key in cache and cache[key]:
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
    rows = []
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


def row_at_or_after(rows: list[dict], date: str) -> tuple[int | None, dict | None]:
    for idx, row in enumerate(rows):
        if row["date"] >= date:
            return idx, row
    return None, None


def prev_row(rows: list[dict], idx: int | None) -> dict | None:
    if idx is None or idx <= 0:
        return None
    return rows[idx - 1]


def pct(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return round((current / previous - 1) * 100, 3)


def reaction_date(signal_date: str, session: str, base_rows: list[dict]) -> str:
    target = add_days(signal_date, 1) if session in {"after_close", "after_close_inferred", "eod_report_inferred"} else signal_date
    _, row = row_at_or_after(base_rows, target)
    return row["date"] if row else signal_date


def classify(sector_pct: float | None, topix_pct: float | None) -> str:
    if sector_pct is None or topix_pct is None:
        return "proxy_unavailable"
    relative = sector_pct - topix_pct
    if sector_pct >= 0.5 and relative >= 0.3:
        return "sector_tailwind"
    if sector_pct <= -0.5 and relative <= -0.3:
        return "sector_headwind"
    if relative >= 0.7:
        return "sector_relative_strength"
    if relative <= -0.7:
        return "sector_relative_weakness"
    if sector_pct >= 0.5:
        return "sector_positive_but_market_like"
    if sector_pct <= -0.5:
        return "sector_negative_but_market_like"
    return "sector_neutral_or_unclear"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build rough sector/proxy market context.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    parser.add_argument("--outcome", type=Path, default=None)
    parser.add_argument("--cache-only", action="store_true", help="Use existing Yahoo sector proxy cache only; do not fetch network data.")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    output = args.output or Path(str(DEFAULT_OUTPUT).format(date=args.date))
    outcomes.OUTCOME = args.outcome or Path(str(outcomes.DEFAULT_OUTCOME).format(date=args.date))

    rows = outcomes.parse_outcomes()
    if not rows:
        print("no rows")
        return 0
    start = min(r["signalDate"] for r in rows)
    end = max(r["signalDate"] for r in rows)
    fetch_start = add_days(start, -10)
    fetch_end = add_days(end, 35)
    cache = load_cache()

    symbols = {BASE_PROXY[0]} | {symbol for symbol, _ in PROFILE_PROXY.values()}
    series = {symbol: fetch_symbol(symbol, fetch_start, fetch_end, cache, cache_only=args.cache_only) for symbol in sorted(symbols)}
    save_cache(cache)
    base_rows = series.get(BASE_PROXY[0], [])

    out_rows = []
    for row in rows:
        profile = row.get("sectorProfile") or "unknown"
        symbol, proxy_name = PROFILE_PROXY.get(profile, BASE_PROXY)
        proxy_rows = series.get(symbol, [])
        rd = reaction_date(row["signalDate"], row.get("session", "unknown"), base_rows)
        proxy_idx, proxy_row = row_at_or_after(proxy_rows, rd)
        base_idx, base_row = row_at_or_after(base_rows, rd)
        proxy_prev = prev_row(proxy_rows, proxy_idx)
        base_prev = prev_row(base_rows, base_idx)
        sector_pct = pct(proxy_row.get("close") if proxy_row else None, proxy_prev.get("close") if proxy_prev else None)
        topix_pct = pct(base_row.get("close") if base_row else None, base_prev.get("close") if base_prev else None)
        relative_pct = round(sector_pct - topix_pct, 3) if sector_pct is not None and topix_pct is not None else None
        out_rows.append({
            "ticker": row["ticker"],
            "signalDate": row["signalDate"],
            "session": row.get("session", "unknown"),
            "reactionDate": rd,
            "sectorProfile": profile,
            "proxySymbol": symbol,
            "proxyName": proxy_name,
            "proxyDate": proxy_row.get("date") if proxy_row else None,
            "proxyPct": sector_pct,
            "topixProxySymbol": BASE_PROXY[0],
            "topixPct": topix_pct,
            "relativeToTopixPct": relative_pct,
            "sectorMarketContext": classify(sector_pct, topix_pct),
            "contextSource": "yahoo_finance_sector_proxy_rough",
        })

    output.write_text(json.dumps({
        "date": args.date,
        "cacheOnly": args.cache_only,
        "source": "Yahoo Finance chart API via query1.finance.yahoo.com",
        "proxyPolicy": "sectorProfileごとに代表ETF/指数proxyを割り当て、反応日の前日比とTOPIX ETF比を粗判定する",
        "caution": "ETF proxyによる粗いセクター地合い分類。個別銘柄の売買助言ではない。",
        "proxyMap": {profile: {"symbol": symbol, "name": name} for profile, (symbol, name) in sorted(PROFILE_PROXY.items())},
        "rows": out_rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    conn = sqlite3.connect(args.db)
    try:
        conn.execute("DELETE FROM sector_market_context_rows WHERE date=?", (args.date,))
        for r in out_rows:
            conn.execute(
                """
                INSERT INTO sector_market_context_rows(
                  date,ticker,signal_date,session,reaction_date,sector_profile,proxy_symbol,proxy_name,proxy_date,proxy_pct,
                  topix_proxy_symbol,topix_pct,relative_to_topix_pct,sector_market_context,context_source,source_path,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                """,
                (
                    args.date,
                    r.get("ticker", ""),
                    r.get("signalDate", ""),
                    r.get("session", ""),
                    r.get("reactionDate", ""),
                    r.get("sectorProfile", ""),
                    r.get("proxySymbol", ""),
                    r.get("proxyName", ""),
                    r.get("proxyDate", ""),
                    r.get("proxyPct"),
                    r.get("topixProxySymbol", ""),
                    r.get("topixPct"),
                    r.get("relativeToTopixPct"),
                    r.get("sectorMarketContext", ""),
                    r.get("contextSource", ""),
                    str(output.relative_to(ROOT)),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    print(f"wrote {output.relative_to(ROOT)} rows={len(out_rows)} proxies={len(symbols)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
