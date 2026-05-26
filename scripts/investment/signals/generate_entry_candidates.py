#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INBOX = ROOT / "topics" / "investment-research" / "inbox"
DEFAULT_DB = ROOT / "data" / "investment.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate long/short entry candidates from market-signals")
    p.add_argument("--date", required=True)
    p.add_argument("--max-long", type=int, default=8)
    p.add_argument("--max-short", type=int, default=8)
    p.add_argument("--max-watch-long", type=int, default=12)
    p.add_argument("--max-watch-short", type=int, default=12)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    return p.parse_args()


def load_signals_from_db(db_path: Path, date_str: str) -> list[dict[str, str]]:
    if not db_path.exists():
        raise SystemExit(f"db not found: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT signal_id,ticker,company,expected_direction,long_rank,short_rank,url,gate_status,
                   material_signal_checked,external_context_checked,technical_signal_checked,source
            FROM signals
            WHERE date=?
            ORDER BY signal_id
            """,
            (date_str,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        raise SystemExit(f"signals not found in DB for {date_str}")
    out: list[dict[str, str]] = []
    for r in rows:
        out.append(
            {
                "signalId": r["signal_id"] or "",
                "ticker": r["ticker"] or "",
                "company": r["company"] or "",
                "expectedDirection": r["expected_direction"] or "",
                "longSignalRank": r["long_rank"] or "",
                "shortSignalRank": r["short_rank"] or "",
                "tradeUse": "",
                "url": r["url"] or "",
                "gateStatus": r["gate_status"] or "",
                "materialSignalChecked": r["material_signal_checked"] or "",
                "externalContextChecked": r["external_context_checked"] or "",
                "technicalSignalChecked": r["technical_signal_checked"] or "",
                "source": r["source"] or "",
            }
        )
    return out


def to_entry(row: dict[str, str]) -> dict[str, str]:
    return {
        "signalId": row.get("signalId", ""),
        "ticker": row.get("ticker", ""),
        "company": row.get("company", ""),
        "expectedDirection": row.get("expectedDirection", ""),
        "longSignalRank": row.get("longSignalRank", ""),
        "shortSignalRank": row.get("shortSignalRank", ""),
        "tradeUse": row.get("tradeUse", ""),
        "url": row.get("url", ""),
        "gateStatus": row.get("gateStatus", ""),
        "materialSignalChecked": row.get("materialSignalChecked", ""),
        "externalContextChecked": row.get("externalContextChecked", ""),
        "technicalSignalChecked": row.get("technicalSignalChecked", ""),
    }


def yes(v: str) -> bool:
    return (v or "").strip().lower() == "yes"


def gate_pass(v: str) -> bool:
    return (v or "").strip().lower() == "pass"


def gate_hold(v: str) -> bool:
    s = (v or "").strip().lower()
    return s.startswith("hold")


def gate_watch_block(v: str) -> bool:
    s = (v or "").strip().lower()
    # Keep watch candidates when credit status is just unknown.
    if s in {"hold_credit_unknown", "hold_borrow_unknown"}:
        return False
    # Hard block for clearly non-tradable statuses.
    hard_tokens = ("non_margin", "credit_unavailable", "borrow_unavailable")
    return any(tok in s for tok in hard_tokens)


def rank_bucket(v: str) -> str:
    r = (v or "").strip().upper()
    if not r:
        return ""
    if r.startswith("A"):
        return "A"
    if r.startswith("B"):
        return "B"
    if r.startswith("C"):
        return "C"
    return r


def score_long(row: dict[str, str]) -> int:
    s = 0
    rb = rank_bucket(row.get("longSignalRank", ""))
    if rb == "A":
        s += 6
    elif rb == "B":
        s += 4
    elif rb == "C":
        s += 2
    if row.get("expectedDirection") in {"up", "up_watch"}:
        s += 2
    if gate_pass(row.get("gateStatus", "")):
        s += 2
    if yes(row.get("materialSignalChecked", "")):
        s += 1
    if yes(row.get("externalContextChecked", "")):
        s += 1
    if yes(row.get("technicalSignalChecked", "")):
        s += 1
    return s


def score_short(row: dict[str, str]) -> int:
    s = 0
    rb = rank_bucket(row.get("shortSignalRank", ""))
    if rb == "A":
        s += 6
    elif rb == "B":
        s += 4
    elif rb == "C":
        s += 2
    if row.get("expectedDirection") in {"down", "down_watch"}:
        s += 2
    if gate_pass(row.get("gateStatus", "")):
        s += 2
    if yes(row.get("materialSignalChecked", "")):
        s += 1
    if yes(row.get("externalContextChecked", "")):
        s += 1
    if yes(row.get("technicalSignalChecked", "")):
        s += 1
    return s


def pick_long(rows: list[dict[str, str]], max_n: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for r in rows:
        if gate_hold(r.get("gateStatus", "")):
            continue
        if rank_bucket(r.get("longSignalRank", "")) in {"A", "B"} and r.get("expectedDirection") in {"up", "up_watch"}:
            e = to_entry(r)
            e["candidateType"] = "primary"
            e["score"] = str(score_long(r))
            out.append(e)
    out.sort(key=lambda x: int(x.get("score", "0")), reverse=True)
    return out[:max_n]


def pick_short(rows: list[dict[str, str]], max_n: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for r in rows:
        if gate_hold(r.get("gateStatus", "")):
            continue
        if rank_bucket(r.get("shortSignalRank", "")) in {"A", "B"} and r.get("expectedDirection") in {"down", "down_watch"}:
            e = to_entry(r)
            e["candidateType"] = "primary"
            e["score"] = str(score_short(r))
            out.append(e)
    out.sort(key=lambda x: int(x.get("score", "0")), reverse=True)
    return out[:max_n]


def pick_watch_long(rows: list[dict[str, str]], max_n: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for r in rows:
        if gate_watch_block(r.get("gateStatus", "")):
            continue
        # Relaxed: allow C when confirmation/gate exists.
        if r.get("expectedDirection") not in {"up", "up_watch"}:
            continue
        lr = rank_bucket(r.get("longSignalRank", ""))
        if lr not in {"A", "B", "C"}:
            continue
        if lr == "C" and not (gate_pass(r.get("gateStatus", "")) or yes(r.get("materialSignalChecked", ""))):
            continue
        e = to_entry(r)
        e["candidateType"] = "watch"
        e["score"] = str(score_long(r))
        out.append(e)
    out.sort(key=lambda x: int(x.get("score", "0")), reverse=True)
    return out[:max_n]


def pick_watch_short(rows: list[dict[str, str]], max_n: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for r in rows:
        if gate_watch_block(r.get("gateStatus", "")):
            continue
        if r.get("expectedDirection") not in {"down", "down_watch"}:
            continue
        sr = rank_bucket(r.get("shortSignalRank", ""))
        if sr not in {"A", "B", "C"}:
            continue
        if sr == "C" and not (gate_pass(r.get("gateStatus", "")) or yes(r.get("materialSignalChecked", ""))):
            continue
        e = to_entry(r)
        e["candidateType"] = "watch"
        e["score"] = str(score_short(r))
        out.append(e)
    out.sort(key=lambda x: int(x.get("score", "0")), reverse=True)
    return out[:max_n]


def main() -> int:
    args = parse_args()
    source_date = args.date
    rows = load_signals_from_db(args.db, args.date)
    long_entries = pick_long(rows, args.max_long)
    short_entries = pick_short(rows, args.max_short)
    watch_long_entries = pick_watch_long(rows, args.max_watch_long)
    watch_short_entries = pick_watch_short(rows, args.max_watch_short)
    primary_ids = {e.get("signalId", "") for e in (long_entries + short_entries)}
    watch_long_entries = [e for e in watch_long_entries if e.get("signalId", "") not in primary_ids][: args.max_watch_long]
    watch_short_entries = [e for e in watch_short_entries if e.get("signalId", "") not in primary_ids][: args.max_watch_short]

    data = {
        "date": args.date,
        "sourceDate": source_date,
        "source": "db:signals",
        "longEntryCandidates": long_entries,
        "shortEntryCandidates": short_entries,
        "longWatchCandidates": watch_long_entries,
        "shortWatchCandidates": watch_short_entries,
        "counts": {
            "totalSignals": len(rows),
            "longPrimary": len(long_entries),
            "shortPrimary": len(short_entries),
            "longWatch": len(watch_long_entries),
            "shortWatch": len(watch_short_entries),
        },
        "caution": "売買助言ではなく、監視候補の抽出結果。",
    }

    out_json = INBOX / f"{args.date}-entry-candidates.json"
    out_md = INBOX / f"{args.date}-entry-candidates.md"
    out_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# {args.date} Entry Candidates",
        "",
        "- caution: 売買助言ではなく、監視候補の抽出結果。",
        f"- sourceDate: {source_date}",
        "- source: db:signals",
        f"- totalSignals: {len(rows)}",
        f"- longPrimaryCandidates: {len(long_entries)}",
        f"- shortPrimaryCandidates: {len(short_entries)}",
        f"- longWatchCandidates: {len(watch_long_entries)}",
        f"- shortWatchCandidates: {len(watch_short_entries)}",
        "",
        "## Long Entry Candidates (Primary)",
    ]
    if long_entries:
        for r in long_entries:
            lines.append(f"- {r['ticker']} {r['company']} ({r['longSignalRank']}) score={r.get('score','')} / {r['expectedDirection']} / {r['tradeUse']}")
            if r.get("url"):
                lines.append(f"  - {r['url']}")
    else:
        lines.append("- N/C")

    lines.extend(["", "## Short Entry Candidates (Primary)"])
    if short_entries:
        for r in short_entries:
            lines.append(f"- {r['ticker']} {r['company']} ({r['shortSignalRank']}) score={r.get('score','')} / {r['expectedDirection']} / {r['tradeUse']}")
            if r.get("url"):
                lines.append(f"  - {r['url']}")
    else:
        lines.append("- N/C")

    lines.extend(["", "## Long Watch Candidates (Relaxed)"])
    if watch_long_entries:
        for r in watch_long_entries:
            lines.append(f"- {r['ticker']} {r['company']} ({r['longSignalRank']}) score={r.get('score','')} / {r['expectedDirection']} / gate={r.get('gateStatus','')}")
    else:
        lines.append("- N/C")

    lines.extend(["", "## Short Watch Candidates (Relaxed)"])
    if watch_short_entries:
        for r in watch_short_entries:
            lines.append(f"- {r['ticker']} {r['company']} ({r['shortSignalRank']}) score={r.get('score','')} / {r['expectedDirection']} / gate={r.get('gateStatus','')}")
    else:
        lines.append("- N/C")

    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # DB-first: persist candidates directly.
    conn = sqlite3.connect(args.db)
    try:
        conn.execute("DELETE FROM entry_candidates WHERE date=?", (args.date,))
        def upsert(side: str, ctype: str, items: list[dict[str, str]]) -> None:
            for r in items:
                conn.execute(
                    """
                    INSERT INTO entry_candidates(
                      date,side,candidate_type,signal_id,ticker,company,rank,long_rank,short_rank,expected_direction,
                      trade_use,gate_status,material_signal_checked,external_context_checked,technical_signal_checked,score,url,source_path,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                    """,
                    (
                        args.date,
                        side,
                        ctype,
                        r.get("signalId", ""),
                        r.get("ticker", ""),
                        r.get("company", ""),
                        r.get("longSignalRank", "") if side == "long" else r.get("shortSignalRank", ""),
                        r.get("longSignalRank", ""),
                        r.get("shortSignalRank", ""),
                        r.get("expectedDirection", ""),
                        r.get("tradeUse", ""),
                        r.get("gateStatus", ""),
                        r.get("materialSignalChecked", ""),
                        r.get("externalContextChecked", ""),
                        r.get("technicalSignalChecked", ""),
                        int(r.get("score", "0") or 0),
                        r.get("url", ""),
                        "db:signals",
                    ),
                )
        upsert("long", "primary", long_entries)
        upsert("short", "primary", short_entries)
        upsert("long", "watch", watch_long_entries)
        upsert("short", "watch", watch_short_entries)
        conn.commit()
    finally:
        conn.close()

    print(f"wrote {out_md.relative_to(ROOT)} and {out_json.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
