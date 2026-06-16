#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db

INBOX = ROOT / "topics" / "investment-research" / "inbox"
DEFAULT_DB = resolve_investment_db()
COMPANY_OVERRIDE_PATH = ROOT / "configs" / "ticker_company_overrides.json"

SIG_RE = re.compile(r"^###\s+([^:]+):\s*(.+)$", re.MULTILINE)
FIELD_RE = re.compile(r"^-\s+([A-Za-z0-9+_-]+):\s*(.*)$")
OUT_RE = re.compile(r"^###\s+(outcome_[^:]+):\s*(.+)$", re.MULTILINE)
POS_RE = re.compile(r"^###\s+([0-9]{4}|[0-9]{3}[A-Z])\s+(.+?)\s+\[(long|short)\]\s+x([0-9]+)\s+\(([^)]+)\)\s*$", re.MULTILINE)


def signal_type_label_ja(v: str) -> str:
    m = {
        "self_buyback": "自社株買い",
        "earnings_positive": "好決算",
        "earnings_negative": "悪決算",
        "technical_breakout": "テクニカル上放れ",
        "technical_breakdown": "テクニカル下放れ",
        "rebound_long_candidate": "押し目ロング候補",
        "rebound_short_candidate": "戻り売りショート候補",
        "news_material": "ニュース材料",
    }
    return m.get((v or "").strip(), v or "")


def expected_direction_label_ja(v: str) -> str:
    m = {
        "up": "上昇",
        "up_watch": "上昇監視",
        "down": "下落",
        "down_watch": "下落監視",
        "neutral": "中立",
        "unknown": "不明",
    }
    return m.get((v or "").strip(), v or "")


def rank_label_ja(v: str) -> str:
    v = (v or "").strip()
    if not v:
        return ""
    if v.lower() == "none":
        return "該当なし"
    if v.lower() == "unknown":
        return "不明"
    return f"{v}ランク"


def gate_status_label_ja(v: str) -> str:
    s = (v or "").lower()
    if not s:
        return ""
    if "pass" in s:
        return "通過"
    if "fail" in s:
        return "非通過"
    if "watch" in s:
        return "監視"
    return v or ""


def disclosure_category_label_ja(v: str) -> str:
    m = {
        "self_buyback": "自社株買い",
        "earnings": "決算",
        "technical": "テクニカル",
        "news": "ニュース",
        "unknown": "不明",
    }
    return m.get((v or "").strip(), v or "")


def side_label_ja(v: str) -> str:
    return {"long": "ロング", "short": "ショート"}.get((v or "").strip(), v or "")


def status_label_ja(v: str) -> str:
    return {
        "active_rule": "有効ルール",
        "watch_rule": "監視ルール",
        "hypothesis_only": "仮説段階",
    }.get((v or "").strip(), v or "")


def daily_use_label_ja(v: str) -> str:
    m = {
        "long_core_watch": "ロング主監視",
        "long_watch": "ロング監視",
        "buy_avoid_or_exit": "買い回避/手仕舞い観点",
        "short_term_only": "短期限定",
        "short_core_watch": "ショート主監視",
        "return_short_wait": "戻り売り待ち",
        "low_liquidity_short_caution": "低流動性ショート注意",
        "buy_avoid_no_system_short": "買い回避（ショート見送り）",
        "return_short_wait_or_avoid": "戻り待ち/見送り",
        "short_term_event_only": "イベント短期限定",
        "watch": "監視",
    }
    return m.get((v or "").strip(), v or "")


def bucket_label_ja(v: str) -> str:
    m = {
        "strict_long_signal": "ロング強シグナル",
        "long_watch": "ロング監視",
        "long_downgrade_or_avoid": "ロング降格/回避",
        "long_short_term_only": "ロング短期限定",
        "strict_short_signal": "ショート強シグナル",
        "return_short_wait": "戻り売り待ち",
        "tactical_low_liquidity_watch": "低流動性戦術監視",
        "buy_avoid_no_system_short": "買い回避（ショート見送り）",
        "return_short_wait_or_avoid": "戻り待ち/回避",
        "exit_or_buy_avoid": "手仕舞い/買い回避",
        "event_only": "イベント限定",
    }
    return m.get((v or "").strip(), v or "")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _is_placeholder_company(v: str) -> bool:
    s = (v or "").strip()
    if not s:
        return True
    return s.upper() in {"不明", "-", "N/A", "NA", "UNKNOWN"}


