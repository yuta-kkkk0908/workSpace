#!/usr/bin/env python3
"""Fill rough T+1/T+3/T+5/T+10/T+20 outcomes for investment backtest seed files.

This is intentionally rough: it uses Yahoo Finance daily closes and compares
future closes with the close on the signal date. It is for research logs, not
trading advice.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from json import JSONDecodeError

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = ROOT / "topics/investment-research/inbox/{date}-rough-backtest-outcomes-batch-1.md"
DEFAULT_AGGREGATION_OUTPUT = ROOT / "topics/investment-research/inbox/{date}-rough-backtest-win-loss-aggregation.md"
CACHE = ROOT / ".cache/market-outcomes/yahoo-chart-cache.json"
sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db

DEFAULT_DB = resolve_investment_db()

sys.path.insert(0, str(ROOT / "scripts/investment/analysis"))
from investment_seed_config import DEFAULT_CONFIG, load_seed_paths  # noqa: E402


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


@dataclass
class Signal:
    signal_id: str
    title: str
    ticker: str
    signal_date: str
    category: str
    signal_type: str
    expected: str
    long_rank: str
    short_rank: str
    source_file: str


def parse_signals(paths: Iterable[Path]) -> list[Signal]:
    signals: list[Signal] = []
    section_re = re.compile(r"^###\s+([^:]+):\s+(.+)$", re.M)
    for path in paths:
        text = path.read_text(encoding="utf-8")
        matches = list(section_re.finditer(text))
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end]
            signal_id = m.group(1).strip()
            title = m.group(2).strip()

            def field(name: str) -> str:
                fm = re.search(rf"^- {re.escape(name)}:\s*(.+)$", body, re.M)
                return fm.group(1).strip() if fm else ""

            ticker = field("ticker")
            if not ticker:
                # Batch 1 headers often start with the ticker.
                hm = re.match(r"([0-9]{4}|[0-9]{3}[A-Z])\s+", title)
                ticker = hm.group(1) if hm else ""
            if not re.match(r"^[0-9]{4}$|^[0-9]{3}[A-Z]$", ticker):
                continue
            signal_date_raw = field("signalDate")
            if not signal_date_raw:
                signal_date_raw = field("publishedAt")
            if not signal_date_raw:
                hm = re.search(r"(20\d{2}-\d{2}-\d{2})", signal_id)
                signal_date_raw = hm.group(1) if hm else ""
            dm = re.search(r"(20\d{2}-\d{2}-\d{2})", signal_date_raw)
            if not dm:
                continue
            signals.append(
                Signal(
                    signal_id=signal_id,
                    title=title,
                    ticker=ticker,
                    signal_date=dm.group(1),
                    category=field("disclosureCategory") or "unknown",
                    signal_type=field("signalType") or "unknown",
                    expected=field("expectedDirection") or "unknown",
                    long_rank=field("longSignalRank") or "unknown",
                    short_rank=field("shortSignalRank") or "unknown",
                    source_file=str(path.relative_to(ROOT / "topics/investment-research")),
                )
            )
    # Deduplicate by ticker + date + type; the same signal may be referenced in
    # a backfill, rerank, and outcome file.
    seen: set[tuple[str, str, str]] = set()
    out: list[Signal] = []
    for s in signals:
        key = (s.ticker, s.signal_date, s.signal_type)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def infer_signal_type_from_tdnet(title: str, category: str) -> str:
    c = (category or "").strip().lower()
    if c in {
        "offering_or_dilution",
        "downward_revision_dividend_cut",
        "weak_earnings_or_guidance",
        "upward_revision_highest_profit",
        "upward_revision_plus_dividend",
        "dividend_revision",
        "upward_revision",
    }:
        return c
    t = (title or "").strip()
    has_highest_profit = any(k in t for k in ["最高益", "過去最高益", "最高益更新"])
    has_downward = ("下方修正" in t) or ("業績予想の修正" in t and "上方修正" not in t)
    has_dividend_cut = any(k in t for k in ["減配", "無配", "配当予想の修正", "配当予想の取り下げ", "配当予想を未定"])
    if "上方修正" in t and has_highest_profit:
        return "upward_revision_highest_profit"
    if "上方修正" in t and ("増配" in t or "配当予想の修正" in t):
        return "upward_revision_plus_dividend"
    if "増配" in t and "配当予想の修正" in t:
        return "dividend_revision"
    if "上方修正" in t:
        return "upward_revision"
    if any(k in t for k in ["売出し", "売出", "自己株式処分", "公募", "第三者割当", "新株予約権"]):
        return "offering_or_dilution"
    if has_downward and has_dividend_cut:
        return "downward_revision_dividend_cut"
    if any(k in t for k in ["下方修正", "赤字", "減益", "未達", "下振れ", "営業損失", "経常損失", "最終損失", "最終赤字", "業績予想の修正"]):
        return "weak_earnings_or_guidance"
    return "unknown"


def infer_expected_direction(signal_type: str, fallback: str = "unknown") -> str:
    st = (signal_type or "").strip().lower()
    if st in {"offering_or_dilution", "downward_revision_dividend_cut", "weak_earnings_or_guidance", "downward_revision_to_loss", "downward_revision"}:
        return "down"
    if st in {"upward_revision_plus_dividend", "upward_revision", "dividend_revision", "highest_profit_guidance_dividend_revision", "upward_revision_highest_profit"}:
        return "up"
    return fallback or "unknown"


def parse_db_signals(db_path: Path, as_of: str, lookback_days: int) -> list[Signal]:
    if not db_path.exists():
        return []
    d0 = datetime.strptime(as_of, "%Y-%m-%d").date()
    min_date = (d0 - timedelta(days=max(0, lookback_days))).isoformat()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    out: list[Signal] = []
    try:
        sig_rows = conn.execute(
            """
            SELECT signal_id,date,ticker,signal_type,expected_direction,long_rank,short_rank
            FROM signals
            WHERE date BETWEEN ? AND ?
              AND COALESCE(ticker,'')<>''
            ORDER BY date DESC, signal_id DESC
            """,
            (min_date, as_of),
        ).fetchall()
        for r in sig_rows:
            ticker = str(r["ticker"] or "").strip()
            if not re.match(r"^[0-9]{4}$|^[0-9]{3}[A-Z]$", ticker):
                continue
            signal_date = str(r["date"] or "").strip()
            if not signal_date:
                continue
            out.append(
                Signal(
                    signal_id=str(r["signal_id"] or f"db_signal_{signal_date}_{ticker}"),
                    title=f"{ticker} {str(r['signal_type'] or '').strip()}",
                    ticker=ticker,
                    signal_date=signal_date,
                    category=infer_category("unknown", str(r["signal_type"] or "")),
                    signal_type=str(r["signal_type"] or "unknown").strip() or "unknown",
                    expected=str(r["expected_direction"] or "unknown").strip() or "unknown",
                    long_rank=str(r["long_rank"] or "C").strip() or "C",
                    short_rank=str(r["short_rank"] or "C").strip() or "C",
                    source_file="db:signals",
                )
            )

        td_rows = conn.execute(
            """
            SELECT date,ticker,title,category,source_kind
            FROM tdnet_disclosures
            WHERE date BETWEEN ? AND ?
              AND COALESCE(ticker,'')<>''
            ORDER BY date DESC
            """,
            (min_date, as_of),
        ).fetchall()
        for r in td_rows:
            ticker = str(r["ticker"] or "").strip()
            if not re.match(r"^[0-9]{4}$|^[0-9]{3}[A-Z]$", ticker):
                continue
            signal_date = str(r["date"] or "").strip()
            if not signal_date:
                continue
            signal_type = infer_signal_type_from_tdnet(str(r["title"] or ""), str(r["category"] or ""))
            out.append(
                Signal(
                    signal_id=f"tdnet_{signal_date}_{ticker}_{signal_type}",
                    title=f"{ticker} {str(r['title'] or '').strip()}",
                    ticker=ticker,
                    signal_date=signal_date,
                    category=infer_category(str(r["category"] or "unknown"), signal_type),
                    signal_type=signal_type,
                    expected=infer_expected_direction(signal_type, "unknown"),
                    long_rank="B" if str(r["source_kind"] or "").strip().startswith("tdnet") else "C",
                    short_rank="B" if infer_expected_direction(signal_type, "unknown") == "down" else "none",
                    source_file="db:tdnet_disclosures",
                )
            )
    finally:
        conn.close()
    seen: set[tuple[str, str, str]] = set()
    deduped: list[Signal] = []
    for s in out:
        key = (s.ticker, s.signal_date, s.signal_type)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(s)
    return deduped


def load_cache() -> dict:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except JSONDecodeError:
            # Corrupted cache file can happen after interrupted writes.
            # Keep evidence and continue with cold cache.
            ts = datetime.now(JST).strftime("%Y%m%d-%H%M%S")
            bad = CACHE.with_name(f"{CACHE.stem}.corrupt-{ts}{CACHE.suffix}")
            try:
                CACHE.rename(bad)
                print(f"[warn] cache json broken; moved to {display_path(bad)}")
            except Exception:
                pass
            return {}
        except MemoryError:
            # Fallback to cold cache when file is too large to read in memory.
            return {}
    return {}


def save_cache(cache: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    # Keep cache bounded to avoid OOM when serializing very large histories.
    max_entries = 5000
    if len(cache) > max_entries:
        keys = sorted(cache.keys())
        drop = len(cache) - max_entries
        for k in keys[:drop]:
            cache.pop(k, None)
    with CACHE.open("w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
        f.write("\n")


def has_ohlc(rows: list[dict]) -> bool:
    if not rows:
        return False
    return all(all(k in row for k in ("open", "high", "low", "close")) for row in rows[: min(3, len(rows))])


def epoch(date: str) -> int:
    dt = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=JST)
    return int(dt.timestamp())


def expected_last_available_date(end: str) -> str:
    """Expected latest date we should have in history at run time.

    Yahoo's period2 is exclusive-ish in practice, so use min(today, end-1day)
    as the freshness target for cached rows.
    """
    end_date = datetime.strptime(end, "%Y-%m-%d").date()
    target = min(datetime.now(JST).date(), end_date - timedelta(days=1))
    return target.strftime("%Y-%m-%d")


def is_cache_stale(rows: list[dict], end: str) -> bool:
    if not rows:
        return True
    last = rows[-1].get("date")
    if not last:
        return True
    return last < expected_last_available_date(end)


def fetch_prices_from_db(ticker: str, start: str, end: str, db_path: Path) -> list[dict]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT date, open, high, low, close, volume
            FROM facts_price_daily
            WHERE ticker = ?
              AND date BETWEEN ? AND ?
            ORDER BY date
            """,
            (ticker, start, end),
        ).fetchall()
        out: list[dict] = []
        for r in rows:
            if r["close"] is None:
                continue
            out.append(
                {
                    "date": str(r["date"]),
                    "open": float(r["open"]) if r["open"] is not None else float(r["close"]),
                    "high": float(r["high"]) if r["high"] is not None else float(r["close"]),
                    "low": float(r["low"]) if r["low"] is not None else float(r["close"]),
                    "close": float(r["close"]),
                    "volume": int(r["volume"]) if r["volume"] is not None else None,
                }
            )
        return out
    finally:
        conn.close()


