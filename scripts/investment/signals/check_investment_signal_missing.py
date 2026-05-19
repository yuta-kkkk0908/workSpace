#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]

RE_SIGNAL = re.compile(r"^###\s+([^:]+):", re.MULTILINE)

REQUIRED = [
    "- expectedDirection:",
    "- hypothesisDirection:",
    "- checkLater:",
    "- outcome:",
    "  - T+1:",
    "  - T+5:",
    "  - T+20:",
    "- requiredCheck:",
    "  - gateStatus:",
]

def parse_args():
    p = argparse.ArgumentParser(description="Check required fields in market-signals markdown")
    p.add_argument("--date", required=True)
    p.add_argument("--topic", default="investment-research")
    return p.parse_args()

def main() -> int:
    args = parse_args()
    path = ROOT / "topics" / args.topic / "inbox" / f"{args.date}-market-signals.md"
    if not path.exists():
      print(f"missing_file: {path}")
      return 2
    text = path.read_text(encoding="utf-8")
    starts = [m.start() for m in RE_SIGNAL.finditer(text)]
    if not starts:
      print("signals: 0")
      return 0
    starts.append(len(text))
    issues = []
    for i in range(len(starts)-1):
      chunk = text[starts[i]:starts[i+1]]
      header = chunk.splitlines()[0].strip()
      miss = [x for x in REQUIRED if x not in chunk]
      if miss:
        issues.append((header, miss))
    print(f"file: {path}")
    print(f"signals: {len(starts)-1}")
    print(f"signals_with_missing: {len(issues)}")
    for h, miss in issues:
      print(f"- {h}")
      for m in miss:
        print(f"  - missing: {m}")
    return 1 if issues else 0

if __name__ == "__main__":
    raise SystemExit(main())
