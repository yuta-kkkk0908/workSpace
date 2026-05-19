#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INBOX = ROOT / "topics" / "investment-research" / "inbox"

SIG_RE = re.compile(r"^###\s+([^:]+):\s*(.+)$", re.MULTILINE)
FIELD_RE = re.compile(r"^-\s+([A-Za-z0-9+_-]+):\s*(.*)$")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate long/short entry candidates from market-signals")
    p.add_argument("--date", required=True)
    p.add_argument("--max-long", type=int, default=8)
    p.add_argument("--max-short", type=int, default=8)
    p.add_argument("--max-watch-long", type=int, default=12)
    p.add_argument("--max-watch-short", type=int, default=12)
    p.add_argument("--fallback-days", type=int, default=0, help="if target date file is missing, look back N days")
    return p.parse_args()


def resolve_source(date_str: str, fallback_days: int) -> tuple[Path, str]:
    base = datetime.strptime(date_str, "%Y-%m-%d").date()
    src = INBOX / f"{date_str}-market-signals.md"
    if src.exists():
        return src, date_str
    for i in range(1, max(0, fallback_days) + 1):
        d = (base - timedelta(days=i)).isoformat()
        p = INBOX / f"{d}-market-signals.md"
        if p.exists():
            return p, d
    raise SystemExit(f"market-signals not found: {src} (fallback_days={fallback_days})")


def parse_signals(text: str) -> list[dict[str, str]]:
    starts = [m.start() for m in SIG_RE.finditer(text)]
    if not starts:
        return []
    starts.append(len(text))
    rows = []
    for i in range(len(starts) - 1):
        chunk = text[starts[i]:starts[i + 1]]
        first = chunk.splitlines()[0]
        m = SIG_RE.match(first)
        if not m:
            continue
        signal_id, title = m.group(1).strip(), m.group(2).strip()
        row = {"signalId": signal_id, "title": title}
        for line in chunk.splitlines()[1:]:
            f = FIELD_RE.match(line.strip())
            if f:
                row[f.group(1)] = f.group(2)
        rows.append(row)
    return rows


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


def score_long(row: dict[str, str]) -> int:
    s = 0
    if row.get("longSignalRank") == "A":
        s += 6
    elif row.get("longSignalRank", "").startswith("A"):
        s += 5
    elif row.get("longSignalRank") == "B":
        s += 4
    elif row.get("longSignalRank") == "C":
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
    if row.get("shortSignalRank") == "A":
        s += 6
    elif row.get("shortSignalRank", "").startswith("A"):
        s += 5
    elif row.get("shortSignalRank") == "B":
        s += 4
    elif row.get("shortSignalRank") == "C":
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
        if r.get("longSignalRank") in {"A", "B"} and r.get("expectedDirection") in {"up", "up_watch"}:
            e = to_entry(r)
            e["candidateType"] = "primary"
            e["score"] = str(score_long(r))
            out.append(e)
    out.sort(key=lambda x: int(x.get("score", "0")), reverse=True)
    return out[:max_n]


def pick_short(rows: list[dict[str, str]], max_n: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for r in rows:
        if r.get("shortSignalRank") in {"A", "B"} and r.get("expectedDirection") in {"down", "down_watch"}:
            e = to_entry(r)
            e["candidateType"] = "primary"
            e["score"] = str(score_short(r))
            out.append(e)
    out.sort(key=lambda x: int(x.get("score", "0")), reverse=True)
    return out[:max_n]


def pick_watch_long(rows: list[dict[str, str]], max_n: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for r in rows:
        # Relaxed: allow C when confirmation/gate exists.
        if r.get("expectedDirection") not in {"up", "up_watch"}:
            continue
        lr = r.get("longSignalRank", "")
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
        if r.get("expectedDirection") not in {"down", "down_watch"}:
            continue
        sr = r.get("shortSignalRank", "")
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
    src, source_date = resolve_source(args.date, args.fallback_days)

    rows = parse_signals(src.read_text(encoding="utf-8"))
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
        "source": str(src.relative_to(ROOT)),
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
        f"- source: {src.relative_to(ROOT)}",
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
    print(f"wrote {out_md.relative_to(ROOT)} and {out_json.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