def _load_company_overrides() -> dict[str, str]:
    if not COMPANY_OVERRIDE_PATH.exists():
        return {}
    try:
        raw = json.loads(COMPANY_OVERRIDE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        tk = str(k or "").strip()
        tv = str(v or "").strip()
        if not tk or _is_placeholder_company(tv):
            continue
        out[tk] = tv
    return out


def _resolve_company_name(conn: sqlite3.Connection, ticker: str, current_company: str, asof_date: str) -> str:
    c = (current_company or "").strip()
    if not _is_placeholder_company(c):
        return c
    t = (ticker or "").strip()
    if not t:
        return c
    overrides = _load_company_overrides()
    if t in overrides:
        return overrides[t]

    # 1) existing signals (most recent <= asof_date)
    try:
        row = conn.execute(
            """
            SELECT company FROM signals
            WHERE ticker=? AND date<=?
            ORDER BY date DESC, signal_id DESC
            LIMIT 1
            """,
            (t, asof_date),
        ).fetchone()
    except sqlite3.DatabaseError as e:
        if "malformed" in str(e).lower():
            return c
        raise
    if row:
        v = str(row[0] or "").strip()
        if not _is_placeholder_company(v):
            return v

    # 2) tdnet disclosures
    try:
        row = conn.execute(
            """
            SELECT company FROM tdnet_disclosures
            WHERE ticker=? AND date<=?
            ORDER BY date DESC, disclosed_at DESC
            LIMIT 1
            """,
            (t, asof_date),
        ).fetchone()
    except sqlite3.DatabaseError as e:
        if "malformed" in str(e).lower():
            return c
        raise
    if row:
        v = str(row[0] or "").strip()
        if not _is_placeholder_company(v):
            return v

    # 3) instruments master
    try:
        row = conn.execute("SELECT name FROM instruments WHERE ticker=? LIMIT 1", (t,)).fetchone()
    except sqlite3.DatabaseError as e:
        if "malformed" in str(e).lower():
            return c
        raise
    if row:
        v = str(row[0] or "").strip()
        if not _is_placeholder_company(v):
            return v
    return c


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest investment inbox into SQLite")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--date", help="target date YYYY-MM-DD (optional)")
    return p.parse_args()


def files_for(pattern: str, date: str | None):
    if date:
        return [INBOX / pattern.format(date=date)]
    return sorted(INBOX.glob(pattern.replace("{date}", "*")))


def upsert_daily(conn: sqlite3.Connection, path: Path):
    text = path.read_text(encoding="utf-8")
    date = path.name[:10]
    summary = "\n".join([ln for ln in text.splitlines() if ln.strip()][:8])
    conn.execute(
        """
        INSERT INTO daily_digest(topic,date,path,summary,updated_at)
        VALUES(?,?,?,?,?)
        ON CONFLICT(topic,date) DO UPDATE SET path=excluded.path,summary=excluded.summary,updated_at=excluded.updated_at
        """,
        ("investment-research", date, str(path.relative_to(ROOT)), summary, now()),
    )
    conn.execute("INSERT INTO ingest_log(run_at,kind,source_path,rows) VALUES(?,?,?,?)", (now(), "daily", str(path.relative_to(ROOT)), 1))


def parse_signal_chunks(text: str):
    starts = [m.start() for m in SIG_RE.finditer(text)]
    if not starts:
        return []
    starts.append(len(text))
    rows = []
    for i in range(len(starts)-1):
        chunk = text[starts[i]:starts[i+1]]
        head = chunk.splitlines()[0]
        m = SIG_RE.match(head)
        if not m:
            continue
        d = {"signal_id": m.group(1).strip(), "title": m.group(2).strip()}
        for line in chunk.splitlines()[1:]:
            f = FIELD_RE.match(line.strip())
            if f:
                d[f.group(1)] = f.group(2)
        d["t1"] = ""
        d["t5"] = ""
        d["t20"] = ""
        t1 = re.search(r"- T\+1:\s*(.*)", chunk)
        t5 = re.search(r"- T\+5:\s*(.*)", chunk)
        t20 = re.search(r"- T\+20:\s*(.*)", chunk)
        if t1: d["t1"] = t1.group(1).strip()
        if t5: d["t5"] = t5.group(1).strip()
        if t20: d["t20"] = t20.group(1).strip()
        gate = re.search(r"- gateStatus:\s*(.*)", chunk)
        d["gateStatus"] = gate.group(1).strip() if gate else ""
        rows.append(d)
    return rows


