#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db
from utils.pipeline_events import write_pipeline_event
from utils.sector_inference import resolve_sector_label

INBOX = ROOT / "topics" / "investment-research" / "inbox"
DEFAULT_DB = resolve_investment_db()
HEAD_RE = re.compile(r"^###\s+([^:]+):\s*(.+)$", re.M)
FIELD_RE = re.compile(r"^-\s+([A-Za-z0-9+_-]+):\s*(.*)$")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build opening trading scenarios from entry candidates")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--fallback-days", type=int, default=3)
    p.add_argument("--risk-per-trade-jpy", type=int, default=5000)
    p.add_argument("--max-candidates", type=int, default=6)
    p.add_argument("--min-long", type=int, default=2, help="minimum long scenarios for trade mode")
    p.add_argument("--min-short", type=int, default=2, help="minimum short scenarios for trade mode")
    p.add_argument("--min-rule-hits", type=int, default=5, help="minimum rule hit count for publish gate")
    p.add_argument("--min-score", type=int, default=70, help="minimum scenarioScore for publish gate")
    p.add_argument("--min-winrate", type=float, default=50.0, help="minimum estimated winrate for publish gate")
    p.add_argument("--min-winrate-samples", type=int, default=1, help="minimum sample count required for trade tier")
    p.add_argument("--paper-trade-max-samples", type=int, default=2, help="max sample count for paper-trade-only tier")
    p.add_argument("--paper-promote-min-trades", type=int, default=5, help="min historical paper trades for promotion to trade")
    p.add_argument("--paper-promote-min-winrate", type=float, default=55.0, help="min T+5 win rate (%) for promotion")
    p.add_argument("--paper-promote-min-ev", type=float, default=0.2, help="min T+5 expected value (%) for promotion")
    p.add_argument("--paper-promote-max-dd", type=float, default=-8.0, help="max allowed drawdown (%) for promotion")
    p.add_argument("--paper-promote-lookback-days", type=int, default=60, help="lookback window for paper promotion stats")
    p.add_argument("--min-winrate-samples-soft", type=int, default=3, help="sample count where winrate is treated as stable (display/penalty use)")
    p.add_argument("--n1-min-score", type=int, default=90, help="minimum score for n=1 trade allowance")
    p.add_argument("--n1-min-winrate", type=float, default=70.0, help="minimum winrate for n=1 trade allowance")
    p.add_argument("--allow-unknown-winrate", action="store_true", help="allow scenarios with unknown winrate (for testing/backfill phases)")
    p.add_argument("--auto-relax-gate", action="store_true", help="auto relax quality gate only when accepted scenarios are insufficient")
    p.add_argument("--auto-relax-steps", type=int, default=3, help="max relax attempts when auto-relax-gate is enabled")
    p.add_argument("--relax-min-rule-hits-floor", type=int, default=3, help="lower bound of min-rule-hits during auto relax")
    p.add_argument("--relax-min-score-floor", type=int, default=62, help="lower bound of min-score during auto relax")
    p.add_argument("--relax-min-winrate-floor", type=float, default=46.0, help="lower bound of min-winrate during auto relax")
    p.add_argument("--soft-gate", action="store_true", help="demote weak scenarios to watch instead of hard reject")
    p.add_argument("--soft-min-score", type=int, default=55, help="minimum score to keep scenario as watch in soft gate")
    p.add_argument("--soft-min-rule-hits", type=int, default=2, help="minimum rule hits to keep scenario as watch in soft gate")
    p.add_argument("--adaptive-side-minimum", action="store_true", help="relax min long/short when one side has structurally low candidates")
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite DB path (DB-first source)")
    return p.parse_args()


def load_entry_candidates_from_db(db_path: Path, date_str: str, fallback_days: int) -> tuple[dict | None, str | None]:
    if not db_path.exists():
        return None, None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
        for i in range(0, max(0, fallback_days) + 1):
            d = (d0 - timedelta(days=i)).isoformat()
            rows = conn.execute(
                """
                SELECT side,candidate_type,signal_id,ticker,company,expected_direction,long_rank,short_rank,trade_use,url,gate_status,
                       material_signal_checked,external_context_checked,technical_signal_checked,score
                FROM entry_candidates
                WHERE date=?
                ORDER BY side,candidate_type,COALESCE(score,0) DESC,signal_id
                """,
                (d,),
            ).fetchall()
            if not rows:
                continue

            out = {
                "date": d,
                "sourceDate": d,
                "source": "db:entry_candidates",
                "longEntryCandidates": [],
                "shortEntryCandidates": [],
                "longWatchCandidates": [],
                "shortWatchCandidates": [],
            }
            for r in rows:
                item = {
                    "signalId": r["signal_id"] or "",
                    "ticker": r["ticker"] or "",
                    "company": r["company"] or "",
                    "expectedDirection": r["expected_direction"] or "",
                    "longSignalRank": r["long_rank"] or "",
                    "shortSignalRank": r["short_rank"] or "",
                    "tradeUse": r["trade_use"] or "",
                    "url": r["url"] or "",
                    "gateStatus": r["gate_status"] or "",
                    "materialSignalChecked": r["material_signal_checked"] or "",
                    "externalContextChecked": r["external_context_checked"] or "",
                    "technicalSignalChecked": r["technical_signal_checked"] or "",
                    "candidateType": r["candidate_type"] or "primary",
                    "score": str(r["score"] or 0),
                }
                side = r["side"] or ""
                ctype = r["candidate_type"] or "primary"
                if side == "long" and ctype == "primary":
                    out["longEntryCandidates"].append(item)
                elif side == "short" and ctype == "primary":
                    out["shortEntryCandidates"].append(item)
                elif side == "long":
                    out["longWatchCandidates"].append(item)
                elif side == "short":
                    out["shortWatchCandidates"].append(item)
            return out, d
    finally:
        conn.close()
    return None, None


def load_signal_map_from_db(db_path: Path, date_str: str, fallback_days: int) -> tuple[dict[str, dict[str, str]], str | None]:
    if not db_path.exists():
        return {}, None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
        for i in range(0, max(0, fallback_days) + 1):
            d = (d0 - timedelta(days=i)).isoformat()
            rows = conn.execute(
                """
                SELECT signal_id,signal_type,source,session,url,gate_status,material_signal_checked,external_context_checked,technical_signal_checked,
                       credit_status,credit_buy_status,credit_sell_status,credit_source_kind,credit_source_date,credit_freshness_hours
                FROM signals
                WHERE date=?
                """,
                (d,),
            ).fetchall()
            if not rows:
                continue
            out: dict[str, dict[str, str]] = {}
            for r in rows:
                sid = r["signal_id"] or ""
                if not sid:
                    continue
                out[sid] = {
                    "signalType": r["signal_type"] or "",
                    "source": r["source"] or "",
                    "session": r["session"] or "",
                    "url": r["url"] or "",
                    "gateStatus": r["gate_status"] or "",
                    "materialSignalChecked": r["material_signal_checked"] or "",
                    "externalContextChecked": r["external_context_checked"] or "",
                    "technicalSignalChecked": r["technical_signal_checked"] or "",
                    "borrowStatus": r["credit_status"] or "",
                    "buyStatus": r["credit_buy_status"] or "",
                    "sellStatus": r["credit_sell_status"] or "",
                    "creditSourceKind": r["credit_source_kind"] or "",
                    "creditSourceDate": r["credit_source_date"] or "",
                    "creditFreshnessHours": r["credit_freshness_hours"] if r["credit_freshness_hours"] is not None else "",
                }
            return out, d
    finally:
        conn.close()
    return {}, None


def load_ticker_context_from_db(db_path: Path, date_str: str, fallback_days: int) -> dict[str, dict[str, str]]:
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(db_path)
    try:
        out: dict[str, dict[str, str]] = {}
        d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
        for i in range(0, max(0, fallback_days) + 1):
            d = (d0 - timedelta(days=i)).isoformat()
            sec_rows = conn.execute(
                "SELECT ticker, sector_group FROM sector_context_rows WHERE date=?",
                (d,),
            ).fetchall()
            for t, sec in sec_rows:
                tt = str(t or "").strip()
                if not tt:
                    continue
                out.setdefault(tt, {})["sector"] = str(sec or "").strip()

            credit_rows = conn.execute(
                "SELECT ticker, credit_status, buy_status, sell_status FROM credit_status_rows WHERE date=?",
                (d,),
            ).fetchall()
            for t, cs, buy_s, sell_s in credit_rows:
                tt = str(t or "").strip()
                if not tt:
                    continue
                out.setdefault(tt, {})["borrow_status"] = str(cs or "").strip()
                out.setdefault(tt, {})["buy_status"] = str(buy_s or "").strip()
                out.setdefault(tt, {})["sell_status"] = str(sell_s or "").strip()

            bor_rows = conn.execute(
                "SELECT ticker, borrow_status FROM short_readiness_rows WHERE date=?",
                (d,),
            ).fetchall()
            for t, bor in bor_rows:
                tt = str(t or "").strip()
                if not tt:
                    continue
                cur = out.setdefault(tt, {}).get("borrow_status", "")
                # Keep manual credit feedback as highest priority.
                if str(cur).startswith("manual_"):
                    continue
                out.setdefault(tt, {})["borrow_status"] = str(bor or "").strip()

            mkt_rows = conn.execute(
                """
                SELECT ticker, market_context, confidence, topix_pct
                FROM market_context_rows
                WHERE date=?
                """,
                (d,),
            ).fetchall()
            for t, mctx, conf, topix_pct in mkt_rows:
                tt = str(t or "").strip()
                if not tt:
                    continue
                out.setdefault(tt, {})["market_context"] = str(mctx or "").strip()
                out.setdefault(tt, {})["market_confidence"] = str(conf or "").strip()
                out.setdefault(tt, {})["topix_pct"] = topix_pct if topix_pct is not None else ""

            sm_rows = conn.execute(
                """
                SELECT ticker, relative_to_topix_pct, sector_market_context
                FROM sector_market_context_rows
                WHERE date=?
                """,
                (d,),
            ).fetchall()
            for t, rel_topix, smctx in sm_rows:
                tt = str(t or "").strip()
                if not tt:
                    continue
                out.setdefault(tt, {})["relative_to_topix_pct"] = rel_topix if rel_topix is not None else ""
                out.setdefault(tt, {})["sector_market_context"] = str(smctx or "").strip()
            if out:
                break
        return out
    finally:
        conn.close()


