#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INBOX = ROOT / "topics" / "investment-research" / "inbox"

HEAD_RE = re.compile(r"^###\s+([^:]+):\s*(.+)$", re.M)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Nightly technical check and rank re-evaluation for market-signals")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--fallback-days", type=int, default=3)
    return p.parse_args()


def find_signals_file(date_str: str, fallback_days: int) -> Path:
    d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
    for i in range(0, max(0, fallback_days) + 1):
        d = (d0 - timedelta(days=i)).isoformat()
        p = INBOX / f"{d}-market-signals.md"
        if p.exists():
            return p
    raise SystemExit(f"market-signals not found for {date_str} (fallback_days={fallback_days})")


def split_chunks(text: str) -> list[tuple[str, str]]:
    starts = [m.start() for m in HEAD_RE.finditer(text)]
    if not starts:
        return []
    starts.append(len(text))
    out = []
    for i in range(len(starts) - 1):
        chunk = text[starts[i] : starts[i + 1]]
        head = chunk.splitlines()[0]
        out.append((head, chunk))
    return out


def get_field(chunk: str, key: str, nested: bool = False) -> str:
    if nested:
        m = re.search(rf"^\s{{2}}-\s+{re.escape(key)}:\s*(.*)$", chunk, re.M)
    else:
        m = re.search(rf"^-\s+{re.escape(key)}:\s*(.*)$", chunk, re.M)
    return (m.group(1).strip() if m else "")


def set_field(chunk: str, key: str, value: str, nested: bool = False) -> str:
    if nested:
        pat = re.compile(rf"^(\s{{2}}-\s+{re.escape(key)}:\s*).*$", re.M)
        rep = rf"\1{value}"
    else:
        pat = re.compile(rf"^(-\s+{re.escape(key)}:\s*).*$", re.M)
        rep = rf"\1{value}"
    if pat.search(chunk):
        return pat.sub(rep, chunk)
    if nested:
        if "  - technicalSignalChecked:" in chunk:
            return chunk.replace("  - technicalSignalChecked:", f"  - {key}: {value}\n  - technicalSignalChecked:", 1)
        if "- requiredCheck:" in chunk:
            return chunk.replace("- requiredCheck:", f"- requiredCheck:\n  - {key}: {value}", 1)
    return chunk


def tokens(signal_type: str) -> set[str]:
    parts = [p.strip() for p in re.split(r"\s*/\s*|\s*,\s*", signal_type or "") if p.strip()]
    return {p.lower() for p in parts}


def rerank(chunk: str) -> tuple[str, bool]:
    signal_type = get_field(chunk, "signalType")
    expected = get_field(chunk, "expectedDirection").lower()
    gate = get_field(chunk, "gateStatus", nested=True).lower()
    material = get_field(chunk, "materialSignalChecked", nested=True).lower()
    external = get_field(chunk, "externalContextChecked", nested=True).lower()
    lr = get_field(chunk, "longSignalRank")
    sr = get_field(chunk, "shortSignalRank")
    conf = get_field(chunk, "confidence", nested=True)

    tk = tokens(signal_type)
    tech_ok = False
    upgraded = False
    reason = "neutral"

    if expected.startswith("up"):
        if "technical_breakout" in tk:
            tech_ok = True
            reason = "breakout"
            if lr in {"B", "B+"}:
                lr = "A-"
                upgraded = True
        elif "relative_strength" in tk and gate == "pass":
            tech_ok = True
            reason = "relative_strength"
    elif expected.startswith("down"):
        if "technical_breakdown" in tk:
            tech_ok = True
            reason = "breakdown"
            if sr in {"B", "B+"}:
                sr = "A-"
                upgraded = True
        elif "sell_the_news" in tk and gate == "pass" and external == "yes":
            tech_ok = True
            reason = "sell_the_news"

    # Secondary conservative upgrades when confirmations are complete.
    if material == "yes" and external == "yes" and gate == "pass":
        if expected.startswith("up") and lr == "B" and {"earnings_positive", "self_buyback"} & tk:
            lr = "A-"
            upgraded = True
            tech_ok = True
            reason = "material+confirmation"
        if expected.startswith("down") and sr == "B" and {"earnings_negative"} & tk:
            sr = "A-"
            upgraded = True
            tech_ok = True
            reason = "material+confirmation"

    chunk = set_field(chunk, "technicalSignalChecked", "yes", nested=True)
    chunk = set_field(chunk, "longSignalRank", lr)
    chunk = set_field(chunk, "shortSignalRank", sr)
    if upgraded and conf == "medium":
        chunk = set_field(chunk, "confidence", "high", nested=True)

    signal_rank = "B"
    if "A" in lr or "A" in sr:
        signal_rank = "A-"
    elif lr.startswith("C") and sr.startswith("C"):
        signal_rank = "C"
    chunk = set_field(chunk, "signalRank", signal_rank)
    chunk = set_field(chunk, "technicalSignalNote", reason, nested=True)
    return chunk, upgraded


def main() -> int:
    args = parse_args()
    path = find_signals_file(args.date, args.fallback_days)
    text = path.read_text(encoding="utf-8")
    chunks = split_chunks(text)
    if not chunks:
        print(f"no signal chunks: {path.relative_to(ROOT)}")
        return 0

    upgraded = 0
    out = text
    for _head, old in chunks:
        new, up = rerank(old)
        if up:
            upgraded += 1
        out = out.replace(old, new, 1)

    path.write_text(out, encoding="utf-8")
    print(f"updated: {path.relative_to(ROOT)} upgraded={upgraded}/{len(chunks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
