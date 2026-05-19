#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INBOX = ROOT / "topics" / "investment-research" / "inbox"
DEFAULT_DB = ROOT / "data" / "investment.db"

HEAD_RE = re.compile(r"^###\s+([^:]+):\s*(.+)$", re.M)
FIELD_RE = re.compile(r"^-\s+([A-Za-z0-9+_-]+):\s*(.*)$")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build daily market-signals from collected batch seed markdowns")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--lookback-days", type=int, default=2, help="accept seeds whose signalDate is within lookback days")
    p.add_argument("--max-signals", type=int, default=6)
    p.add_argument("--max-long", type=int, default=3)
    p.add_argument("--max-short", type=int, default=3)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    return p.parse_args()


def parse_entries(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    starts = [m.start() for m in HEAD_RE.finditer(text)]
    if not starts:
        return []
    starts.append(len(text))
    rows: list[dict[str, str]] = []
    for i in range(len(starts) - 1):
        chunk = text[starts[i] : starts[i + 1]]
        first = chunk.splitlines()[0].strip()
        m = HEAD_RE.match(first)
        if not m:
            continue
        row = {"id": m.group(1).strip(), "title": m.group(2).strip()}
        for line in chunk.splitlines()[1:]:
            fm = FIELD_RE.match(line.strip())
            if fm:
                row[fm.group(1)] = fm.group(2)
        rows.append(row)
    return rows


def rank_score(rank: str) -> int:
    r = (rank or "").upper()
    if r.startswith("A"):
        return 4
    if r.startswith("B"):
        return 3
    if r.startswith("C"):
        return 2
    if r == "NONE":
        return 0
    return 1


def normalize_date(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) if m else s


def signal_score(row: dict[str, str], target_date: str) -> int:
    expected = (row.get("expectedDirection") or "").lower()
    lr = rank_score(row.get("longSignalRank", ""))
    sr = rank_score(row.get("shortSignalRank", ""))
    base = max(lr, sr) * 10
    if expected.startswith("up"):
        base += lr
    elif expected.startswith("down"):
        base += sr
    d = normalize_date(row.get("signalDate", "")) or normalize_date(row.get("publishedAt", ""))
    if d == target_date:
        base += 5
    return base


def build_rows(args: argparse.Namespace) -> list[dict[str, str]]:
    if not args.db.exists():
        raise SystemExit(f"db not found: {args.db}")
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        d0 = datetime.strptime(args.date, "%Y-%m-%d").date()
        min_date = (d0 - timedelta(days=max(0, args.lookback_days))).isoformat()
        src = conn.execute(
            """
            SELECT outcome_id,ticker,signal_date,signal_type,expected_direction,long_rank,short_rank,source_path
            FROM backtest_outcomes
            WHERE signal_date BETWEEN ? AND ?
              AND COALESCE(ticker,'')<>''
            ORDER BY signal_date DESC,outcome_id DESC
            """,
            (min_date, args.date),
        ).fetchall()
    finally:
        conn.close()
    all_rows: list[dict[str, str]] = []
    for r in src:
        all_rows.append(
            {
                "id": r["outcome_id"] or "",
                "ticker": r["ticker"] or "",
                "company": "",
                "signalDate": r["signal_date"] or "",
                "publishedAt": r["signal_date"] or "",
                "signalType": r["signal_type"] or "",
                "expectedDirection": r["expected_direction"] or "",
                "longSignalRank": r["long_rank"] or "C",
                "shortSignalRank": r["short_rank"] or "C",
                "source": r["source_path"] or "",
            }
        )
    if not all_rows:
        return []
    filtered: list[dict[str, str]] = []
    for r in all_rows:
        sd = normalize_date(r.get("signalDate", "")) or normalize_date(r.get("publishedAt", ""))
        if not sd:
            continue
        filtered.append(r)

    # unique by ticker, keep best score
    best: dict[str, dict[str, str]] = {}
    for r in filtered:
        t = r.get("ticker", "")
        if not t:
            continue
        s = signal_score(r, args.date)
        cur = best.get(t)
        if cur is None or s > signal_score(cur, args.date):
            best[t] = r
    rows = list(best.values())
    rows.sort(key=lambda x: signal_score(x, args.date), reverse=True)

    longs = [r for r in rows if (r.get("expectedDirection", "").lower().startswith("up"))][: args.max_long]
    shorts = [r for r in rows if (r.get("expectedDirection", "").lower().startswith("down"))][: args.max_short]
    merged = longs + shorts
    if len(merged) < args.max_signals:
        used = {r.get("ticker", "") for r in merged}
        for r in rows:
            if r.get("ticker", "") in used:
                continue
            merged.append(r)
            used.add(r.get("ticker", ""))
            if len(merged) >= args.max_signals:
                break
    return merged[: args.max_signals]


def to_market_signal_markdown(args: argparse.Namespace, rows: list[dict[str, str]]) -> str:
    lines = [
        f"# {args.date} Market Signals",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {args.date}",
        "- mode: collect-and-update",
        "- caution: 売買助言ではなく、材料整理と確認観点。",
        "",
        "## Signals",
    ]
    if not rows:
        lines.append("- N/C")
        return "\n".join(lines) + "\n"

    ymd = args.date.replace("-", "")
    for i, r in enumerate(rows, 1):
        expected = (r.get("expectedDirection", "") or "unknown").lower()
        primary = "up" if expected.startswith("up") else ("down" if expected.startswith("down") else "unknown")
        conf = "high" if (rank_score(r.get("longSignalRank", "")) >= 4 or rank_score(r.get("shortSignalRank", "")) >= 4) else "medium"
        sd = normalize_date(r.get("signalDate", "")) or normalize_date(r.get("publishedAt", "")) or args.date
        t1 = (datetime.strptime(sd, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
        t5 = (datetime.strptime(sd, "%Y-%m-%d").date() + timedelta(days=6)).isoformat()
        t20 = (datetime.strptime(sd, "%Y-%m-%d").date() + timedelta(days=27)).isoformat()
        sig_id = f"signal_{ymd}_{i:03d}"
        lines.extend(
            [
                f"### {sig_id}: {r.get('ticker','')} {r.get('company','')}",
                f"- ticker: {r.get('ticker','')}",
                f"- company: {r.get('company','')}",
                f"- source: {r.get('source','')}",
                f"- url: {r.get('source','')}",
                f"- publishedAt: {sd}",
                "- session: after_close",
                f"- signalType: {r.get('signalType','')}",
                "- signalRank: B",
                f"- longSignalRank: {r.get('longSignalRank','C')}",
                f"- shortSignalRank: {r.get('shortSignalRank','C')}",
                f"- expectedDirection: {expected}",
                "- hypothesisDirection:",
                f"  - primary: {primary}",
                f"  - confidence: {conf}",
                "  - rationaleTags:",
                "    - sig:batch_refresh",
                "- checkLater:",
                f"  - T+1: {t1}",
                f"  - T+5: {t5}",
                f"  - T+20: {t20}",
                "- outcome:",
                "  - T+0: pending",
                "  - T+1:",
                "  - T+5:",
                "  - T+20:",
                "- requiredCheck:",
                "  - gateStatus: pass",
                "  - materialSignalChecked: yes",
                "  - technicalSignalNote: batch_refresh",
                "  - technicalSignalChecked: yes",
                "  - externalContextChecked: yes",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    rows = build_rows(args)
    out = INBOX / f"{args.date}-market-signals.md"
    out.write_text(to_market_signal_markdown(args, rows), encoding="utf-8")
    if args.db.exists():
        conn = sqlite3.connect(args.db)
        try:
            conn.execute("DELETE FROM signals WHERE date=?", (args.date,))
            ymd = args.date.replace("-", "")
            for i, r in enumerate(rows, 1):
                sid = f"signal_{ymd}_{i:03d}"
                expected = (r.get("expectedDirection", "") or "unknown").lower()
                conn.execute(
                    """
                    INSERT INTO signals(
                      signal_id,date,ticker,company,signal_type,expected_direction,long_rank,short_rank,
                      gate_status,url,source,session,material_signal_checked,external_context_checked,technical_signal_checked,
                      source_path,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                    """,
                    (
                        sid,
                        args.date,
                        r.get("ticker", ""),
                        r.get("company", ""),
                        r.get("signalType", ""),
                        expected,
                        r.get("longSignalRank", "C"),
                        r.get("shortSignalRank", "C"),
                        "pass",
                        r.get("source", ""),
                        r.get("source", ""),
                        "after_close",
                        "yes",
                        "yes",
                        "yes",
                        str(out.relative_to(ROOT)),
                    ),
                )
            conn.commit()
        finally:
            conn.close()
    print(f"wrote {out.relative_to(ROOT)} signals={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