def _is_blocked_status(v: str) -> bool:
    s = (v or "").strip().lower()
    if not s or s == "unknown":
        return True
    if s in {"ok", "manual_marginable"}:
        return False
    if s in {"ng", "manual_non_marginable", "manual_unknown"}:
        return True
    bad_tokens = ["不可", "対象外", "なし", "no", "ng", "×", "✕", "x"]
    return any(tok in s for tok in bad_tokens)


def _is_unknown_status(v: str) -> bool:
    s = (v or "").strip().lower()
    if not s:
        return True
    return s in {"unknown", "auto_unknown", "manual_unknown", "pending", "n/a"}


def _prefer_fresher_credit(base_v: str, fallback_v: str) -> str:
    b = (base_v or "").strip()
    f = (fallback_v or "").strip()
    if _is_unknown_status(b) and f:
        return f
    return b or f


def _reason_code(reason: str) -> str:
    s = str(reason or "").strip()
    if s.startswith("sampleCount<="):
        return "SAMPLE_LOW_PAPER_ONLY"
    if s.startswith("ruleHits<"):
        return "RULE_HITS_LT"
    if s.startswith("score<"):
        return "SCORE_LT"
    if s.startswith("sampleCount<"):
        return "SAMPLE_COUNT_LT"
    if s.startswith("winRate<"):
        return "WIN_RATE_LT"
    if s == "winRate_unknown":
        return "WIN_RATE_UNKNOWN"
    if s.startswith("n1_not_strong"):
        return "N1_NOT_STRONG"
    if s.startswith("credit_unknown:"):
        return "CREDIT_UNKNOWN"
    if s.startswith("credit_unavailable:"):
        return "CREDIT_UNAVAILABLE"
    if s.startswith("sampleCount=0 -> watch"):
        return "SAMPLE_ZERO_WATCH"
    if s.startswith("manualCreditOverride"):
        return "MANUAL_CREDIT_OVERRIDE"
    if s.startswith("AGGR_"):
        return "AGGRESSIVENESS"
    return "OTHER"


def _is_placeholder_company(v: str) -> bool:
    s = (v or "").strip()
    if not s:
        return True
    return s.upper() in {"不明", "-", "N/A", "NA", "UNKNOWN"}


def load_company_name_map_from_db(db_path: Path, date_str: str, fallback_days: int) -> dict[str, str]:
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        out: dict[str, str] = {}
        d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
        start = (d0 - timedelta(days=max(1, int(fallback_days)) - 1)).isoformat()
        end = date_str

        # 1) signals: most recent non-placeholder company by ticker
        rows = conn.execute(
            """
            SELECT s.ticker,s.company
            FROM signals s
            INNER JOIN (
              SELECT ticker, MAX(date || ' ' || COALESCE(signal_id,'')) AS k
              FROM signals
              WHERE date BETWEEN ? AND ?
              GROUP BY ticker
            ) latest
              ON latest.ticker=s.ticker
             AND latest.k=(s.date || ' ' || COALESCE(s.signal_id,''))
            """,
            (start, end),
        ).fetchall()
        for r in rows:
            t = str(r["ticker"] or "").strip()
            c = str(r["company"] or "").strip()
            if not t or _is_placeholder_company(c):
                continue
            out[t] = c

        # 2) tdnet_disclosures fallback
        rows = conn.execute(
            """
            SELECT t.ticker,t.company
            FROM tdnet_disclosures t
            INNER JOIN (
              SELECT ticker, MAX(date || ' ' || COALESCE(disclosed_at,'')) AS k
              FROM tdnet_disclosures
              WHERE date BETWEEN ? AND ?
              GROUP BY ticker
            ) latest
              ON latest.ticker=t.ticker
             AND latest.k=(t.date || ' ' || COALESCE(t.disclosed_at,''))
            """,
            (start, end),
        ).fetchall()
        for r in rows:
            t = str(r["ticker"] or "").strip()
            if not t or t in out:
                continue
            c = str(r["company"] or "").strip()
            if _is_placeholder_company(c):
                continue
            out[t] = c

        # 3) instruments fallback
        rows = conn.execute("SELECT ticker,name FROM instruments").fetchall()
        for r in rows:
            t = str(r["ticker"] or "").strip()
            if not t or t in out:
                continue
            c = str(r["name"] or "").strip()
            if _is_placeholder_company(c):
                continue
            out[t] = c

        return out
    finally:
        conn.close()


def is_non_marginable_for_direction(direction: str, borrow_status: str, buy_status: str = "", sell_status: str = "") -> bool:
    dir_s = (direction or "").strip().lower()
    if dir_s == "short":
        # Short must satisfy sell availability.
        if (sell_status or "").strip():
            return _is_blocked_status(sell_status)
        return _is_blocked_status(borrow_status)
    # Long should be judged by buy availability.
    if (buy_status or "").strip():
        return _is_blocked_status(buy_status)
    return _is_blocked_status(borrow_status)


def load_rule_rows_from_db(db_path: Path, date_str: str, fallback_days: int) -> tuple[list[dict], str | None]:
    if not db_path.exists():
        return [], None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
        for i in range(0, max(0, fallback_days) + 1):
            d = (d0 - timedelta(days=i)).isoformat()
            rows = conn.execute(
                "SELECT side,bucket,status,appearances,t1,t5,t20 FROM rule_dashboard_rows WHERE date=?",
                (d,),
            ).fetchall()
            if not rows:
                continue
            return [dict(r) for r in rows], d
    finally:
        conn.close()
    return [], None


def load_sample_hints_from_outcomes(db_path: Path, date_str: str, fallback_days: int) -> tuple[dict[tuple[str, str], int], str | None]:
    if not db_path.exists():
        return {}, None
    conn = sqlite3.connect(db_path)
    try:
        d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
        for i in range(0, max(0, fallback_days) + 1):
            d = (d0 - timedelta(days=i)).isoformat()
            rows = conn.execute(
                """
                SELECT signal_type, expected_direction,
                       SUM(
                         CASE
                           WHEN COALESCE(t1_judge,'') NOT IN ('', 'pending', 'unjudged') THEN 1
                           WHEN COALESCE(t5_judge,'') NOT IN ('', 'pending', 'unjudged') THEN 1
                           WHEN COALESCE(t20_judge,'') NOT IN ('', 'pending', 'unjudged') THEN 1
                           ELSE 0
                         END
                       ) AS judged_count
                FROM backtest_outcomes
                WHERE date=?
                GROUP BY signal_type, expected_direction
                """,
                (d,),
            ).fetchall()
            if not rows:
                continue
            out: dict[tuple[str, str], int] = {}
            for st, ed, n in rows:
                key = (str(st or "").strip(), str(ed or "").strip())
                out[key] = int(n or 0)
            return out, d
    finally:
        conn.close()
    return {}, None


def load_board_snapshot_from_db(db_path: Path, date_str: str, fallback_days: int) -> tuple[dict[str, dict], str | None]:
    if not db_path.exists():
        return {}, None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
        for i in range(0, max(0, fallback_days) + 1):
            d = (d0 - timedelta(days=i)).isoformat()
            rows = conn.execute(
                """
                SELECT ticker,company,best_bid,best_ask,indicative_open
                FROM board_snapshots
                WHERE date=?
                """,
                (d,),
            ).fetchall()
            if not rows:
                continue
            out: dict[str, dict] = {}
            for r in rows:
                t = str(r["ticker"] or "").strip()
                if not t:
                    continue
                out[t] = {
                    "ticker": t,
                    "company": r["company"] or "",
                    "bestBid": r["best_bid"],
                    "bestAsk": r["best_ask"],
                    "indicativeOpen": r["indicative_open"],
                }
            return out, d
    finally:
        conn.close()
    return {}, None


def load_market_snapshot_from_db(db_path: Path, date_str: str, fallback_days: int) -> tuple[dict[str, dict], str | None]:
    if not db_path.exists():
        return {}, None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
        for i in range(0, max(0, fallback_days) + 1):
            d = (d0 - timedelta(days=i)).isoformat()
            try:
                rows = conn.execute(
                    """
                    SELECT m.ticker,m.slot,m.snapshot_time,m.price,m.vwap,m.vwap_gap_pct,m.return_pct,m.volume,m.volume_ratio
                    FROM market_signal_snapshots m
                    INNER JOIN (
                      SELECT ticker, MAX(snapshot_time) AS max_snapshot_time
                      FROM market_signal_snapshots
                      WHERE date=?
                      GROUP BY ticker
                    ) latest
                      ON latest.ticker = m.ticker
                     AND latest.max_snapshot_time = m.snapshot_time
                    WHERE m.date=?
                    """,
                    (d, d),
                ).fetchall()
            except sqlite3.OperationalError:
                return {}, None
            if not rows:
                continue
            out: dict[str, dict] = {}
            for r in rows:
                t = str(r["ticker"] or "").strip()
                if not t:
                    continue
                out[t] = {
                    "slot": r["slot"],
                    "snapshotTime": r["snapshot_time"],
                    "price": r["price"],
                    "vwap": r["vwap"],
                    "vwapGapPct": r["vwap_gap_pct"],
                    "returnPct": r["return_pct"],
                    "volume": r["volume"],
                    "volumeRatio": r["volume_ratio"],
                }
            return out, d
    finally:
        conn.close()
    return {}, None


def _compute_execution_feasibility(board: dict | None, market_snap: dict | None) -> tuple[int | None, dict]:
    if not board and not market_snap:
        return None, {"status": "unknown", "reasons": ["board_and_market_snapshot_missing"]}

    score = 50
    reasons: list[str] = []
    spread_bps = None
    gap_pct = None
    vol_ratio = None
    intraday_ret = None

    if board:
        bid = board.get("bestBid")
        ask = board.get("bestAsk")
        iop = board.get("indicativeOpen")
        if isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and bid > 0 and ask > 0:
            mid = (float(bid) + float(ask)) / 2.0
            spread_bps = ((float(ask) - float(bid)) / mid) * 10000.0 if mid > 0 else None
            if spread_bps is not None:
                if spread_bps <= 10:
                    score += 20
                    reasons.append("tight_spread")
                elif spread_bps <= 30:
                    score += 8
                elif spread_bps >= 80:
                    score -= 20
                    reasons.append("wide_spread")
            if isinstance(iop, (int, float)) and mid > 0:
                gap_pct = abs((float(iop) / mid - 1.0) * 100.0)
                if gap_pct <= 0.5:
                    score += 8
                elif gap_pct >= 2.0:
                    score -= 10
                    reasons.append("large_open_gap")

    if market_snap:
        try:
            vol_ratio = float(market_snap.get("volumeRatio")) if market_snap.get("volumeRatio") is not None else None
        except Exception:
            vol_ratio = None
        try:
            intraday_ret = abs(float(market_snap.get("returnPct"))) if market_snap.get("returnPct") is not None else None
        except Exception:
            intraday_ret = None
        if vol_ratio is not None:
            if vol_ratio >= 2.0:
                score += 18
                reasons.append("volume_follow_through")
            elif vol_ratio >= 1.2:
                score += 8
            elif vol_ratio < 0.6:
                score -= 10
                reasons.append("thin_volume")
        if intraday_ret is not None:
            if intraday_ret >= 5.0:
                score -= 12
                reasons.append("intraday_volatility_high")
            elif intraday_ret <= 1.0:
                score += 4

    final_score = max(0, min(100, int(round(score))))
    return final_score, {
        "status": "ok",
        "spreadBps": round(spread_bps, 2) if spread_bps is not None else None,
        "openGapAbsPct": round(gap_pct, 3) if gap_pct is not None else None,
        "volumeRatio": round(vol_ratio, 3) if vol_ratio is not None else None,
        "intradayReturnAbsPct": round(intraday_ret, 3) if intraday_ret is not None else None,
        "reasons": reasons,
    }