def upsert_signals(conn: sqlite3.Connection, path: Path):
    text = path.read_text(encoding="utf-8")
    date = path.name[:10]
    rows = parse_signal_chunks(text)
    for r in rows:
        existing = conn.execute(
            """
            SELECT long_rank,short_rank,gate_status,payload_json
            FROM signals
            WHERE signal_id=? AND date=?
            """,
            (r.get("signal_id", ""), date),
        ).fetchone()
        parsed_payload: dict = dict(r)
        keep_noon_reeval = False
        if existing and existing[3]:
            try:
                existing_payload = json.loads(str(existing[3]))
            except Exception:
                existing_payload = {}
            keep_noon_reeval = isinstance(existing_payload, dict) and isinstance(existing_payload.get("noonReeval"), dict)
            if keep_noon_reeval:
                # Keep DB-side noon re-evaluation result even when inbox markdown is re-ingested.
                r["longSignalRank"] = str(existing[0] or r.get("longSignalRank", ""))
                r["shortSignalRank"] = str(existing[1] or r.get("shortSignalRank", ""))
                r["gateStatus"] = str(existing[2] or r.get("gateStatus", ""))
                parsed_payload.update(existing_payload)
        ticker = str(r.get("ticker", "") or "").strip()
        company = _resolve_company_name(conn, ticker, str(r.get("company", "") or ""), date)
        r["company"] = company
        conn.execute(
            """
            INSERT INTO signals(signal_id,date,ticker,company,signal_type,signal_type_label_ja,expected_direction,expected_direction_label_ja,long_rank,short_rank,long_rank_label_ja,short_rank_label_ja,t1,t5,t20,gate_status,gate_status_label_ja,url,source,session,material_signal_checked,external_context_checked,technical_signal_checked,credit_status,credit_buy_status,credit_sell_status,credit_source_kind,credit_source_date,credit_freshness_hours,payload_json,source_path,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(signal_id,date) DO UPDATE SET
            ticker=excluded.ticker,company=excluded.company,signal_type=excluded.signal_type,signal_type_label_ja=excluded.signal_type_label_ja,
            expected_direction=excluded.expected_direction,expected_direction_label_ja=excluded.expected_direction_label_ja,
            long_rank=excluded.long_rank,short_rank=excluded.short_rank,long_rank_label_ja=excluded.long_rank_label_ja,short_rank_label_ja=excluded.short_rank_label_ja,
            t1=excluded.t1,t5=excluded.t5,t20=excluded.t20,
            gate_status=excluded.gate_status,gate_status_label_ja=excluded.gate_status_label_ja,
            url=excluded.url,source=excluded.source,session=excluded.session,
            material_signal_checked=excluded.material_signal_checked,external_context_checked=excluded.external_context_checked,technical_signal_checked=excluded.technical_signal_checked,
            credit_status=excluded.credit_status,credit_buy_status=excluded.credit_buy_status,credit_sell_status=excluded.credit_sell_status,
            credit_source_kind=excluded.credit_source_kind,credit_source_date=excluded.credit_source_date,credit_freshness_hours=excluded.credit_freshness_hours,
            payload_json=excluded.payload_json,
            source_path=excluded.source_path,updated_at=excluded.updated_at
            """,
            (
                r.get("signal_id",""), date, ticker, company, r.get("signalType",""),
                signal_type_label_ja(r.get("signalType","")),
                r.get("expectedDirection",""), expected_direction_label_ja(r.get("expectedDirection","")),
                r.get("longSignalRank",""), r.get("shortSignalRank",""),
                rank_label_ja(r.get("longSignalRank","")), rank_label_ja(r.get("shortSignalRank","")),
                r.get("t1",""), r.get("t5",""), r.get("t20",""), r.get("gateStatus",""),
                gate_status_label_ja(r.get("gateStatus","")),
                r.get("url",""), r.get("source",""), r.get("session",""),
                r.get("materialSignalChecked",""), r.get("externalContextChecked",""), r.get("technicalSignalChecked",""),
                r.get("creditStatus",""), r.get("creditBuyStatus",""), r.get("creditSellStatus",""),
                r.get("creditSourceKind",""), r.get("creditSourceDate",""),
                int(r.get("creditFreshnessHours", 0) or 0) if str(r.get("creditFreshnessHours", "")).strip() else None,
                json.dumps(parsed_payload, ensure_ascii=False, separators=(",", ":")),
                str(path.relative_to(ROOT)), now(),
            ),
        )
        # Keep write units small on drvfs-backed SQLite files to avoid
        # long transactions that have been correlating with corruption.
        conn.commit()
    conn.execute("INSERT INTO ingest_log(run_at,kind,source_path,rows) VALUES(?,?,?,?)", (now(), "signals", str(path.relative_to(ROOT)), len(rows)))
    conn.commit()


