#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "topics" / "investment-research" / "inbox"
DEFAULT_DB = ROOT / "data" / "investment.db"

SIG_RE = re.compile(r"^###\s+([^:]+):\s*(.+)$", re.MULTILINE)
FIELD_RE = re.compile(r"^-\s+([A-Za-z0-9+_-]+):\s*(.*)$")
OUT_RE = re.compile(r"^###\s+(outcome_[^:]+):\s*(.+)$", re.MULTILINE)


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
        conn.execute(
            """
            INSERT INTO signals(signal_id,date,ticker,company,signal_type,signal_type_label_ja,expected_direction,expected_direction_label_ja,long_rank,short_rank,long_rank_label_ja,short_rank_label_ja,t1,t5,t20,gate_status,gate_status_label_ja,source_path,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(signal_id,date) DO UPDATE SET
            ticker=excluded.ticker,company=excluded.company,signal_type=excluded.signal_type,signal_type_label_ja=excluded.signal_type_label_ja,
            expected_direction=excluded.expected_direction,expected_direction_label_ja=excluded.expected_direction_label_ja,
            long_rank=excluded.long_rank,short_rank=excluded.short_rank,long_rank_label_ja=excluded.long_rank_label_ja,short_rank_label_ja=excluded.short_rank_label_ja,
            t1=excluded.t1,t5=excluded.t5,t20=excluded.t20,
            gate_status=excluded.gate_status,gate_status_label_ja=excluded.gate_status_label_ja,source_path=excluded.source_path,updated_at=excluded.updated_at
            """,
            (
                r.get("signal_id",""), date, r.get("ticker",""), r.get("company",""), r.get("signalType",""),
                signal_type_label_ja(r.get("signalType","")),
                r.get("expectedDirection",""), expected_direction_label_ja(r.get("expectedDirection","")),
                r.get("longSignalRank",""), r.get("shortSignalRank",""),
                rank_label_ja(r.get("longSignalRank","")), rank_label_ja(r.get("shortSignalRank","")),
                r.get("t1",""), r.get("t5",""), r.get("t20",""), r.get("gateStatus",""),
                gate_status_label_ja(r.get("gateStatus","")),
                str(path.relative_to(ROOT)), now(),
            ),
        )
    conn.execute("INSERT INTO ingest_log(run_at,kind,source_path,rows) VALUES(?,?,?,?)", (now(), "signals", str(path.relative_to(ROOT)), len(rows)))


def upsert_entry_candidates(conn: sqlite3.Connection, path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    date = data.get("date", path.name[:10])
    rows = 0
    for side, key, rank_field in (("long", "longEntryCandidates", "longSignalRank"), ("short", "shortEntryCandidates", "shortSignalRank")):
        for r in data.get(key, []):
            conn.execute(
                """
                INSERT INTO entry_candidates(date,side,signal_id,ticker,company,rank,expected_direction,trade_use,source_path,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(date,side,signal_id) DO UPDATE SET
                ticker=excluded.ticker,company=excluded.company,rank=excluded.rank,expected_direction=excluded.expected_direction,
                trade_use=excluded.trade_use,source_path=excluded.source_path,updated_at=excluded.updated_at
                """,
                (date, side, r.get("signalId",""), r.get("ticker",""), r.get("company",""), r.get(rank_field,""), r.get("expectedDirection",""), r.get("tradeUse",""), str(path.relative_to(ROOT)), now()),
            )
            rows += 1
    conn.execute("INSERT INTO ingest_log(run_at,kind,source_path,rows) VALUES(?,?,?,?)", (now(), "entry_candidates", str(path.relative_to(ROOT)), rows))


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
    for r in rows:
        ticker = r.get("ticker", "")
        if not ticker:
            m = re.match(r"([0-9]{4}|[0-9]{3}[A-Z])\s+", r.get("title", ""))
            ticker = m.group(1) if m else ""
        conn.execute(
            """
            INSERT INTO backtest_outcomes(outcome_id,date,source_signal_id,ticker,signal_date,disclosure_category,disclosure_category_label_ja,signal_type,signal_type_label_ja,expected_direction,expected_direction_label_ja,long_rank,short_rank,long_rank_label_ja,short_rank_label_ja,t1_judge,t5_judge,t20_judge,outcome_type,source_path,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(outcome_id,date) DO UPDATE SET
            source_signal_id=excluded.source_signal_id,ticker=excluded.ticker,signal_date=excluded.signal_date,
            disclosure_category=excluded.disclosure_category,disclosure_category_label_ja=excluded.disclosure_category_label_ja,
            signal_type=excluded.signal_type,signal_type_label_ja=excluded.signal_type_label_ja,
            expected_direction=excluded.expected_direction,expected_direction_label_ja=excluded.expected_direction_label_ja,
            long_rank=excluded.long_rank,short_rank=excluded.short_rank,long_rank_label_ja=excluded.long_rank_label_ja,short_rank_label_ja=excluded.short_rank_label_ja,t1_judge=excluded.t1_judge,t5_judge=excluded.t5_judge,
            t20_judge=excluded.t20_judge,outcome_type=excluded.outcome_type,source_path=excluded.source_path,updated_at=excluded.updated_at
            """,
            (
                r.get("outcome_id",""), date, r.get("sourceSignalId",""), ticker, r.get("signalDate",""),
                r.get("disclosureCategory",""), disclosure_category_label_ja(r.get("disclosureCategory","")),
                r.get("signalType",""), signal_type_label_ja(r.get("signalType","")),
                r.get("expectedDirection",""), expected_direction_label_ja(r.get("expectedDirection","")),
                r.get("longSignalRank",""), r.get("shortSignalRank",""),
                rank_label_ja(r.get("longSignalRank","")), rank_label_ja(r.get("shortSignalRank","")),
                r.get("T+1Judge",""), r.get("T+5Judge",""), r.get("T+20Judge",""), r.get("roughOutcomeType",""),
                str(path.relative_to(ROOT)), now(),
            ),
        )
    conn.execute("INSERT INTO ingest_log(run_at,kind,source_path,rows) VALUES(?,?,?,?)", (now(), "backtest_outcomes", str(path.relative_to(ROOT)), len(rows)))


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


def main() -> int:
    args = parse_args()
    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    try:
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