def load_paper_trade_stats_by_ticker(
    db_path: Path,
    date_str: str,
    lookback_days: int,
) -> dict[tuple[str, str], dict[str, float | int]]:
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
        start = (d0 - timedelta(days=max(1, int(lookback_days)) - 1)).isoformat()
        rows = conn.execute(
            """
            SELECT p.ticker,p.side,p.t5_return_pct
            FROM paper_trades p
            LEFT JOIN opening_scenarios os
              ON os.scenario_date=p.entry_date
             AND os.ticker=p.ticker
             AND lower(os.direction)=lower(p.side)
             AND COALESCE(os.signal_id,'')=COALESCE(p.signal_id,'')
            WHERE p.mode='watch'
              AND p.entry_date BETWEEN ? AND ?
              AND os.scenario_tier='paper_trade_only'
              AND p.t5_return_pct IS NOT NULL
            ORDER BY p.entry_date, p.trade_id
            """,
            (start, date_str),
        ).fetchall()
    finally:
        conn.close()
    grouped: dict[tuple[str, str], list[float]] = {}
    for r in rows:
        key = (str(r["ticker"] or "").strip(), str(r["side"] or "").strip().lower())
        if not key[0] or key[1] not in {"long", "short"}:
            continue
        grouped.setdefault(key, []).append(float(r["t5_return_pct"]))
    out: dict[tuple[str, str], dict[str, float | int]] = {}
    for k, vals in grouped.items():
        if not vals:
            continue
        wins = sum(1 for v in vals if v > 0.0)
        wr = wins / len(vals) * 100.0
        ev = sum(vals) / len(vals)
        # rough drawdown on sequential compounded returns
        eq = 1.0
        peak = 1.0
        mdd = 0.0
        for v in vals:
            eq *= 1.0 + (v / 100.0)
            if eq > peak:
                peak = eq
            dd = (eq / peak) - 1.0
            if dd < mdd:
                mdd = dd
        out[k] = {
            "trades": len(vals),
            "winRate": wr,
            "ev": ev,
            "maxDrawdownPct": mdd * 100.0,
        }
    return out


def fmt_price(v: float) -> str:
    return f"{int(round(v)):,}円"


def horizon_from_rank(rank: str) -> str:
    r = (rank or "").upper()
    if r.startswith("A"):
        return "T+5中心（T+1で一部利確、残りをT+5目線）"
    if r.startswith("B"):
        return "T+1〜T+3中心（デイトレ〜短期スイング）"
    return "T+1中心（短期限定）"


def aggressiveness_profile(level: str) -> tuple[float, float, str]:
    lvl = (level or "").strip().lower()
    if lvl == "aggressive":
        return 1.25, 1.10, "T+5"
    if lvl == "balanced":
        return 1.00, 1.00, "T+5"
    if lvl == "conservative":
        return 0.85, 0.90, "T+1"
    if lvl == "avoid":
        return 0.75, 0.80, "T+1"
    return 1.00, 1.00, "T+5"


def load_signal_type_aggressiveness_from_db(db_path: Path, date_str: str, fallback_days: int) -> tuple[dict[tuple[str, str], dict[str, object]], str | None]:
    if not db_path.exists():
        return {}, None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
        for i in range(0, max(0, fallback_days) + 1):
            d = (d0 - timedelta(days=i)).isoformat()
            rows = conn.execute(
                """
                SELECT signal_type,expected_direction,sample_count,t1_win_rate_pct,t5_win_rate_pct,t20_win_rate_pct,
                       t1_dir_avg_return_pct,t5_dir_avg_return_pct,t20_dir_avg_return_pct,
                       aggressiveness_level,aggressiveness_score,decision_reason
                FROM signal_type_aggressiveness_rows
                WHERE date=? AND window_days=365
                """,
                (d,),
            ).fetchall()
            if not rows:
                continue
            out: dict[tuple[str, str], dict[str, object]] = {}
            for r in rows:
                signal_type = str(r["signal_type"] or "").strip()
                expected_direction = str(r["expected_direction"] or "").strip().lower()
                if not signal_type or expected_direction not in {"up", "down"}:
                    continue
                out[(signal_type, expected_direction)] = {
                    "sample_count": int(r["sample_count"] or 0),
                    "t1_win_rate_pct": float(r["t1_win_rate_pct"]) if r["t1_win_rate_pct"] is not None else None,
                    "t5_win_rate_pct": float(r["t5_win_rate_pct"]) if r["t5_win_rate_pct"] is not None else None,
                    "t20_win_rate_pct": float(r["t20_win_rate_pct"]) if r["t20_win_rate_pct"] is not None else None,
                    "t1_dir_avg_return_pct": float(r["t1_dir_avg_return_pct"]) if r["t1_dir_avg_return_pct"] is not None else None,
                    "t5_dir_avg_return_pct": float(r["t5_dir_avg_return_pct"]) if r["t5_dir_avg_return_pct"] is not None else None,
                    "t20_dir_avg_return_pct": float(r["t20_dir_avg_return_pct"]) if r["t20_dir_avg_return_pct"] is not None else None,
                    "aggressiveness_level": str(r["aggressiveness_level"] or "").strip() or "unknown",
                    "aggressiveness_score": int(r["aggressiveness_score"] or 0),
                    "decision_reason": str(r["decision_reason"] or "").strip(),
                    "source_date": d,
                }
            return out, d
    finally:
        conn.close()
    return {}, None


def invalidation_text(direction: str) -> str:
    if direction == "long":
        return "寄り後に下方向へ急変し、想定支持を割る場合は見送り/撤退"
    return "寄り後に上方向へ急変し、想定抵抗を超える場合は見送り/撤退"


def build_rule_context(rule_rows: list[dict], side: str) -> dict:
    rows = [r for r in rule_rows if r.get("side") == side]
    rows.sort(
        key=lambda r: (
            {"active_rule": 0, "watch_rule": 1, "hypothesis_only": 2}.get(r.get("status", ""), 9),
            -(int(r.get("appearances") or 0)),
        )
    )
    if not rows:
        return {"summary": "該当ルール統計なし", "status": "unknown"}
    top = rows[0]
    return {
        "summary": f"{top.get('bucket','')} / status={top.get('status','')} / n={top.get('appearances','')} / T+1 {top.get('t1','')} / T+5 {top.get('t5','')} / T+20 {top.get('t20','')}",
        "status": top.get("status", ""),
        "bucket": top.get("bucket", ""),
        "appearances": int(top.get("appearances") or 0),
        "t1": top.get("t1", ""),
        "t5": top.get("t5", ""),
        "t20": top.get("t20", ""),
    }


def parse_signal_map(text: str) -> dict[str, dict[str, str]]:
    starts = [m.start() for m in HEAD_RE.finditer(text)]
    if not starts:
        return {}
    starts.append(len(text))
    out: dict[str, dict[str, str]] = {}
    for i in range(len(starts) - 1):
        chunk = text[starts[i] : starts[i + 1]]
        head = chunk.splitlines()[0]
        hm = HEAD_RE.match(head)
        if not hm:
            continue
        sid = hm.group(1).strip()
        d: dict[str, str] = {"title": hm.group(2).strip()}
        for line in chunk.splitlines()[1:]:
            fm = FIELD_RE.match(line.strip())
            if fm:
                d[fm.group(1)] = fm.group(2)
        out[sid] = d
    return out


def parse_wr(text: str) -> float | None:
    m = re.search(r"wr=([0-9]+(?:\.[0-9]+)?)%", text or "")
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def pick_horizon_by_wr(rule_ctx: dict, min_samples: int = 3) -> tuple[str, str, float | None]:
    n = int(rule_ctx.get("appearances") or 0)
    wr1 = parse_wr(rule_ctx.get("t1", ""))
    wr5 = parse_wr(rule_ctx.get("t5", ""))
    wr20 = parse_wr(rule_ctx.get("t20", ""))
    cand = [("T+1", wr1), ("T+5", wr5), ("T+20", wr20)]
    cand = [(k, v) for k, v in cand if v is not None]
    if not cand:
        return ("T+1", "勝率目安データ不足", None)
    best = max(cand, key=lambda x: x[1])
    verdict = "50%超" if best[1] >= 50.0 else "50%未満"
    if best[0] == "T+20":
        # Opening scenarios should frame profit expectation on the shorter T+5 horizon.
        return ("T+5", f"T+5想定勝率={best[1]:.1f}%（{verdict}）", float(best[1]))
    if n < max(1, min_samples):
        return (best[0], f"{best[0]}想定勝率={best[1]:.1f}%（参考値 n={n}）", float(best[1]))
    return (best[0], f"{best[0]}想定勝率={best[1]:.1f}%（{verdict}）", float(best[1]))