def upsert_entry_candidates(conn: sqlite3.Connection, path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    date = data.get("date", path.name[:10])
    rows = 0
    mappings = [
        ("long", "longEntryCandidates", "primary", "longSignalRank"),
        ("short", "shortEntryCandidates", "primary", "shortSignalRank"),
        ("long", "longWatchCandidates", "watch", "longSignalRank"),
        ("short", "shortWatchCandidates", "watch", "shortSignalRank"),
    ]
    for side, key, candidate_type, rank_field in mappings:
        for r in data.get(key, []) or []:
            ticker = str(r.get("ticker", "") or "").strip()
            company = _resolve_company_name(conn, ticker, str(r.get("company", "") or ""), date)
            r["company"] = company
            conn.execute(
                """
                INSERT INTO entry_candidates(date,side,candidate_type,signal_id,ticker,company,rank,long_rank,short_rank,expected_direction,trade_use,gate_status,material_signal_checked,external_context_checked,technical_signal_checked,score,url,payload_json,source_path,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT DO UPDATE SET
                candidate_type=excluded.candidate_type,
                ticker=excluded.ticker,company=excluded.company,rank=excluded.rank,expected_direction=excluded.expected_direction,
                long_rank=excluded.long_rank,short_rank=excluded.short_rank,trade_use=excluded.trade_use,
                gate_status=excluded.gate_status,material_signal_checked=excluded.material_signal_checked,
                external_context_checked=excluded.external_context_checked,technical_signal_checked=excluded.technical_signal_checked,
                score=excluded.score,url=excluded.url,payload_json=excluded.payload_json,source_path=excluded.source_path,updated_at=excluded.updated_at
                """,
                (
                    date, side, candidate_type, r.get("signalId",""), ticker, company,
                    r.get(rank_field,""), r.get("longSignalRank",""), r.get("shortSignalRank",""),
                    r.get("expectedDirection",""), r.get("tradeUse",""), r.get("gateStatus",""),
                    r.get("materialSignalChecked",""), r.get("externalContextChecked",""), r.get("technicalSignalChecked",""),
                    int(r.get("score", 0) or 0), r.get("url",""), json.dumps(r, ensure_ascii=False, separators=(",", ":")), str(path.relative_to(ROOT)), now(),
                ),
            )
            rows += 1
            conn.commit()
    conn.execute("INSERT INTO ingest_log(run_at,kind,source_path,rows) VALUES(?,?,?,?)", (now(), "entry_candidates", str(path.relative_to(ROOT)), rows))
    conn.commit()


def parse_outcome_chunks(text: str):
    starts = [m.start() for m in OUT_RE.finditer(text)]
    if not starts:
        return []
    starts.append(len(text))
    out = []
    for i in range(len(starts)-1):
        chunk = text[starts[i]:starts[i+1]]
        head = chunk.splitlines()[0]
        m = OUT_RE.match(head)
        if not m:
            continue
        d = {"outcome_id": m.group(1).strip(), "title": m.group(2).strip()}
        for line in chunk.splitlines()[1:]:
            f = FIELD_RE.match(line.strip())
            if f:
                d[f.group(1)] = f.group(2)
        out.append(d)
    return out


def upsert_backtest(conn: sqlite3.Connection, path: Path):
    text = path.read_text(encoding="utf-8")
    date = path.name[:10]
    rows = parse_outcome_chunks(text)
    skipped_missing_identity = 0
    upserted_rows = 0
    for r in rows:
        def judge_or_pending(key: str) -> str:
            v = (r.get(key) or "").strip()
            return v if v else "pending"

        def opt_float(key: str) -> float | None:
            raw = str(r.get(key) or "").strip()
            if not raw or raw.lower() in {"none", "null"}:
                return None
            try:
                return float(raw)
            except Exception:
                return None

        def opt_int(key: str) -> int | None:
            raw = str(r.get(key) or "").strip()
            if not raw or raw.lower() in {"none", "null"}:
                return None
            try:
                return int(float(raw))
            except Exception:
                return None

        ticker = r.get("ticker", "")
        if not ticker:
            m = re.match(r"([0-9]{4}|[0-9]{3}[A-Z])\s+", r.get("title", ""))
            ticker = m.group(1) if m else ""
        source_signal_id = (r.get("sourceSignalId", "") or "").strip()
        outcome_id = (r.get("outcome_id", "") or "").strip()
        row_date = date
        signal_date = (r.get("signalDate", "") or "").strip()
        signal_type = (r.get("signalType", "") or "").strip()
        if not source_signal_id or not signal_date or not signal_type:
            # Skip malformed rows without full stable identity.
            skipped_missing_identity += 1
            continue

        # Force deterministic identity to prevent duplicate ingestion across reruns.
        # Format: outcome_<sourceSignalId>_<signalDate>_<signalType>
        normalized_type = re.sub(r"[^A-Za-z0-9_-]+", "_", signal_type)
        outcome_id = f"outcome_{source_signal_id}_{signal_date}_{normalized_type}"

        conn.execute(
            """
            INSERT INTO backtest_outcomes(outcome_id,date,source_signal_id,ticker,signal_date,disclosure_category,disclosure_category_label_ja,signal_type,signal_type_label_ja,expected_direction,expected_direction_label_ja,long_rank,short_rank,long_rank_label_ja,short_rank_label_ja,base_close_price,base_volume,t1_candle_type,t1_open_price,t1_high_price,t1_low_price,t1_close_price,t3_close_price,t5_close_price,t10_close_price,t20_close_price,t1_open_vs_base_pct,t1_high_vs_base_pct,t1_low_vs_base_pct,t1_close_vs_base_pct,t3_close_vs_base_pct,t5_close_vs_base_pct,t10_close_vs_base_pct,t20_close_vs_base_pct,t1_close_vs_open_pct,t1_range_pct,t1_body_pct,t1_upper_wick_pct,t1_lower_wick_pct,t1_close_location,t1_volume,t1_volume_ratio_5,t1_volume_ratio_25,t1_judge,t3_judge,t5_judge,t10_judge,t20_judge,outcome_type,source_path,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT DO UPDATE SET
            ticker=excluded.ticker,signal_date=excluded.signal_date,
            disclosure_category=excluded.disclosure_category,disclosure_category_label_ja=excluded.disclosure_category_label_ja,
            signal_type=excluded.signal_type,signal_type_label_ja=excluded.signal_type_label_ja,
            expected_direction=excluded.expected_direction,expected_direction_label_ja=excluded.expected_direction_label_ja,
            long_rank=excluded.long_rank,short_rank=excluded.short_rank,long_rank_label_ja=excluded.long_rank_label_ja,short_rank_label_ja=excluded.short_rank_label_ja,
            base_close_price=excluded.base_close_price,base_volume=excluded.base_volume,t1_candle_type=excluded.t1_candle_type,
            t1_open_price=excluded.t1_open_price,t1_high_price=excluded.t1_high_price,t1_low_price=excluded.t1_low_price,t1_close_price=excluded.t1_close_price,
            t3_close_price=excluded.t3_close_price,t5_close_price=excluded.t5_close_price,t10_close_price=excluded.t10_close_price,t20_close_price=excluded.t20_close_price,
            t1_open_vs_base_pct=excluded.t1_open_vs_base_pct,t1_high_vs_base_pct=excluded.t1_high_vs_base_pct,t1_low_vs_base_pct=excluded.t1_low_vs_base_pct,
            t1_close_vs_base_pct=excluded.t1_close_vs_base_pct,t3_close_vs_base_pct=excluded.t3_close_vs_base_pct,t5_close_vs_base_pct=excluded.t5_close_vs_base_pct,t10_close_vs_base_pct=excluded.t10_close_vs_base_pct,t20_close_vs_base_pct=excluded.t20_close_vs_base_pct,
            t1_close_vs_open_pct=excluded.t1_close_vs_open_pct,t1_range_pct=excluded.t1_range_pct,t1_body_pct=excluded.t1_body_pct,
            t1_upper_wick_pct=excluded.t1_upper_wick_pct,t1_lower_wick_pct=excluded.t1_lower_wick_pct,t1_close_location=excluded.t1_close_location,
            t1_volume=excluded.t1_volume,t1_volume_ratio_5=excluded.t1_volume_ratio_5,t1_volume_ratio_25=excluded.t1_volume_ratio_25,
            t1_judge=excluded.t1_judge,t3_judge=excluded.t3_judge,t5_judge=excluded.t5_judge,t10_judge=excluded.t10_judge,t20_judge=excluded.t20_judge,
            outcome_type=excluded.outcome_type,source_path=excluded.source_path,updated_at=excluded.updated_at,
            outcome_id=excluded.outcome_id,date=excluded.date
            """,
            (
                outcome_id, row_date, source_signal_id, ticker, signal_date,
                r.get("disclosureCategory",""), disclosure_category_label_ja(r.get("disclosureCategory","")),
                r.get("signalType",""), signal_type_label_ja(r.get("signalType","")),
                r.get("expectedDirection",""), expected_direction_label_ja(r.get("expectedDirection","")),
                r.get("longSignalRank",""), r.get("shortSignalRank",""),
                rank_label_ja(r.get("longSignalRank","")), rank_label_ja(r.get("shortSignalRank","")),
                opt_float("baseClosePrice"),
                opt_int("baseVolume"),
                r.get("T+1Candle", ""),
                opt_float("T+1OpenPrice"),
                opt_float("T+1HighPrice"),
                opt_float("T+1LowPrice"),
                opt_float("T+1ClosePrice"),
                opt_float("T+3ClosePrice"),
                opt_float("T+5ClosePrice"),
                opt_float("T+10ClosePrice"),
                opt_float("T+20ClosePrice"),
                opt_float("T+1OpenVsBasePct"),
                opt_float("T+1HighVsBasePct"),
                opt_float("T+1LowVsBasePct"),
                opt_float("T+1CloseVsBasePct"),
                opt_float("T+3CloseVsBasePct"),
                opt_float("T+5CloseVsBasePct"),
                opt_float("T+10CloseVsBasePct"),
                opt_float("T+20CloseVsBasePct"),
                opt_float("T+1CloseVsOpenPct"),
                opt_float("T+1RangePct"),
                opt_float("T+1BodyPct"),
                opt_float("T+1UpperWickPct"),
                opt_float("T+1LowerWickPct"),
                opt_float("T+1CloseLocation"),
                opt_int("T+1Volume"),
                opt_float("T+1VolumeRatio5"),
                opt_float("T+1VolumeRatio25"),
                judge_or_pending("T+1Judge"), judge_or_pending("T+3Judge"), judge_or_pending("T+5Judge"), judge_or_pending("T+10Judge"), judge_or_pending("T+20Judge"), r.get("roughOutcomeType",""),
                str(path.relative_to(ROOT)), now(),
            ),
        )
        upserted_rows += 1
    conn.execute("INSERT INTO ingest_log(run_at,kind,source_path,rows) VALUES(?,?,?,?)", (now(), "backtest_outcomes", str(path.relative_to(ROOT)), upserted_rows))
    if skipped_missing_identity:
        conn.execute(
            "INSERT INTO ingest_log(run_at,kind,source_path,rows) VALUES(?,?,?,?)",
            (now(), "backtest_outcomes_skipped_missing_identity", str(path.relative_to(ROOT)), skipped_missing_identity),
        )
    print(f"[ingest_backtest] file={path.name} parsed={len(rows)} upserted={upserted_rows} skipped_missing_identity={skipped_missing_identity}")


def upsert_paper_trade_report(conn: sqlite3.Connection, path: Path):
    text = path.read_text(encoding="utf-8")
    date = path.name[:10]
    mm = re.search(r"^- mode:\s*(.+)$", text, re.MULTILINE)
    mode = (mm.group(1).strip() if mm else "") or "backtest"
    rows = 0
    for idx, m in enumerate(POS_RE.finditer(text), start=1):
        ticker, company, side = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        lots = int(m.group(4).strip())
        start = m.end()
        nxt = POS_RE.search(text, start)
        end = nxt.start() if nxt else len(text)
        body = text[start:end]
        sm = re.search(r"^- status:\s*(.+)$", body, re.MULTILINE)
        status = sm.group(1).strip() if sm else "open_pending_outcome"

        def parse_win(label: str):
            wm = re.search(rf"^- {re.escape(label)}:\s+return=([^%]+)%\s*/\s*judge=([^\n]+)$", body, re.MULTILINE)
            if not wm:
                return None, "pending"
            rv = wm.group(1).strip()
            jv = wm.group(2).strip()
            ret = None if rv in ("None", "null", "") else float(rv)
            judge = "pending" if jv in ("None", "null", "") else jv
            return ret, judge

        t1_ret, t1_j = parse_win("T+1")
        t5_ret, t5_j = parse_win("T+5")
        t20_ret, t20_j = parse_win("T+20")
        trade_id = f"paper_{date}_{ticker}_{side}_{mode}_{idx:03d}"
        conn.execute(
            """
            INSERT INTO paper_trades(trade_id,entry_date,ticker,company,side,lots,entry_style,status,signal_id,source_path,t1_return_pct,t5_return_pct,t20_return_pct,t1_judge,t5_judge,t20_judge,updated_at,mode)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(trade_id) DO UPDATE SET
            entry_date=excluded.entry_date,ticker=excluded.ticker,company=excluded.company,side=excluded.side,lots=excluded.lots,
            entry_style=excluded.entry_style,status=excluded.status,signal_id=excluded.signal_id,source_path=excluded.source_path,
            t1_return_pct=excluded.t1_return_pct,t5_return_pct=excluded.t5_return_pct,t20_return_pct=excluded.t20_return_pct,
            t1_judge=excluded.t1_judge,t5_judge=excluded.t5_judge,t20_judge=excluded.t20_judge,updated_at=excluded.updated_at,mode=excluded.mode
            """,
            (
                trade_id, date, ticker, company, side, lots, "paper", status, None, str(path.relative_to(ROOT)),
                t1_ret, t5_ret, t20_ret, t1_j, t5_j, t20_j, now(), mode,
            ),
        )
        rows += 1
    conn.execute("INSERT INTO ingest_log(run_at,kind,source_path,rows) VALUES(?,?,?,?)", (now(), "paper_trades", str(path.relative_to(ROOT)), rows))


def upsert_execution_plan(conn: sqlite3.Connection, path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    plan_date = data.get("date", path.name[:10])
    rows = 0
    for idx, r in enumerate(data.get("scenarios", []) or [], start=1):
        ticker = (r.get("ticker") or "").strip()
        direction = (r.get("direction") or "").strip().lower()
        if not ticker or not direction:
            continue
        signal_id = (r.get("signalId") or "").strip()
        plan_id = f"plan_{plan_date}_{signal_id or ticker+'_'+direction}_{idx:03d}"
        reasons = r.get("reasons", [])
        if isinstance(reasons, list):
            reasons_txt = "\n".join(str(x) for x in reasons)
        else:
            reasons_txt = str(reasons or "")
        conn.execute(
            """
            INSERT INTO execution_plan(plan_id,plan_date,ticker,company,direction,entry,tp,sl,rr,ev,rank,reasons,scenario_tier,status,signal_id,source_path,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(plan_id) DO UPDATE SET
            plan_date=excluded.plan_date,ticker=excluded.ticker,company=excluded.company,direction=excluded.direction,
            entry=excluded.entry,tp=excluded.tp,sl=excluded.sl,rr=excluded.rr,ev=excluded.ev,rank=excluded.rank,reasons=excluded.reasons,
            scenario_tier=excluded.scenario_tier,status=excluded.status,signal_id=excluded.signal_id,source_path=excluded.source_path,updated_at=excluded.updated_at
            """,
            (
                plan_id, plan_date, ticker, r.get("company", ""), direction,
                r.get("entryPrice"), r.get("takeProfit"), r.get("stopLoss"), r.get("rr"), r.get("expectedValue"),
                r.get("rank", ""), reasons_txt, r.get("scenarioTier", "trade"), r.get("status", "pending"),
                signal_id, str(path.relative_to(ROOT)), now(),
            ),
        )
        rows += 1
    conn.execute("INSERT INTO ingest_log(run_at,kind,source_path,rows) VALUES(?,?,?,?)", (now(), "execution_plan", str(path.relative_to(ROOT)), rows))


def upsert_rule_dashboard(conn: sqlite3.Connection, path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    date = data.get("date", path.name[:10])
    rows = 0
    for r in data.get("rows", []):
        side = r.get("side", "")
        bucket = r.get("bucket", "")
        daily_use = r.get("dailyUse", "")
        status = r.get("status", "")
        conn.execute(
            """
            INSERT INTO rule_dashboard_rows(date,side,side_label_ja,bucket,bucket_label_ja,rule,appearances,period,t1,t5,t20,daily_use,daily_use_label_ja,status,status_label_ja,source_path,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(date,side,bucket,rule) DO UPDATE SET
            side_label_ja=excluded.side_label_ja,bucket_label_ja=excluded.bucket_label_ja,appearances=excluded.appearances,
            period=excluded.period,t1=excluded.t1,t5=excluded.t5,t20=excluded.t20,daily_use=excluded.daily_use,
            daily_use_label_ja=excluded.daily_use_label_ja,status=excluded.status,status_label_ja=excluded.status_label_ja,
            source_path=excluded.source_path,updated_at=excluded.updated_at
            """,
            (
                date, side, side_label_ja(side), bucket, bucket_label_ja(bucket), r.get("rule", ""),
                int(r.get("appearances") or 0), r.get("period", ""), r.get("t1", ""), r.get("t5", ""), r.get("t20", ""),
                daily_use, daily_use_label_ja(daily_use), status, status_label_ja(status),
                str(path.relative_to(ROOT)), now(),
            ),
        )
        rows += 1
    conn.execute("INSERT INTO ingest_log(run_at,kind,source_path,rows) VALUES(?,?,?,?)", (now(), "rule_dashboard_rows", str(path.relative_to(ROOT)), rows))


def upsert_rule_history(conn: sqlite3.Connection, path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    rules = data.get("rules", {}) or {}
    rows = 0
    for rid, item in rules.items():
        side = item.get("side", "")
        bucket = item.get("bucket", "")
        for s in item.get("snapshots", []) or []:
            status = s.get("status", "")
            daily_use = s.get("dailyUse", "")
            conn.execute(
                """
                INSERT INTO rule_history_snapshots(rule_id,date,side,side_label_ja,bucket,bucket_label_ja,rule,appearances,period,t1,t5,t20,daily_use,daily_use_label_ja,status,status_label_ja,source_path,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(rule_id,date) DO UPDATE SET
                side=excluded.side,side_label_ja=excluded.side_label_ja,bucket=excluded.bucket,bucket_label_ja=excluded.bucket_label_ja,
                rule=excluded.rule,appearances=excluded.appearances,period=excluded.period,t1=excluded.t1,t5=excluded.t5,t20=excluded.t20,
                daily_use=excluded.daily_use,daily_use_label_ja=excluded.daily_use_label_ja,status=excluded.status,status_label_ja=excluded.status_label_ja,
                source_path=excluded.source_path,updated_at=excluded.updated_at
                """,
                (
                    rid, s.get("date", ""), side, side_label_ja(side), bucket, bucket_label_ja(bucket),
                    item.get("rule", ""), int(s.get("appearances") or 0), s.get("period", ""),
                    s.get("t1", ""), s.get("t5", ""), s.get("t20", ""), daily_use, daily_use_label_ja(daily_use),
                    status, status_label_ja(status), str(path.relative_to(ROOT)), now(),
                ),
            )
            rows += 1
    conn.execute("INSERT INTO ingest_log(run_at,kind,source_path,rows) VALUES(?,?,?,?)", (now(), "rule_history_snapshots", str(path.relative_to(ROOT)), rows))


def upsert_observations(conn: sqlite3.Connection, path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    date = data.get("date", path.name[:10])
    rows = 0
    for r in data.get("rows", []) or []:
        note = str(r.get("note", "")).strip()
        if not note:
            continue
        obs_time = str(r.get("obsTime", "")).strip()
        ticker = str(r.get("ticker", "")).strip()
        sector = str(r.get("sector", "")).strip()
        tag = str(r.get("tag", "")).strip()
        source_kind = str(r.get("sourceKind", "manual_observation")).strip() or "manual_observation"
        source_url = str(r.get("sourceUrl", "")).strip()
        payload = r.get("payload", {})
        if not isinstance(payload, (dict, list)):
            payload = {"value": payload}
        conn.execute(
            """
            INSERT INTO observations(obs_date,obs_time,ticker,sector,tag,source_kind,source_url,note,payload_json,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                date, obs_time, ticker, sector, tag, source_kind, source_url, note,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                now(),
            ),
        )
        rows += 1
    conn.execute("INSERT INTO ingest_log(run_at,kind,source_path,rows) VALUES(?,?,?,?)", (now(), "observations", str(path.relative_to(ROOT)), rows))


def main() -> int:
    args = parse_args()
    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        for p in files_for("{date}-daily.md", args.date):
            if p.exists() and p.parent.name == "inbox":
                upsert_daily(conn, p)
        for p in files_for("{date}-market-signals.md", args.date):
            if p.exists():
                upsert_signals(conn, p)
        for p in files_for("{date}-entry-candidates.json", args.date):
            if p.exists():
                upsert_entry_candidates(conn, p)
        for p in files_for("{date}-rough-backtest-outcomes-batch-1.md", args.date):
            if p.exists():
                upsert_backtest(conn, p)
        for p in files_for("{date}-rule-dashboard.json", args.date):
            if p.exists():
                upsert_rule_dashboard(conn, p)
        for p in files_for("{date}-paper-trade-report.md", args.date):
            if p.exists():
                upsert_paper_trade_report(conn, p)
        for p in files_for("{date}-opening-scenarios.json", args.date):
            if p.exists():
                upsert_execution_plan(conn, p)
        for p in files_for("{date}-observations.json", args.date):
            if p.exists():
                upsert_observations(conn, p)
        history = ROOT / "topics" / "investment-research" / "rule-history.json"
        if history.exists():
            upsert_rule_history(conn, history)
        conn.commit()
    finally:
        conn.close()
    print(f"ingested into {db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