def fetch_prices(ticker: str, start: str, end: str, cache: dict, cache_only: bool = False, db_path: Path | None = None) -> list[dict]:
    if db_path:
        db_rows = fetch_prices_from_db(ticker, start, end, db_path)
        if db_rows and has_ohlc(db_rows) and not is_cache_stale(db_rows, end):
            return db_rows
    for suffix in (".T", ".N", ".S", ".F"):
        symbol = f"{ticker}{suffix}"
        key = f"{symbol}:{start}:{end}"
        if key in cache and cache[key] and has_ohlc(cache[key]) and not is_cache_stale(cache[key], end):
            return cache[key]
        if key in cache and suffix != ".F" and has_ohlc(cache[key]) and not is_cache_stale(cache[key], end):
            continue
        if cache_only:
            continue
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
        adj = (result.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or []
        open_ = quote.get("open") or []
        high = quote.get("high") or []
        low = quote.get("low") or []
        close = quote.get("close") or []
        rows = []
        volume = quote.get("volume") or []
        for idx, ts in enumerate(timestamps):
            c = adj[idx] if idx < len(adj) and adj[idx] is not None else (close[idx] if idx < len(close) else None)
            if c is None or (isinstance(c, float) and math.isnan(c)):
                continue
            o = open_[idx] if idx < len(open_) and open_[idx] is not None else c
            h = high[idx] if idx < len(high) and high[idx] is not None else c
            l = low[idx] if idx < len(low) and low[idx] is not None else c
            v = volume[idx] if idx < len(volume) and volume[idx] is not None else None
            rows.append({
                "date": datetime.fromtimestamp(ts, JST).strftime("%Y-%m-%d"),
                "open": round(float(o), 4),
                "high": round(float(h), 4),
                "low": round(float(l), 4),
                "close": round(float(c), 4),
                "volume": int(v) if v is not None else None,
            })
        cache[key] = rows
        time.sleep(0.15)
        if rows:
            return rows
    return []


def add_months_rough(date: str, days: int) -> str:
    d = datetime.strptime(date, "%Y-%m-%d").date()
    return (d + timedelta(days=days)).strftime("%Y-%m-%d")


def compute_outcome(signal: Signal, cache: dict, cache_only: bool = False, db_path: Path | None = None) -> dict:
    start = add_months_rough(signal.signal_date, -7)
    end = add_months_rough(signal.signal_date, 45)
    try:
        rows = fetch_prices(signal.ticker, start, end, cache, cache_only=cache_only, db_path=db_path)
    except Exception as e:
        return {"status": "fetch_failed", "error": f"{type(e).__name__}: {e}"}
    base_idx = next((idx for idx, row in enumerate(rows) if row["date"] >= signal.signal_date), None)
    if base_idx is None:
        return {"status": "insufficient_prices", "rows": 0}
    future_rows = rows[base_idx:]
    if len(future_rows) < 2:
        return {"status": "insufficient_prices", "rows": len(future_rows)}
    base = future_rows[0]

    def nth(n: int) -> dict | None:
        return future_rows[n] if len(future_rows) > n else None

    def avg_volume(start_idx: int, length: int) -> float | None:
        slice_rows = rows[max(0, start_idx - length):start_idx]
        vols = [r.get("volume") for r in slice_rows if r.get("volume")]
        if not vols:
            return None
        return sum(vols) / len(vols)

    def vol_ratio(row: dict | None, avg: float | None) -> float | None:
        if not row or not avg or not row.get("volume"):
            return None
        return row["volume"] / avg

    def pct(row: dict | None) -> float | None:
        if not row:
            return None
        return (row["close"] / base["close"] - 1) * 100

    def pct_from_base(row: dict | None, price_key: str) -> float | None:
        if not row or not base.get("close") or not row.get(price_key):
            return None
        return (row[price_key] / base["close"] - 1) * 100

    def pct_close_vs_open(row: dict | None) -> float | None:
        if not row or not row.get("open"):
            return None
        return (row["close"] / row["open"] - 1) * 100

    def candle_metrics(row: dict | None) -> dict:
        if not row or not all(row.get(k) is not None for k in ("open", "high", "low", "close")):
            return {
                "candle": "unknown",
                "rangePct": None,
                "bodyPct": None,
                "upperWickPct": None,
                "lowerWickPct": None,
                "closeLocation": None,
                "closeVsOpenPct": None,
                "openVsBasePct": None,
                "highVsBasePct": None,
                "lowVsBasePct": None,
                "closeVsBasePct": None,
            }
        o = float(row["open"])
        h = float(row["high"])
        l = float(row["low"])
        c = float(row["close"])
        if o <= 0 or h <= l:
            candle = "range_unknown"
            close_location = None
        else:
            close_location = (c - l) / (h - l)
            body_pct = abs(c - o) / o * 100
            upper_wick_pct = (h - max(o, c)) / o * 100
            lower_wick_pct = (min(o, c) - l) / o * 100
            open_vs_base = pct_from_base(row, "open")
            close_vs_base = pct_from_base(row, "close")
            close_vs_open = pct_close_vs_open(row)
            if open_vs_base is not None and open_vs_base >= 2 and upper_wick_pct >= max(body_pct, 1.0) and close_location < 0.55:
                candle = "gap_up_upper_wick"
            elif open_vs_base is not None and open_vs_base <= -2 and lower_wick_pct >= max(body_pct, 1.0) and close_location > 0.45:
                candle = "gap_down_lower_wick_rebound"
            elif close_vs_base is not None and close_vs_base >= 3 and close_location >= 0.7 and c >= o:
                candle = "bullish_close"
            elif close_vs_base is not None and close_vs_base <= -3 and close_location <= 0.3 and c <= o:
                candle = "bearish_close"
            elif upper_wick_pct >= max(body_pct, 1.0) and close_location <= 0.45:
                candle = "upper_wick_reversal"
            elif lower_wick_pct >= max(body_pct, 1.0) and close_location >= 0.55:
                candle = "lower_wick_rebound"
            elif close_vs_open is not None and abs(close_vs_open) <= 0.5:
                candle = "doji_or_small_body"
            elif c > o:
                candle = "bullish_body"
            else:
                candle = "bearish_body"
            return {
                "candle": candle,
                "rangePct": (h - l) / o * 100,
                "bodyPct": body_pct,
                "upperWickPct": upper_wick_pct,
                "lowerWickPct": lower_wick_pct,
                "closeLocation": close_location,
                "closeVsOpenPct": close_vs_open,
                "openVsBasePct": open_vs_base,
                "highVsBasePct": pct_from_base(row, "high"),
                "lowVsBasePct": pct_from_base(row, "low"),
                "closeVsBasePct": close_vs_base,
            }
        return {
            "candle": candle,
            "rangePct": None,
            "bodyPct": None,
            "upperWickPct": None,
            "lowerWickPct": None,
            "closeLocation": close_location,
            "closeVsOpenPct": None,
            "openVsBasePct": pct_from_base(row, "open"),
            "highVsBasePct": pct_from_base(row, "high"),
            "lowVsBasePct": pct_from_base(row, "low"),
            "closeVsBasePct": pct_from_base(row, "close"),
        }

    def ret(row: dict | None) -> str:
        if not row:
            return "pending"
        pct_value = pct(row)
        return f"{row['date']} close {row['close']:.2f} ({pct_value:+.2f}%)"

    t1 = nth(1)
    t3 = nth(3)
    t5 = nth(5)
    t10 = nth(10)
    t20 = nth(20)
    avg5 = avg_volume(base_idx, 5)
    avg25 = avg_volume(base_idx, 25)
    t1_vol_ratio_5 = vol_ratio(t1, avg5)
    t1_vol_ratio_25 = vol_ratio(t1, avg25)
    t1_candle = candle_metrics(t1)
    returns = []
    for row in (t1, t3, t5, t10, t20):
        if row:
            returns.append((row["close"] / base["close"] - 1) * 100)
    if not returns:
        outcome_type = "pending"
    elif t20 and returns[-1] >= 8:
        outcome_type = "trend_continuation"
    elif t1 and ((t1["close"] / base["close"] - 1) * 100) >= 5 and t20 and returns[-1] <= 0:
        outcome_type = "initial_pop_only"
    elif t5 and ((t5["close"] / base["close"] - 1) * 100) <= -5:
        outcome_type = "failed_or_downtrend"
    elif t20 and abs(returns[-1]) < 3:
        outcome_type = "mean_reversion_or_no_edge"
    else:
        outcome_type = "mixed"
    return {
        "status": "ok",
        "base": f"{base['date']} close {base['close']:.2f}",
        "base_ohlc": f"{base['date']} O:{base.get('open'):.2f} H:{base.get('high'):.2f} L:{base.get('low'):.2f} C:{base.get('close'):.2f}",
        "T+1": ret(t1),
        "T+3": ret(t3),
        "T+5": ret(t5),
        "T+10": ret(t10),
        "T+20": ret(t20),
        "baseClosePrice": round(base["close"], 4),
        "baseVolume": base.get("volume"),
        "T+1Candle": t1_candle["candle"],
        "T+1OpenPrice": round(float(t1["open"]), 4) if t1 and t1.get("open") is not None else None,
        "T+1HighPrice": round(float(t1["high"]), 4) if t1 and t1.get("high") is not None else None,
        "T+1LowPrice": round(float(t1["low"]), 4) if t1 and t1.get("low") is not None else None,
        "T+1ClosePrice": round(float(t1["close"]), 4) if t1 else None,
        "T+3ClosePrice": round(float(t3["close"]), 4) if t3 else None,
        "T+5ClosePrice": round(float(t5["close"]), 4) if t5 else None,
        "T+10ClosePrice": round(float(t10["close"]), 4) if t10 else None,
        "T+20ClosePrice": round(float(t20["close"]), 4) if t20 else None,
        "T+1_pct": pct(t1),
        "T+3_pct": pct(t3),
        "T+5_pct": pct(t5),
        "T+10_pct": pct(t10),
        "T+20_pct": pct(t20),
        "T+1_volume": t1.get("volume") if t1 else None,
        "volumeAvg5BeforeSignal": round(avg5, 2) if avg5 else None,
        "volumeAvg25BeforeSignal": round(avg25, 2) if avg25 else None,
        "T+1_volumeRatio5": round(t1_vol_ratio_5, 2) if t1_vol_ratio_5 else None,
        "T+1_volumeRatio25": round(t1_vol_ratio_25, 2) if t1_vol_ratio_25 else None,
        "T+1OpenVsBasePct": round(t1_candle["openVsBasePct"], 2) if t1_candle["openVsBasePct"] is not None else None,
        "T+1HighVsBasePct": round(t1_candle["highVsBasePct"], 2) if t1_candle["highVsBasePct"] is not None else None,
        "T+1LowVsBasePct": round(t1_candle["lowVsBasePct"], 2) if t1_candle["lowVsBasePct"] is not None else None,
        "T+1CloseVsBasePct": round(t1_candle["closeVsBasePct"], 2) if t1_candle["closeVsBasePct"] is not None else None,
        "T+3CloseVsBasePct": round(pct(t3), 2) if t3 else None,
        "T+5CloseVsBasePct": round(pct(t5), 2) if t5 else None,
        "T+10CloseVsBasePct": round(pct(t10), 2) if t10 else None,
        "T+20CloseVsBasePct": round(pct(t20), 2) if t20 else None,
        "T+1CloseVsOpenPct": round(t1_candle["closeVsOpenPct"], 2) if t1_candle["closeVsOpenPct"] is not None else None,
        "T+1RangePct": round(t1_candle["rangePct"], 2) if t1_candle["rangePct"] is not None else None,
        "T+1BodyPct": round(t1_candle["bodyPct"], 2) if t1_candle["bodyPct"] is not None else None,
        "T+1UpperWickPct": round(t1_candle["upperWickPct"], 2) if t1_candle["upperWickPct"] is not None else None,
        "T+1LowerWickPct": round(t1_candle["lowerWickPct"], 2) if t1_candle["lowerWickPct"] is not None else None,
        "T+1CloseLocation": round(t1_candle["closeLocation"], 2) if t1_candle["closeLocation"] is not None else None,
        "outcomeType": outcome_type,
    }


def judge(expected: str, pct_value: float | None) -> str:
    if pct_value is None:
        return "pending"
    expected_l = expected.lower()
    if "context" in expected_l or "event" in expected_l:
        return "excluded_event_or_context"
    if "up" in expected_l:
        if pct_value >= 1:
            return "win"
        if pct_value <= -1:
            return "loss"
        return "flat"
    if "down" in expected_l:
        if pct_value <= -1:
            return "win"
        if pct_value >= 1:
            return "loss"
        return "flat"
    if "neutral" in expected_l or "unclear" in expected_l:
        return "win" if abs(pct_value) <= 3 else "loss"
    return "unjudged"


def infer_category(category: str, signal_type: str) -> str:
    if category and category != "unknown":
        return category
    st = signal_type.lower()
    if "downward" in st or "dividend_cut" in st or "weak" in st or "red" in st:
        return "earnings_negative"
    if "earnings" in st or "upward" in st or "highest_profit" in st:
        return "earnings_positive"
    if "dividend" in st and "cut" not in st:
        return "dividend_return"
    if "buyback" in st or "cancellation" in st or "tostnet" in st:
        return "dividend_return"
    if "tob" in st or "mbo" in st:
        return "ma_tob_mbo"
    if "capital_policy" in st or "third_party" in st or "offering" in st or "dilution" in st:
        return "capital_policy"
    if "large_order" in st or "partnership" in st:
        return "business_event"
    if "monthly" in st:
        return "monthly_kpi"
    return category or "unknown"


def build_aggregation(rows: list[tuple[Signal, dict]], date: str, source_log: str) -> str:
    from collections import Counter, defaultdict

    windows = ["T+1", "T+3", "T+5", "T+10", "T+20"]
    total_by_window = {w: Counter() for w in windows}
    category_by_window: dict[str, dict[str, Counter]] = {w: defaultdict(Counter) for w in windows}
    rank_by_window: dict[str, dict[str, Counter]] = {w: defaultdict(Counter) for w in windows}
    outcome_types = Counter()

    for signal, outcome in rows:
        if outcome.get("status") != "ok":
            continue
        outcome_types[outcome.get("outcomeType", "unknown")] += 1
        for w in windows:
            result = judge(signal.expected, outcome.get(f"{w}_pct"))
            total_by_window[w][result] += 1
            category_by_window[w][signal.category][result] += 1
            rank_key = f"long:{signal.long_rank}/short:{signal.short_rank}"
            rank_by_window[w][rank_key][result] += 1

    lines = [
        f"# {date} Rough Backtest Win Loss Aggregation",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {date}",
        "- mode: rough-win-loss-aggregation",
        f"- sourceLog: {source_log}",
        "- method: `up` は +1%以上でwin、`down` は -1%以下でwin、`neutral/unclear` は絶対値3%以内でwin。event/contextは勝敗から除外。",
        "- caution: Yahoo Finance日足終値による粗集計。発表時刻、場中織り込み、TOB裁定、流動性は未補正。売買助言ではない。",
        "",
        "## Summary",
        f"- outcomeRows: {sum(1 for _, o in rows if o.get('status') == 'ok')}",
        "",
        "## Outcome Type Counts",
    ]
    for key, value in outcome_types.most_common():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Window Win Loss Counts"])
    for w in windows:
        c = total_by_window[w]
        judged = c["win"] + c["loss"] + c["flat"]
        win_rate = (c["win"] / judged * 100) if judged else 0
        lines.append(f"- {w}: win={c['win']}, loss={c['loss']}, flat={c['flat']}, excluded={c['excluded_event_or_context']}, unjudged={c['unjudged']}, winRate={win_rate:.1f}%")

    lines.extend(["", "## Category Win Loss Counts"])
    for w in windows:
        lines.append(f"### {w}")
        for category, counter in sorted(category_by_window[w].items()):
            judged = counter["win"] + counter["loss"] + counter["flat"]
            if not judged and not counter["excluded_event_or_context"]:
                continue
            win_rate = (counter["win"] / judged * 100) if judged else 0
            lines.append(
                f"- {category}: win={counter['win']}, loss={counter['loss']}, flat={counter['flat']}, excluded={counter['excluded_event_or_context']}, winRate={win_rate:.1f}%"
            )

    lines.extend(["", "## Rank Win Loss Counts"])
    for w in windows:
        lines.append(f"### {w}")
        for rank, counter in sorted(rank_by_window[w].items()):
            judged = counter["win"] + counter["loss"] + counter["flat"]
            if judged < 2:
                continue
            win_rate = (counter["win"] / judged * 100) if judged else 0
            lines.append(f"- {rank}: win={counter['win']}, loss={counter['loss']}, flat={counter['flat']}, excluded={counter['excluded_event_or_context']}, winRate={win_rate:.1f}%")

    lines.extend([
        "",
        "## Early Read",
        "- T+1/T+5/T+20 を分けると、短期で当たってもT+20で崩れるもの、短期で外れてT+20で戻るものが混在する。",
        "- `event/context` は通常の勝敗から除外し、TOBサヤ寄せや市場背景として別管理する。",
        "- `neutral/unclear` は動かなければ勝ちという扱いにしたため、方向シグナルとは別枠で読む。",
        "- 次は発表時刻、外部地合い、出来高、信用残で層別する。",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Fill rough T+1/T+5/T+20 outcomes.")
    parser.add_argument("inputs", nargs="*", type=Path, help="Seed markdown files. Defaults to known backtest source logs.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    parser.add_argument("--seed-config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--seed-list", default=None)
    parser.add_argument("--cache-only", action="store_true", help="Use existing Yahoo cache only; do not fetch network data.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite DB path for optional signal/tdnet backfill seeds.")
    parser.add_argument("--include-db-signals", action="store_true", help="Include `signals` and `tdnet_disclosures` rows as seed candidates.")
    parser.add_argument("--db-lookback-days", type=int, default=30, help="Lookback days for DB-derived seeds.")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--aggregation-output", type=Path, default=None)
    args = parser.parse_args()

    output = args.output or Path(str(DEFAULT_OUTPUT).format(date=args.date))
    aggregation_output = args.aggregation_output or Path(str(DEFAULT_AGGREGATION_OUTPUT).format(date=args.date))
    paths = args.inputs or load_seed_paths(args.seed_config, args.seed_list)
    try:
        source_log = output.relative_to(ROOT / "topics/investment-research")
    except ValueError:
        source_log = output
    signals = parse_signals(paths)
    db_added = 0
    if args.include_db_signals:
        db_signals = parse_db_signals(args.db, args.date, args.db_lookback_days)
        db_added = len(db_signals)
        signals.extend(db_signals)
        seen: set[tuple[str, str, str]] = set()
        deduped: list[Signal] = []
        for s in signals:
            key = (s.ticker, s.signal_date, s.signal_type)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(s)
        signals = deduped
    cache = load_cache()
    lines = [
        f"# {args.date} Rough Backtest Outcomes Batch 1",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {args.date}",
        "- mode: rough-outcome-fill",
        "- sourceData: Yahoo Finance chart API via query1.finance.yahoo.com",
        f"- cacheOnly: {args.cache_only}",
        f"- includeDbSignals: {args.include_db_signals}",
        f"- dbLookbackDays: {args.db_lookback_days}",
        "- method: signalDate以降の最初の取引日終値をbaseとし、T+1/T+3/T+5/T+10/T+20営業日後の調整後終値を比較。T+1はOHLCから寄り付きギャップ、ヒゲ、引け位置を粗分類する。",
        "- caution: 発表時刻、場中織り込み、分割/配当調整、TOBイベント、流動性は未精査の粗計算。売買助言ではない。",
        "",
        "## Summary",
        f"- parsedSignals: {len(signals)}",
        f"- dbDerivedSignalsBeforeDedup: {db_added}",
    ]
    ok = 0
    failed = 0
    computed_rows: list[tuple[Signal, dict]] = []
    rows_md: list[str] = []
    for idx, signal in enumerate(signals, 1):
        outcome = compute_outcome(signal, cache, cache_only=args.cache_only, db_path=args.db)
        if outcome.get("status") == "ok":
            ok += 1
        else:
            failed += 1
        computed_rows.append((signal, outcome))
        rows_md.extend([
            f"### outcome_{args.date.replace('-', '')}_{idx:03d}: {signal.ticker} {signal.title}",
            f"- sourceSignalId: {signal.signal_id}",
            f"- sourceLog: {signal.source_file}",
            f"- signalDate: {signal.signal_date}",
            f"- disclosureCategory: {infer_category(signal.category, signal.signal_type)}",
            f"- originalDisclosureCategory: {signal.category}",
            f"- signalType: {signal.signal_type}",
            f"- expectedDirection: {signal.expected}",
            f"- longSignalRank: {signal.long_rank}",
            f"- shortSignalRank: {signal.short_rank}",
            f"- outcomeStatus: {outcome.get('status')}",
        ])
        if outcome.get("status") == "ok":
            rows_md.extend([
                f"- base: {outcome['base']}",
                f"- baseOHLC: {outcome['base_ohlc']}",
                f"- baseClosePrice: {outcome.get('baseClosePrice')}",
                f"- baseVolume: {outcome.get('baseVolume')}",
                f"- T+1: {outcome['T+1']}",
                f"- T+3: {outcome['T+3']}",
                f"- T+5: {outcome['T+5']}",
                f"- T+10: {outcome['T+10']}",
                f"- T+20: {outcome['T+20']}",
                f"- T+1Candle: {outcome.get('T+1Candle')}",
                f"- T+1OpenPrice: {outcome.get('T+1OpenPrice')}",
                f"- T+1HighPrice: {outcome.get('T+1HighPrice')}",
                f"- T+1LowPrice: {outcome.get('T+1LowPrice')}",
                f"- T+1ClosePrice: {outcome.get('T+1ClosePrice')}",
                f"- T+3ClosePrice: {outcome.get('T+3ClosePrice')}",
                f"- T+5ClosePrice: {outcome.get('T+5ClosePrice')}",
                f"- T+10ClosePrice: {outcome.get('T+10ClosePrice')}",
                f"- T+20ClosePrice: {outcome.get('T+20ClosePrice')}",
                f"- T+1Judge: {judge(signal.expected, outcome.get('T+1_pct'))}",
                f"- T+3Judge: {judge(signal.expected, outcome.get('T+3_pct'))}",
                f"- T+5Judge: {judge(signal.expected, outcome.get('T+5_pct'))}",
                f"- T+10Judge: {judge(signal.expected, outcome.get('T+10_pct'))}",
                f"- T+20Judge: {judge(signal.expected, outcome.get('T+20_pct'))}",
                f"- volumeContext:",
                f"  - baseVolume: {outcome.get('baseVolume')}",
                f"  - T+1Volume: {outcome.get('T+1_volume')}",
                f"  - volumeAvg5BeforeSignal: {outcome.get('volumeAvg5BeforeSignal')}",
                f"  - volumeAvg25BeforeSignal: {outcome.get('volumeAvg25BeforeSignal')}",
                f"  - T+1VolumeRatio5: {outcome.get('T+1_volumeRatio5')}",
                f"  - T+1VolumeRatio25: {outcome.get('T+1_volumeRatio25')}",
                f"- priceActionContext:",
                f"  - T+1OpenVsBasePct: {outcome.get('T+1OpenVsBasePct')}",
                f"  - T+1HighVsBasePct: {outcome.get('T+1HighVsBasePct')}",
                f"  - T+1LowVsBasePct: {outcome.get('T+1LowVsBasePct')}",
                f"  - T+1CloseVsBasePct: {outcome.get('T+1CloseVsBasePct')}",
                f"  - T+3CloseVsBasePct: {outcome.get('T+3CloseVsBasePct')}",
                f"  - T+5CloseVsBasePct: {outcome.get('T+5CloseVsBasePct')}",
                f"  - T+10CloseVsBasePct: {outcome.get('T+10CloseVsBasePct')}",
                f"  - T+20CloseVsBasePct: {outcome.get('T+20CloseVsBasePct')}",
                f"  - T+1CloseVsOpenPct: {outcome.get('T+1CloseVsOpenPct')}",
                f"  - T+1RangePct: {outcome.get('T+1RangePct')}",
                f"  - T+1BodyPct: {outcome.get('T+1BodyPct')}",
                f"  - T+1UpperWickPct: {outcome.get('T+1UpperWickPct')}",
                f"  - T+1LowerWickPct: {outcome.get('T+1LowerWickPct')}",
                f"  - T+1CloseLocation: {outcome.get('T+1CloseLocation')}",
                f"- roughOutcomeType: {outcome['outcomeType']}",
            ])
        else:
            rows_md.append(f"- unresolved: {outcome}")
        rows_md.append("")
    lines.extend([f"- outcomesFilled: {ok}", f"- failedOrSkipped: {failed}", "", "## Outcomes", ""])
    lines.extend(rows_md)
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    aggregation_output.write_text(build_aggregation(computed_rows, args.date, str(source_log)), encoding="utf-8")
    save_cache(cache)
    print(f"wrote {display_path(output)}")
    print(f"wrote {display_path(aggregation_output)}")
    print(f"parsed={len(signals)} ok={ok} failed={failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