def _compute_phase_a_factor_scores(row: dict, signal_meta: dict[str, str], board: dict | None) -> dict[str, int]:
    """
    Phase A (DB-only) factors:
    - material: signal metadata quality
    - market: external context + gate status
    - volatility: technical check / rank proxy
    - gap: indicative open vs board mid (when available)
    """
    out = {"material": 0, "market": 0, "volatility": 0, "gap": 0}
    if (signal_meta.get("materialSignalChecked", "") or "").lower() == "yes":
        out["material"] += 3
    if (signal_meta.get("signalType", "") or "").strip().lower() in {
        "upward_revision_highest_profit",
        "upward_revision_plus_dividend",
        "downward_revision_dividend_cut",
        "offering_or_dilution",
    }:
        out["material"] += 2

    if (signal_meta.get("externalContextChecked", "") or "").lower() == "yes":
        out["market"] += 3
    if (signal_meta.get("gateStatus", "") or "").lower() == "pass":
        out["market"] += 2

    rank = (
        (row.get("longSignalRank", "") if (row.get("expectedDirection", "") or "").startswith("up") else row.get("shortSignalRank", ""))
        or ""
    ).upper()
    if (signal_meta.get("technicalSignalChecked", "") or "").lower() == "yes":
        out["volatility"] += 3
    if rank.startswith("A"):
        out["volatility"] += 2
    elif rank.startswith("B"):
        out["volatility"] += 1

    if board:
        bid = board.get("bestBid")
        ask = board.get("bestAsk")
        iop = board.get("indicativeOpen")
        if isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and isinstance(iop, (int, float)) and bid > 0 and ask > 0:
            mid = (float(bid) + float(ask)) / 2.0
            if mid > 0:
                gap_pct = (float(iop) / mid - 1.0) * 100.0
                if abs(gap_pct) >= 1.5:
                    out["gap"] += 3
                elif abs(gap_pct) >= 0.8:
                    out["gap"] += 2
                elif abs(gap_pct) >= 0.3:
                    out["gap"] += 1
    return out


def _compute_phase_b_factor_scores(row: dict) -> dict[str, int]:
    out = {"market_regime": 0, "sector_regime": 0}
    direction = str(row.get("expectedDirection", "") or "")
    is_long = direction.startswith("up")
    mctx = str(row.get("marketContext", "") or "").strip()
    smctx = str(row.get("sectorMarketContext", "") or "").strip()
    mconf = str(row.get("marketConfidence", "") or "").strip().lower()

    pos_tokens = ("追い風", "強い", "改善", "上向", "risk-on", "bull")
    neg_tokens = ("逆風", "弱い", "悪化", "下向", "risk-off", "bear")
    if any(t in mctx for t in pos_tokens):
        out["market_regime"] += 2 if is_long else -2
    if any(t in mctx for t in neg_tokens):
        out["market_regime"] += -2 if is_long else 2
    if mconf in {"high", "strong"}:
        out["market_regime"] += 1

    try:
        topix_pct = float(row.get("topixPct"))
    except Exception:
        topix_pct = None
    if topix_pct is not None:
        if is_long:
            out["market_regime"] += 1 if topix_pct >= 0.3 else (-1 if topix_pct <= -0.3 else 0)
        else:
            out["market_regime"] += 1 if topix_pct <= -0.3 else (-1 if topix_pct >= 0.3 else 0)

    if any(t in smctx for t in pos_tokens):
        out["sector_regime"] += 1 if is_long else -1
    if any(t in smctx for t in neg_tokens):
        out["sector_regime"] += -1 if is_long else 1
    try:
        rel = float(row.get("relativeToTopixPct"))
    except Exception:
        rel = None
    if rel is not None:
        if is_long:
            out["sector_regime"] += 2 if rel >= 0.5 else (-2 if rel <= -0.5 else 0)
        else:
            out["sector_regime"] += 2 if rel <= -0.5 else (-2 if rel >= 0.5 else 0)
    return out


def technical_tag(row: dict, signal_meta: dict[str, str]) -> str:
    st = str(signal_meta.get("signalType", "") or "").strip().lower()
    tech_checked = (signal_meta.get("technicalSignalChecked", "") or "").strip().lower() == "yes"
    long_rank = str(row.get("longSignalRank", "") or "").strip().upper()
    short_rank = str(row.get("shortSignalRank", "") or "").strip().upper()
    is_long = str(row.get("expectedDirection", "") or "").startswith("up")
    rank = long_rank if is_long else short_rank
    if "technical" in st:
        if "short" in st:
            return "technical_short"
        if "breakout" in st:
            return "technical_breakout"
        if "rebound" in st:
            return "technical_rebound"
        return "technical_generic"
    if tech_checked and rank.startswith("A"):
        return "tech_checked_rank_a"
    if tech_checked and rank.startswith("B"):
        return "tech_checked_rank_b"
    if tech_checked:
        return "tech_checked"
    return "non_technical"


def technical_score_bonus(tag: str) -> int:
    # Keep bonus intentionally small so technical factors augment, not dominate.
    if tag in {"technical_breakout", "technical_rebound", "technical_short"}:
        return 3
    if tag in {"technical_generic", "tech_checked_rank_a"}:
        return 2
    if tag in {"tech_checked_rank_b", "tech_checked"}:
        return 1
    return 0


def scenario_score(
    row: dict,
    signal_meta: dict[str, str],
    rule_ctx: dict,
    rule_hits: int,
    winrate_value: float | None,
    board_available: bool,
    board: dict | None = None,
) -> tuple[int, dict[str, int]]:
    side = "long" if (row.get("expectedDirection", "") or "").startswith("up") else "short"
    rank = ((row.get("longSignalRank") if side == "long" else row.get("shortSignalRank")) or "").upper()
    score = 35
    score += min(rule_hits, 7) * 4
    if rank.startswith("A"):
        score += 16
    elif rank.startswith("B"):
        score += 10
    if (signal_meta.get("technicalSignalChecked", "") or "").lower() == "yes":
        score += 8
    if (signal_meta.get("externalContextChecked", "") or "").lower() == "yes":
        score += 6
    if (signal_meta.get("materialSignalChecked", "") or "").lower() == "yes":
        score += 6
    if (signal_meta.get("gateStatus", "") or "").lower() == "pass":
        score += 6
    if winrate_value is not None:
        score += max(-8, min(12, int((winrate_value - 50.0) / 2.0)))
    else:
        score -= 6
    st = (rule_ctx.get("status", "") or "").strip()
    if st == "active_rule":
        score += 8
    elif st == "watch_rule":
        score += 4
    elif st == "hypothesis_only":
        score -= 4
    src = (row.get("candidateSource", "primary") or "primary").strip()
    if src == "watch":
        score -= 3
    elif src == "supplemental":
        score -= 6
    if board_available:
        score += 3
    tag = technical_tag(row, signal_meta)
    tech_bonus = technical_score_bonus(tag)
    score += tech_bonus
    phase_a = _compute_phase_a_factor_scores(row, signal_meta, board)
    phase_b = _compute_phase_b_factor_scores(row)
    score += sum(int(v or 0) for v in phase_a.values())
    score += sum(int(v or 0) for v in phase_b.values())
    final_score = max(0, min(100, int(score)))
    breakdown = {
        "base": 35,
        "rule_hits": min(rule_hits, 7) * 4,
        "rank": 16 if rank.startswith("A") else (10 if rank.startswith("B") else 0),
        "technical_checked": 8 if (signal_meta.get("technicalSignalChecked", "") or "").lower() == "yes" else 0,
        "external_checked": 6 if (signal_meta.get("externalContextChecked", "") or "").lower() == "yes" else 0,
        "material_checked": 6 if (signal_meta.get("materialSignalChecked", "") or "").lower() == "yes" else 0,
        "gate_pass": 6 if (signal_meta.get("gateStatus", "") or "").lower() == "pass" else 0,
        "winrate": (max(-8, min(12, int((winrate_value - 50.0) / 2.0))) if winrate_value is not None else -6),
        "rule_status": 8 if st == "active_rule" else (4 if st == "watch_rule" else (-4 if st == "hypothesis_only" else 0)),
        "candidate_source": (-3 if src == "watch" else (-6 if src == "supplemental" else 0)),
        "board_bonus": 3 if board_available else 0,
        "technical_tag_bonus": tech_bonus,
        "phase_a_material": int(phase_a.get("material", 0) or 0),
        "phase_a_market": int(phase_a.get("market", 0) or 0),
        "phase_a_volatility": int(phase_a.get("volatility", 0) or 0),
        "phase_a_gap": int(phase_a.get("gap", 0) or 0),
        "phase_b_market_regime": int(phase_b.get("market_regime", 0) or 0),
        "phase_b_sector_regime": int(phase_b.get("sector_regime", 0) or 0),
        "final": final_score,
    }
    return final_score, breakdown


def as_entry_row(signal_id: str, meta: dict[str, str], side: str) -> dict[str, str] | None:
    exp = (meta.get("expectedDirection") or "").strip()
    if side == "long" and exp not in {"up", "up_watch"}:
        return None
    if side == "short" and exp not in {"down", "down_watch"}:
        return None
    gate = (meta.get("gateStatus") or "").strip().lower()
    material = (meta.get("materialSignalChecked") or "").strip().lower()
    external = (meta.get("externalContextChecked") or "").strip().lower()
    if not (gate == "pass" and material == "yes" and external == "yes"):
        return None
    rank_field = "longSignalRank" if side == "long" else "shortSignalRank"
    rank = (meta.get(rank_field) or "").strip()
    if rank not in {"A", "A-", "B", "B+"}:
        return None
    return {
        "signalId": signal_id,
        "ticker": meta.get("ticker", ""),
        "company": meta.get("company", ""),
        "expectedDirection": exp,
        "longSignalRank": meta.get("longSignalRank", ""),
        "shortSignalRank": meta.get("shortSignalRank", ""),
        "tradeUse": "supplemental_from_market_signals",
        "url": meta.get("url", ""),
        "candidateSource": "supplemental",
    }


def quality_hit_count(row: dict, signal_meta: dict[str, str]) -> int:
    hits = 0
    gate = (signal_meta.get("gateStatus") or "").lower() == "pass"
    material = (signal_meta.get("materialSignalChecked") or "").lower() == "yes"
    external = (signal_meta.get("externalContextChecked") or "").lower() == "yes"
    technical = (signal_meta.get("technicalSignalChecked") or "").lower() == "yes"
    if gate:
        hits += 1
    if material:
        hits += 1
    if external:
        hits += 1
    if technical:
        hits += 1
    side = "long" if (row.get("expectedDirection", "") or "").startswith("up") else "short"
    rank = (row.get("longSignalRank") if side == "long" else row.get("shortSignalRank")) or ""
    if rank.upper().startswith("A"):
        hits += 2
    elif rank.upper().startswith("B"):
        hits += 1
    return hits


def scenario_for_row(
    row: dict,
    side: str,
    risk_jpy: int,
    rule_ctx: dict,
    signal_meta: dict[str, str],
    aggressiveness_ctx: dict[str, object] | None = None,
    board: dict | None = None,
    market_snap: dict | None = None,
    sample_hints: dict[tuple[str, str], int] | None = None,
) -> dict:
    ticker = row.get("ticker", "")
    company = row.get("company", "")
    rank = row.get("longSignalRank" if side == "long" else "shortSignalRank", row.get("rank", "C"))
    direction = "long" if side == "long" else "short"
    signal_type = str(signal_meta.get("signalType", "") or "").strip()
    expected_direction = "up" if direction == "long" else "down"

    aggr_level = "unknown"
    aggr_score: int | None = None
    aggr_reason = ""
    aggr_sample_count: int | None = None
    aggr_t5_wr: float | None = None
    aggr_t20_wr: float | None = None
    aggr_hold = "T+5"
    tp_mult, sl_mult, aggr_hold = aggressiveness_profile("balanced")
    if aggressiveness_ctx:
        aggr_level = str(aggressiveness_ctx.get("aggressiveness_level") or "unknown")
        aggr_score = int(aggressiveness_ctx.get("aggressiveness_score") or 0)
        aggr_reason = str(aggressiveness_ctx.get("decision_reason") or "")
        aggr_sample_count = int(aggressiveness_ctx.get("sample_count") or 0)
        aggr_t5_wr = float(aggressiveness_ctx.get("t5_win_rate_pct")) if aggressiveness_ctx.get("t5_win_rate_pct") is not None else None
        aggr_t20_wr = float(aggressiveness_ctx.get("t20_win_rate_pct")) if aggressiveness_ctx.get("t20_win_rate_pct") is not None else None
        tp_mult, sl_mult, aggr_hold = aggressiveness_profile(aggr_level)

    entry_price = None
    take_price = None
    stop_price = None
    board_available = bool(board)
    if board and direction == "long":
        base = board.get("bestAsk") or board.get("indicativeOpen") or board.get("bestBid")
        if isinstance(base, (int, float)) and base > 0:
            entry_price = float(base)
            take_price = entry_price * (1.012 * tp_mult)
            stop_price = entry_price * (1.0 - (0.006 * sl_mult))
    if board and direction == "short":
        base = board.get("bestBid") or board.get("indicativeOpen") or board.get("bestAsk")
        if isinstance(base, (int, float)) and base > 0:
            entry_price = float(base)
            take_price = entry_price * (1.0 - (0.012 * tp_mult))
            stop_price = entry_price * (1.0 + (0.006 * sl_mult))

    if entry_price and take_price and stop_price:
        entry_rule = f"{fmt_price(entry_price)}（板気配ベース）"
        take_rule = f"{fmt_price(take_price)}（第一利確）"
        stop_rule = f"{fmt_price(stop_price)}（損切）"
    else:
        if direction == "long":
            entry_rule = "寄り付き価格×0.998（押し待ち）"
            take_rule = "約定価格×1.012（第一利確）"
            stop_rule = "約定価格×0.994（損切）"
        else:
            entry_rule = "寄り付き価格×1.002（戻り待ち）"
            take_rule = "約定価格×0.988（第一利確）"
            stop_rule = "約定価格×1.006（損切）"

    lot_rule = f"1トレード許容損失 {risk_jpy}円 ÷ (エントリー価格 - 損切価格の絶対値)"
    rationale = [
        f"rank={rank}",
        f"expectedDirection={row.get('expectedDirection','')}",
        f"technicalTag={technical_tag(row, signal_meta)}",
        "source=entry-candidates + market-signals",
        f"boardSnapshot={'yes' if board_available else 'no'}",
    ]
    trigger = f"{signal_meta.get('signalType','')} / source={signal_meta.get('source','')} / session={signal_meta.get('session','')}"
    rule_hits = quality_hit_count(row, signal_meta)
    horizon_code, win_text, win_value = pick_horizon_by_wr(rule_ctx)
    score, score_breakdown = scenario_score(row, signal_meta, rule_ctx, rule_hits, win_value, board_available, board=board)
    sample_count = int(rule_ctx.get("appearances") or 0)
    if sample_count <= 0 and sample_hints:
        st = str(signal_meta.get("signalType", "") or "").strip()
        ed = str(row.get("expectedDirection", "") or "").strip()
        sample_count = int(sample_hints.get((st, ed), 0) or 0)
    skip_conditions = [
        invalidation_text(direction),
        "寄り直後の出来高が細い/気配が飛ぶ場合は見送り",
        "前提材料の否定ニュースが出た場合は見送り",
    ]
    why_pass = [
        f"ruleHits={rule_hits}",
        f"score={score}",
        f"sampleCount={sample_count}",
    ]
    if isinstance(win_value, (int, float)):
        why_pass.append(f"winRate={float(win_value):.1f}%")
    else:
        why_pass.append("winRate=unknown")
    exec_score, exec_breakdown = _compute_execution_feasibility(board, market_snap)
    return {
        "signalId": row.get("signalId", ""),
        "ticker": ticker,
        "company": company,
        "sector": row.get("sector", ""),
        "marketContext": row.get("marketContext", ""),
        "marketConfidence": row.get("marketConfidence", ""),
        "topixPct": row.get("topixPct", ""),
        "sectorMarketContext": row.get("sectorMarketContext", ""),
        "relativeToTopixPct": row.get("relativeToTopixPct", ""),
        "direction": direction,
        "signalType": signal_type,
        "aggressivenessLevel": aggr_level,
        "aggressivenessScore": aggr_score if aggr_score is not None else 0,
        "aggressivenessReason": aggr_reason,
        "aggressivenessSampleCount": aggr_sample_count if aggr_sample_count is not None else 0,
        "aggressivenessT5WinRate": aggr_t5_wr,
        "aggressivenessT20WinRate": aggr_t20_wr,
        "aggressivenessHoldHorizon": aggr_hold,
        "aggressivenessPriceMultiplier": round(tp_mult, 3),
        "entryLimitRule": entry_rule,
        "takeProfitRule": take_rule,
        "stopLossRule": stop_rule,
        "lotRule": lot_rule,
        "entryPrice": entry_price,
        "takeProfitPrice": take_price,
        "stopLossPrice": stop_price,
        "holdHorizon": horizon_from_rank(rank),
        "invalidationCondition": invalidation_text(direction),
        "ruleReproducibility": rule_ctx.get("summary", ""),
        "ruleStatus": rule_ctx.get("status", ""),
        "ruleHitCount": rule_hits,
        "ruleSampleCount": sample_count,
        "technicalTag": technical_tag(row, signal_meta),
        "scenarioScore": score,
        "scoreBreakdown": score_breakdown,
        "suggestedHorizon": horizon_code,
        "estimatedWinRate": win_text,
        "estimatedWinRateValue": win_value,
        "trigger": trigger,
        "skipConditions": skip_conditions,
        "rationale": rationale,
        "why_pass": why_pass,
        "why_hold": [],
        "why_reject": [],
        "why_pass_codes": [_reason_code(x) for x in why_pass] + ([f"AGGR_{aggr_level.upper()}"] if aggr_level and aggr_level != "unknown" else []),
        "why_hold_codes": [],
        "why_reject_codes": [],
        "executionFeasibilityScore": exec_score if exec_score is not None else "unknown",
        "executionFeasibilityBreakdown": exec_breakdown,
        "sourceUrl": row.get("url", ""),
        "candidateSource": row.get("candidateSource", "primary"),
        "borrowStatus": row.get("borrowStatus", ""),
    }


def main() -> int:
    args = parse_args()
    data, src_date = load_entry_candidates_from_db(args.db, args.date, args.fallback_days)
    if data is None:
        raise SystemExit(f"entry_candidates not found in DB for {args.date} (fallback_days={args.fallback_days})")
    src_rel = "db:entry_candidates"

    board_map, board_date = load_board_snapshot_from_db(args.db, args.date, args.fallback_days)
    market_snap_map, market_snap_date = load_market_snapshot_from_db(args.db, args.date, args.fallback_days)
    company_map = load_company_name_map_from_db(args.db, args.date, max(args.fallback_days, 30))
    paper_stats = load_paper_trade_stats_by_ticker(args.db, args.date, args.paper_promote_lookback_days)
    rule_rows, rule_date = load_rule_rows_from_db(args.db, args.date, args.fallback_days)
    sample_hints, sample_hint_date = load_sample_hints_from_outcomes(args.db, args.date, args.fallback_days)
    aggressiveness_map, aggressiveness_date = load_signal_type_aggressiveness_from_db(args.db, args.date, 365)
    signal_map, signal_date = load_signal_map_from_db(args.db, args.date, args.fallback_days)
    if not signal_map:
        raise SystemExit(f"signals not found in DB for {args.date} (fallback_days={args.fallback_days})")
    if not rule_rows:
        print(f"[warn] rule_dashboard_rows not found in DB for {args.date} (fallback_days={args.fallback_days}); continue with unknown rule context")
    if not aggressiveness_map:
        print(f"[warn] signal_type_aggressiveness_rows not found in DB for {args.date} (window_days=365); continue with neutral aggressiveness")
    signal_source_path = "db:signals"
    rule_source_path = "db:rule_dashboard_rows"
    ticker_ctx = load_ticker_context_from_db(args.db, args.date, args.fallback_days)
    long_rule_ctx = build_rule_context(rule_rows, "long")
    short_rule_ctx = build_rule_context(rule_rows, "short")

    long_rows = data.get("longEntryCandidates", [])[: args.max_candidates]
    short_rows = data.get("shortEntryCandidates", [])[: args.max_candidates]
    for r in long_rows:
        r["candidateSource"] = "primary"
    for r in short_rows:
        r["candidateSource"] = "primary"

    # 1) watch候補で補完
    long_watch = data.get("longWatchCandidates", []) or []
    short_watch = data.get("shortWatchCandidates", []) or []
    for r in long_watch:
        if len(long_rows) >= args.max_candidates:
            break
        sid = str(r.get("signalId", ""))
        if sid and sid not in {str(x.get("signalId", "")) for x in long_rows}:
            x = dict(r)
            x["candidateSource"] = "watch"
            long_rows.append(x)
    for r in short_watch:
        if len(short_rows) >= args.max_candidates:
            break
        sid = str(r.get("signalId", ""))
        if sid and sid not in {str(x.get("signalId", "")) for x in short_rows}:
            x = dict(r)
            x["candidateSource"] = "watch"
            short_rows.append(x)
    existing_long = {str(r.get("signalId", "")) for r in long_rows}
    existing_short = {str(r.get("signalId", "")) for r in short_rows}
    if len(long_rows) < args.max_candidates:
        for sid, meta in signal_map.items():
            if sid in existing_long:
                continue
            row = as_entry_row(sid, meta, "long")
            if row:
                long_rows.append(row)
                existing_long.add(sid)
            if len(long_rows) >= args.max_candidates:
                break
    if len(short_rows) < args.max_candidates:
        for sid, meta in signal_map.items():
            if sid in existing_short:
                continue
            row = as_entry_row(sid, meta, "short")
            if row:
                short_rows.append(row)
                existing_short.add(sid)
            if len(short_rows) >= args.max_candidates:
                break

    raw_scenarios = []
    for r in long_rows:
        ctx = ticker_ctx.get(str(r.get("ticker", "")).strip(), {})
        t = str(r.get("ticker", "")).strip()
        if _is_placeholder_company(str(r.get("company", "") or "")) and t in company_map:
            r["company"] = company_map[t]
        signal_meta_row = signal_map.get(str(r.get("signalId", "")).strip(), {})
        r["sector"] = resolve_sector_label(
            ctx.get("sector", ""),
            company=r.get("company", ""),
            signal_type=signal_meta_row.get("signalType", ""),
        )
        r["borrowStatus"] = ctx.get("borrow_status", "")
        r["buyStatus"] = ctx.get("buy_status", "")
        r["sellStatus"] = ctx.get("sell_status", "")
        r["marketContext"] = ctx.get("market_context", "")
        r["marketConfidence"] = ctx.get("market_confidence", "")
        r["topixPct"] = ctx.get("topix_pct", "")
        r["sectorMarketContext"] = ctx.get("sector_market_context", "")
        r["relativeToTopixPct"] = ctx.get("relative_to_topix_pct", "")
        aggr_ctx = aggressiveness_map.get(
            (
                str(signal_meta_row.get("signalType", "") or "").strip(),
                "up" if str(r.get("expectedDirection", "") or "").startswith("up") else "down",
            )
        )
        raw_scenarios.append(
            scenario_for_row(
                r,
                "long",
                args.risk_per_trade_jpy,
                long_rule_ctx,
                signal_meta_row,
                aggressiveness_ctx=aggr_ctx,
                board=board_map.get(str(r.get("ticker", "")).strip()),
                market_snap=market_snap_map.get(str(r.get("ticker", "")).strip()),
                sample_hints=sample_hints,
            )
        )
    for r in short_rows:
        ctx = ticker_ctx.get(str(r.get("ticker", "")).strip(), {})
        t = str(r.get("ticker", "")).strip()
        if _is_placeholder_company(str(r.get("company", "") or "")) and t in company_map:
            r["company"] = company_map[t]
        signal_meta_row = signal_map.get(str(r.get("signalId", "")).strip(), {})
        r["sector"] = resolve_sector_label(
            ctx.get("sector", ""),
            company=r.get("company", ""),
            signal_type=signal_meta_row.get("signalType", ""),
        )
        r["borrowStatus"] = ctx.get("borrow_status", "")
        r["buyStatus"] = ctx.get("buy_status", "")
        r["sellStatus"] = ctx.get("sell_status", "")
        r["marketContext"] = ctx.get("market_context", "")
        r["marketConfidence"] = ctx.get("market_confidence", "")
        r["topixPct"] = ctx.get("topix_pct", "")
        r["sectorMarketContext"] = ctx.get("sector_market_context", "")
        r["relativeToTopixPct"] = ctx.get("relative_to_topix_pct", "")
        aggr_ctx = aggressiveness_map.get(
            (
                str(signal_meta_row.get("signalType", "") or "").strip(),
                "up" if str(r.get("expectedDirection", "") or "").startswith("up") else "down",
            )
        )
        raw_scenarios.append(
            scenario_for_row(
                r,
                "short",
                args.risk_per_trade_jpy,
                short_rule_ctx,
                signal_meta_row,
                aggressiveness_ctx=aggr_ctx,
                board=board_map.get(str(r.get("ticker", "")).strip()),
                market_snap=market_snap_map.get(str(r.get("ticker", "")).strip()),
                sample_hints=sample_hints,
            )
        )

    def apply_quality_gate(min_rule_hits: int, min_score: int, min_winrate: float) -> tuple[list[dict], list[dict]]:
        accepted_local: list[dict] = []
        rejected_local: list[dict] = []
        for s in raw_scenarios:
            reasons: list[str] = []
            hard_fail = False
            if int(s.get("ruleHitCount") or 0) < min_rule_hits:
                reasons.append(f"ruleHits<{min_rule_hits}")
            if int(s.get("scenarioScore") or 0) < min_score:
                reasons.append(f"score<{min_score}")
            sample_n = int(s.get("ruleSampleCount") or 0)
            if sample_n < max(0, int(args.min_winrate_samples)):
                reasons.append(f"sampleCount<{int(args.min_winrate_samples)}")
            wv = s.get("estimatedWinRateValue")
            if isinstance(wv, (int, float)):
                if float(wv) < float(min_winrate):
                    reasons.append(f"winRate<{min_winrate:.1f}%")
            else:
                if not args.allow_unknown_winrate:
                    reasons.append("winRate_unknown")
            # n=1 exceptional allowance: keep possibility when score+winrate are clearly strong.
            if sample_n == 1:
                strong_n1 = (
                    int(s.get("scenarioScore") or 0) >= int(args.n1_min_score)
                    and isinstance(wv, (int, float))
                    and float(wv) >= float(args.n1_min_winrate)
                )
                if not strong_n1:
                    reasons.append(f"n1_not_strong(score>={int(args.n1_min_score)}&wr>={float(args.n1_min_winrate):.1f}%)")
            if reasons:
                # Manual operator override: if credit is explicitly marked marginable,
                # allow trade-tier pass when score/hits are not critically low.
                if str(s.get("borrowStatus", "")).strip().lower() == "manual_marginable":
                    score_now = int(s.get("scenarioScore") or 0)
                    hits_now = int(s.get("ruleHitCount") or 0)
                    sample_now = int(s.get("ruleSampleCount") or 0)
                    if sample_now >= max(1, int(args.min_winrate_samples)) and score_now >= max(args.soft_min_score, 50) and hits_now >= max(args.soft_min_rule_hits, 2):
                        x = dict(s)
                        x["scenarioTier"] = "trade"
                        x["manualCreditOverride"] = True
                        x["manualCreditOverrideReasons"] = reasons
                        x["why_pass"] = list(x.get("why_pass") or [])
                        x["why_pass"].append("manualCreditOverride=applied")
                        x["why_pass_codes"] = [_reason_code(v) for v in x["why_pass"]]
                        accepted_local.append(x)
                        continue
                if args.soft_gate:
                    score_now = int(s.get("scenarioScore") or 0)
                    hits_now = int(s.get("ruleHitCount") or 0)
                    if score_now >= args.soft_min_score and hits_now >= args.soft_min_rule_hits:
                        x = dict(s)
                        x["scenarioTier"] = "watch"
                        x["softRejectReasons"] = reasons
                        x["why_hold"] = [str(v) for v in reasons]
                        x["why_hold_codes"] = [_reason_code(v) for v in x["why_hold"]]
                        accepted_local.append(x)
                        continue
                    hard_fail = True
                else:
                    hard_fail = True
            if hard_fail:
                rejected_local.append(
                    {
                        "ticker": s.get("ticker", ""),
                        "company": s.get("company", ""),
                        "direction": s.get("direction", ""),
                        "scenarioScore": s.get("scenarioScore", 0),
                        "ruleHitCount": s.get("ruleHitCount", 0),
                        "estimatedWinRate": s.get("estimatedWinRate", ""),
                        "rejectReasons": reasons,
                        "why_pass": [],
                        "why_hold": [],
                        "why_reject": [str(v) for v in reasons],
                        "why_pass_codes": [],
                        "why_hold_codes": [],
                        "why_reject_codes": [_reason_code(str(v)) for v in reasons],
                    }
                )
            else:
                if "scenarioTier" not in s:
                    s["scenarioTier"] = "trade"
                s["why_pass"] = list(s.get("why_pass") or [])
                s["why_hold"] = list(s.get("why_hold") or [])
                s["why_reject"] = list(s.get("why_reject") or [])
                s["why_pass_codes"] = [_reason_code(v) for v in s["why_pass"]]
                s["why_hold_codes"] = [_reason_code(v) for v in s["why_hold"]]
                s["why_reject_codes"] = [_reason_code(v) for v in s["why_reject"]]
                accepted_local.append(s)
        return accepted_local, rejected_local

    min_rule_hits_eff = args.min_rule_hits
    min_score_eff = args.min_score
    min_winrate_eff = float(args.min_winrate)
    relax_applied = False
    relax_rounds = 0
    relax_history: list[dict] = []

    accepted, rejected = apply_quality_gate(min_rule_hits_eff, min_score_eff, min_winrate_eff)
    need_total = int(args.min_long) + int(args.min_short)
    if args.auto_relax_gate and len(accepted) < need_total:
        step_rule_hits = 1
        step_score = 3
        step_winrate = 1.0
        for i in range(max(0, args.auto_relax_steps)):
            next_rule_hits = max(int(args.relax_min_rule_hits_floor), min_rule_hits_eff - step_rule_hits)
            next_score = max(int(args.relax_min_score_floor), min_score_eff - step_score)
            next_winrate = max(float(args.relax_min_winrate_floor), min_winrate_eff - step_winrate)
            if (
                next_rule_hits == min_rule_hits_eff
                and next_score == min_score_eff
                and abs(next_winrate - min_winrate_eff) < 1e-9
            ):
                break
            min_rule_hits_eff, min_score_eff, min_winrate_eff = next_rule_hits, next_score, next_winrate
            cand_acc, cand_rej = apply_quality_gate(min_rule_hits_eff, min_score_eff, min_winrate_eff)
            relax_history.append(
                {
                    "round": i + 1,
                    "minRuleHits": min_rule_hits_eff,
                    "minScore": min_score_eff,
                    "minWinRate": round(min_winrate_eff, 1),
                    "accepted": len(cand_acc),
                }
            )
            accepted, rejected = cand_acc, cand_rej
            relax_applied = True
            relax_rounds = i + 1
            if len(accepted) >= need_total:
                break

    scenarios = accepted

    # Exclude non-marginable tickers from both long/short scenarios.
    margin_rejected = []
    filtered_scenarios = []
    for s in scenarios:
        sid = str(s.get("signalId", "")).strip()
        ticker = str(s.get("ticker", "")).strip()
        src_row = signal_map.get(sid, {}) if sid else {}
        # borrow status is attached via row at scenario creation path; fallback to context map.
        borrow_status = _prefer_fresher_credit(
            str(src_row.get("borrowStatus", "")).strip(),
            str(ticker_ctx.get(ticker, {}).get("borrow_status", "")).strip(),
        )
        buy_status = _prefer_fresher_credit(
            str(src_row.get("buyStatus", "")).strip(),
            str(ticker_ctx.get(ticker, {}).get("buy_status", "")).strip(),
        )
        sell_status = _prefer_fresher_credit(
            str(src_row.get("sellStatus", "")).strip(),
            str(ticker_ctx.get(ticker, {}).get("sell_status", "")).strip(),
        )
        direction = str(s.get("direction", "")).strip().lower()
        if direction == "short":
            relevant = (sell_status or borrow_status or "").strip()
        else:
            relevant = (buy_status or borrow_status or "").strip()

        if is_non_marginable_for_direction(direction, borrow_status, buy_status, sell_status):
            if _is_unknown_status(relevant):
                # Unknown credit state is downgraded to watch, not hard-rejected.
                x = dict(s)
                x["scenarioTier"] = "watch"
                reasons = list(x.get("softRejectReasons") or [])
                reasons.append(f"credit_unknown:base={borrow_status};buy={buy_status};sell={sell_status}")
                x["softRejectReasons"] = reasons
                x["why_hold"] = list(x.get("why_hold") or [])
                x["why_hold"].append(reasons[-1])
                x["why_hold_codes"] = [_reason_code(v) for v in x["why_hold"]]
                filtered_scenarios.append(x)
                continue
            margin_rejected.append(
                {
                    "ticker": ticker,
                    "company": s.get("company", ""),
                    "direction": s.get("direction", ""),
                    "scenarioScore": s.get("scenarioScore", 0),
                    "ruleHitCount": s.get("ruleHitCount", 0),
                    "estimatedWinRate": s.get("estimatedWinRate", ""),
                    "rejectReasons": [f"credit_unavailable:base={borrow_status};buy={buy_status};sell={sell_status}"],
                    "why_pass": [],
                    "why_hold": [],
                    "why_reject": [f"credit_unavailable:base={borrow_status};buy={buy_status};sell={sell_status}"],
                    "why_pass_codes": [],
                    "why_hold_codes": [],
                    "why_reject_codes": ["CREDIT_UNAVAILABLE"],
                }
            )
            continue
        filtered_scenarios.append(s)
    scenarios = filtered_scenarios
    had_margin_rejected = len(margin_rejected)
    if margin_rejected:
        rejected.extend(margin_rejected)

    # 2.5) sampleCount-based tier ladder
    # 0: watch, 1-2: paper_trade_only, >=3: trade
    demoted_watch = 0
    demoted_paper = 0
    for s in scenarios:
        sample_n = int(s.get("ruleSampleCount") or 0)
        cur_tier = str(s.get("scenarioTier", "trade") or "trade")
        if cur_tier != "trade":
            continue
        if sample_n <= 0:
            s["scenarioTier"] = "watch"
            reasons = list(s.get("softRejectReasons") or [])
            reasons.append("sampleCount=0 -> watch")
            s["softRejectReasons"] = reasons
            s["why_hold"] = list(s.get("why_hold") or [])
            s["why_hold"].append("sampleCount=0 -> watch")
            s["why_hold_codes"] = [_reason_code(v) for v in s["why_hold"]]
            demoted_watch += 1
        elif sample_n <= int(args.paper_trade_max_samples):
            s["scenarioTier"] = "paper_trade_only"
            reasons = list(s.get("softRejectReasons") or [])
            reasons.append(f"sampleCount<={int(args.paper_trade_max_samples)} -> paper_trade_only")
            s["softRejectReasons"] = reasons
            s["why_hold"] = list(s.get("why_hold") or [])
            s["why_hold"].append(f"sampleCount<={int(args.paper_trade_max_samples)} -> paper_trade_only")
            s["why_hold_codes"] = [_reason_code(v) for v in s["why_hold"]]
            demoted_paper += 1

    promoted_from_paper = 0
    blocked_from_paper = 0
    for s in scenarios:
        if str(s.get("scenarioTier", "")) != "paper_trade_only":
            continue
        ticker = str(s.get("ticker", "")).strip()
        side = str(s.get("direction", "")).strip().lower()
        st = paper_stats.get((ticker, side))
        if not st:
            blocked_from_paper += 1
            s["paperPromotion"] = {"promoted": False, "reason": "no_paper_stats"}
            continue
        trades = int(st.get("trades", 0) or 0)
        wr = float(st.get("winRate", 0.0) or 0.0)
        ev = float(st.get("ev", 0.0) or 0.0)
        mdd = float(st.get("maxDrawdownPct", 0.0) or 0.0)
        ok = (
            trades >= int(args.paper_promote_min_trades)
            and wr >= float(args.paper_promote_min_winrate)
            and ev >= float(args.paper_promote_min_ev)
            and mdd >= float(args.paper_promote_max_dd)
        )
        if ok:
            s["scenarioTier"] = "trade"
            s["paperPromotion"] = {
                "promoted": True,
                "trades": trades,
                "winRate": round(wr, 3),
                "ev": round(ev, 3),
                "maxDrawdownPct": round(mdd, 3),
            }
            promoted_from_paper += 1
        else:
            blocked_from_paper += 1
            s["paperPromotion"] = {
                "promoted": False,
                "trades": trades,
                "winRate": round(wr, 3),
                "ev": round(ev, 3),
                "maxDrawdownPct": round(mdd, 3),
                "thresholds": {
                    "minTrades": int(args.paper_promote_min_trades),
                    "minWinRate": float(args.paper_promote_min_winrate),
                    "minEv": float(args.paper_promote_min_ev),
                    "maxDrawdownPct": float(args.paper_promote_max_dd),
                },
            }

    # 3) 最低件数ガード
    plan_mode = "trade"
    plan_notes: list[str] = []
    accepted_long = sum(1 for x in scenarios if x.get("direction") == "long" and x.get("scenarioTier") == "trade")
    accepted_short = sum(1 for x in scenarios if x.get("direction") == "short" and x.get("scenarioTier") == "trade")
    paper_long = sum(1 for x in scenarios if x.get("direction") == "long" and x.get("scenarioTier") == "paper_trade_only")
    paper_short = sum(1 for x in scenarios if x.get("direction") == "short" and x.get("scenarioTier") == "paper_trade_only")
    watch_long = sum(1 for x in scenarios if x.get("direction") == "long" and x.get("scenarioTier") == "watch")
    watch_short = sum(1 for x in scenarios if x.get("direction") == "short" and x.get("scenarioTier") == "watch")
    min_long_eff = int(args.min_long)
    min_short_eff = int(args.min_short)
    if args.adaptive_side_minimum:
        raw_long = sum(1 for x in raw_scenarios if x.get("direction") == "long")
        raw_short = sum(1 for x in raw_scenarios if x.get("direction") == "short")
        if raw_long <= 1:
            min_long_eff = min(min_long_eff, raw_long)
        if raw_short <= 1:
            min_short_eff = min(min_short_eff, raw_short)
    if accepted_long < min_long_eff or accepted_short < min_short_eff:
        plan_mode = "watch_only"
        plan_notes.append(
            f"最低件数未達のため様子見優先（long={accepted_long}/{min_long_eff}, short={accepted_short}/{min_short_eff}）"
        )
        plan_notes.append("新規エントリーは見送り、監視継続と条件再確認を優先する。")
    if had_margin_rejected > 0:
        plan_notes.append(f"信用取引不可のため除外: {had_margin_rejected}件")
    if rejected:
        plan_notes.append(f"品質ゲート除外: {len(rejected)}件（score/ruleHits/winRate 条件未達）")
    if demoted_watch > 0 or demoted_paper > 0:
        plan_notes.append(
            f"sampleCount段階運用を適用（watch={demoted_watch}件, paper_trade_only={demoted_paper}件, threshold: 0/watch, 1-{int(args.paper_trade_max_samples)}/paper, >= {int(args.paper_trade_max_samples)+1}/trade）"
        )
    if promoted_from_paper > 0 or blocked_from_paper > 0:
        plan_notes.append(
            f"paper->trade昇格判定（promoted={promoted_from_paper}, blocked={blocked_from_paper}, lookback={int(args.paper_promote_lookback_days)}d）"
        )
    if relax_applied:
        plan_notes.append(
            f"サンプル不足のため品質ゲートを段階緩和（rounds={relax_rounds}, effective: hits>={min_rule_hits_eff}, score>={min_score_eff}, winRate>={min_winrate_eff:.1f}%）"
        )
    if rule_date:
        try:
            stale_days = (datetime.strptime(args.date, "%Y-%m-%d").date() - datetime.strptime(rule_date, "%Y-%m-%d").date()).days
        except Exception:
            stale_days = 0
        if stale_days >= 3:
            plan_notes.append(f"rule_dashboard_rows is stale: {rule_date} ({stale_days}d old) -> degraded confidence")
    if not rule_rows:
        if sample_hints:
            plan_notes.append(f"rule_dashboard_rows missing; used sample hints from backtest_outcomes date={sample_hint_date or args.date}")
        else:
            plan_notes.append("rule_dashboard_rows missing; no sample hints available -> quality confidence degraded")

    degraded_reasons: list[str] = []
    if plan_mode == "watch_only":
        degraded_reasons.append("minimum_side_count_unmet")
    if had_margin_rejected > 0:
        degraded_reasons.append("credit_block_present")
    if rejected:
        degraded_reasons.append("quality_gate_rejected_present")
    if relax_applied:
        degraded_reasons.append("auto_relax_applied")
    if rule_date:
        try:
            stale_days = (datetime.strptime(args.date, "%Y-%m-%d").date() - datetime.strptime(rule_date, "%Y-%m-%d").date()).days
        except Exception:
            stale_days = 0
        if stale_days >= 3:
            degraded_reasons.append("rule_dashboard_stale")
    else:
        stale_days = None
    if not rule_rows:
        if sample_hints:
            degraded_reasons.append("rule_dashboard_missing_sample_hints_used")
        else:
            degraded_reasons.append("rule_dashboard_missing_no_hints")

    quality_status = "ok"
    if plan_mode == "watch_only" or len(scenarios) == 0:
        quality_status = "degraded"
    quality_state = {
        "status": quality_status,
        "planMode": plan_mode,
        "degradedReasons": degraded_reasons,
        "staleRuleDays": stale_days,
        "acceptedCount": len(scenarios),
        "rejectedCount": len(rejected),
        "acceptedLong": accepted_long,
        "acceptedShort": accepted_short,
    }

    out = {
        "date": args.date,
        "sourceDate": src_date,
        "source": src_rel,
        "boardSnapshotDate": board_date or "",
        "boardSnapshotSource": "db:board_snapshots" if board_date else "",
        "marketSnapshotDate": market_snap_date or "",
        "marketSnapshotSource": "db:market_signal_snapshots" if market_snap_date else "",
        "ruleDashboardDate": rule_date or "",
        "ruleDashboardSource": rule_source_path,
        "signalSourceDate": signal_date or "",
        "signalSourcePath": signal_source_path,
        "riskPerTradeJpy": args.risk_per_trade_jpy,
        "planMode": plan_mode,
        "planNotes": plan_notes,
        "qualityState": quality_state,
        "counts": {
            "long": accepted_long,
            "short": accepted_short,
            "paperLong": paper_long,
            "paperShort": paper_short,
            "watchLong": watch_long,
            "watchShort": watch_short,
            "paperPromotedToTrade": promoted_from_paper,
            "paperPromotionBlocked": blocked_from_paper,
            "minLong": args.min_long,
            "minShort": args.min_short,
            "effectiveMinLong": min_long_eff,
            "effectiveMinShort": min_short_eff,
            "rejected": len(rejected),
        },
        "qualityGate": {
            "minRuleHits": args.min_rule_hits,
            "minScore": args.min_score,
            "minWinRate": args.min_winrate,
            "effectiveMinRuleHits": min_rule_hits_eff,
            "effectiveMinScore": min_score_eff,
            "effectiveMinWinRate": round(min_winrate_eff, 1),
            "autoRelaxEnabled": bool(args.auto_relax_gate),
            "autoRelaxApplied": relax_applied,
            "autoRelaxRounds": relax_rounds,
            "autoRelaxHistory": relax_history,
        },
        "caution": "売買助言ではなく、寄り前シナリオ整理。板・気配・売建可否の人手確認が必須。",
        "scenarios": scenarios,
        "rejectedScenarios": rejected,
    }

    out_json = INBOX / f"{args.date}-opening-scenarios.json"
    out_md = INBOX / f"{args.date}-opening-scenarios.md"
    out_json.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# {args.date} Opening Scenarios",
        "",
        f"- sourceDate: {src_date}",
        f"- source: {src_rel}",
        f"- riskPerTradeJpy: {args.risk_per_trade_jpy}",
        f"- planMode: {plan_mode}",
        "- caution: 売買助言ではなく、寄り前シナリオ整理。板・気配・売建可否の人手確認が必須。",
        "",
        "## Scenarios",
    ]
    if plan_notes:
        lines.extend(["## Plan Notes", *[f"- {x}" for x in plan_notes], ""])
    if not scenarios:
        lines.append("- N/C")
    else:
        for i, s in enumerate(scenarios, 1):
            lines.extend(
                [
                    f"### {i}. {s['ticker']} {s['company']}",
                    f"- direction: {s['direction']}",
                    f"- aggressiveness: {s.get('aggressivenessLevel','unknown')} / score={s.get('aggressivenessScore',0)} / hold={s.get('aggressivenessHoldHorizon','')}",
                    f"- scenarioScore: {s.get('scenarioScore',0)}",
                    f"- entryLimit: {s['entryLimitRule']}",
                    f"- takeProfit: {s['takeProfitRule']}",
                    f"- stopLoss: {s['stopLossRule']}",
                    f"- lot: {s['lotRule']}",
                    f"- ruleHits: {s.get('ruleHitCount',0)}",
                    f"- estimatedWinRate: {s.get('estimatedWinRate','')}",
                    f"- executionFeasibilityScore: {s.get('executionFeasibilityScore','unknown')}",
                    f"- sourceType: {s.get('candidateSource','primary')}",
                    f"- rationale: {' / '.join(s['rationale'])}",
                    f"- invalidation: {s.get('invalidationCondition','')}",
                    f"- sourceUrl: {s['sourceUrl']}",
                    f"- sector: {s.get('sector','') or '不明'}",
                    "",
                ]
            )
    lines.extend(["", "## Rejected (Quality Gate)"])
    if not rejected:
        lines.append("- none")
    else:
        for r in rejected:
            lines.append(
                f"- {r['ticker']} {r['company']} [{r['direction']}] score={r.get('scenarioScore',0)} hits={r.get('ruleHitCount',0)} reason={','.join(r.get('rejectReasons',[]))}"
            )

    out_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    # DB-first: persist scenario rows for downstream processing to avoid file dependency.
    conn = sqlite3.connect(args.db)
    try:
        conn.execute(
            "DELETE FROM opening_scenarios WHERE scenario_date=?",
            (args.date,),
        )
        conn.execute(
            "DELETE FROM scenario_gate_diagnostics WHERE scenario_date=?",
            (args.date,),
        )
        gate_thresholds = {
            "minRuleHits": args.min_rule_hits,
            "minScore": args.min_score,
            "minWinRate": args.min_winrate,
            "effectiveMinRuleHits": min_rule_hits_eff,
            "effectiveMinScore": min_score_eff,
            "effectiveMinWinRate": round(min_winrate_eff, 1),
            "autoRelaxApplied": relax_applied,
            "autoRelaxRounds": relax_rounds,
        }
        def insert_diag(item: dict, gate_result: str, reject_reasons: list[str] | None = None) -> None:
            conn.execute(
                """
                INSERT INTO scenario_gate_diagnostics(
                  scenario_date,signal_id,ticker,direction,candidate_source,scenario_tier,
                  scenario_score,rule_hit_count,estimated_winrate_value,gate_result,
                  reject_reasons_json,gate_thresholds_json,payload_json,source_path,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    args.date,
                    str(item.get("signalId", "") or ""),
                    str(item.get("ticker", "") or ""),
                    str(item.get("direction", "") or ""),
                    str(item.get("candidateSource", "") or ""),
                    str(item.get("scenarioTier", "") or ""),
                    int(item.get("scenarioScore") or 0),
                    int(item.get("ruleHitCount") or 0),
                    item.get("estimatedWinRateValue"),
                    gate_result,
                    json.dumps(reject_reasons or [], ensure_ascii=False),
                    json.dumps(gate_thresholds, ensure_ascii=False),
                    json.dumps(item, ensure_ascii=False),
                    "db:entry_candidates",
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
        idx = 0
        for s in scenarios:
            s["why_pass"] = [str(x) for x in (s.get("why_pass") or [])]
            s["why_hold"] = [str(x) for x in (s.get("why_hold") or [])]
            s["why_reject"] = []
            s["why_pass_codes"] = [_reason_code(x) for x in s["why_pass"]]
            s["why_hold_codes"] = [_reason_code(x) for x in s["why_hold"]]
            s["why_reject_codes"] = []
            idx += 1
            conn.execute(
                """
                INSERT INTO opening_scenarios(
                  scenario_date, scenario_index, signal_id, ticker, company, direction, scenario_tier,
                  scenario_score, rule_hit_count, estimated_winrate_text, estimated_winrate_value,
                  aggressiveness_level, aggressiveness_score, aggressiveness_reason, aggressiveness_sample_count,
                  aggressiveness_t5_winrate, aggressiveness_t20_winrate, aggressiveness_hold_horizon,
                  entry_price, take_profit_price, stop_loss_price, source_url, source_kind, source_path, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    args.date,
                    idx,
                    s.get("signalId", ""),
                    s.get("ticker", ""),
                    s.get("company", ""),
                    s.get("direction", ""),
                    s.get("scenarioTier", "trade"),
                    int(s.get("scenarioScore") or 0),
                    int(s.get("ruleHitCount") or 0),
                    s.get("estimatedWinRate", ""),
                    s.get("estimatedWinRateValue"),
                    s.get("aggressivenessLevel", ""),
                    int(s.get("aggressivenessScore") or 0),
                    s.get("aggressivenessReason", ""),
                    int(s.get("aggressivenessSampleCount") or 0),
                    s.get("aggressivenessT5WinRate"),
                    s.get("aggressivenessT20WinRate"),
                    s.get("aggressivenessHoldHorizon", ""),
                    s.get("entryPrice"),
                    s.get("takeProfitPrice"),
                    s.get("stopLossPrice"),
                    s.get("sourceUrl", ""),
                    "scenario",
                    "db:entry_candidates",
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            insert_diag(s, "accepted", [])
        for r in rejected:
            r["why_pass"] = []
            r["why_hold"] = []
            if not r.get("why_reject"):
                r["why_reject"] = [str(x) for x in (r.get("rejectReasons") or [])]
            r["why_pass_codes"] = []
            r["why_hold_codes"] = []
            r["why_reject_codes"] = [_reason_code(str(x)) for x in (r.get("why_reject") or [])]
            idx += 1
            conn.execute(
                """
                INSERT INTO opening_scenarios(
                  scenario_date, scenario_index, signal_id, ticker, company, direction, scenario_tier,
                  scenario_score, rule_hit_count, estimated_winrate_text, estimated_winrate_value,
                  aggressiveness_level, aggressiveness_score, aggressiveness_reason, aggressiveness_sample_count,
                  aggressiveness_t5_winrate, aggressiveness_t20_winrate, aggressiveness_hold_horizon,
                  entry_price, take_profit_price, stop_loss_price, source_url, source_kind, source_path, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    args.date,
                    idx,
                    "",
                    r.get("ticker", ""),
                    r.get("company", ""),
                    r.get("direction", ""),
                    "watch",
                    int(r.get("scenarioScore") or 0),
                    int(r.get("ruleHitCount") or 0),
                    r.get("estimatedWinRate", ""),
                    None,
                    None,
                    None,
                    None,
                    "",
                    0,
                    "",
                    0,
                    None,
                    None,
                    "",
                    "",
                    "rejected",
                    "db:entry_candidates",
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            insert_diag(r, "rejected", [str(x) for x in (r.get("rejectReasons") or [])])
        conn.commit()
    finally:
        conn.close()
    write_pipeline_event(
        pipeline="investment_signal",
        slot="inv-scenario",
        stage="build_opening_scenarios",
        status=quality_status,
        event_date=args.date,
        return_code=0,
        payload={
            "qualityState": quality_state,
            "qualityGate": out.get("qualityGate", {}),
            "paperPromotion": {
                "promoted": promoted_from_paper,
                "blocked": blocked_from_paper,
                "lookbackDays": int(args.paper_promote_lookback_days),
            },
            "sourceDate": src_date,
            "ruleDashboardDate": rule_date or "",
            "signalSourceDate": signal_date or "",
        },
        source_path="scripts/investment/signals/build_opening_scenarios.py",
    )
    print(f"wrote {out_md.relative_to(ROOT)} and {out_json.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
