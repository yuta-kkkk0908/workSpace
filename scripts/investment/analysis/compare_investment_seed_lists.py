#!/usr/bin/env python3
"""Compare rule-check results across investment seed lists."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
JST = timezone(timedelta(hours=9))
DEFAULT_MD = ROOT / "topics/investment-research/inbox/{date}-seed-list-comparison.md"
DEFAULT_JSON = ROOT / "topics/investment-research/inbox/{date}-seed-list-comparison.json"


def run_rule_check(date: str, seed_list: str, min_count: int, tmpdir: Path) -> dict:
    md = tmpdir / f"{seed_list}-rule-check.md"
    js = tmpdir / f"{seed_list}-rule-check.json"
    cmd = [
        sys.executable,
        str(ROOT / "scripts/investment/analysis/rule_check_market_outcomes.py"),
        "--date", date,
        "--seed-list", seed_list,
        "--min-count", str(min_count),
        "--md-output", str(md),
        "--json-output", str(js),
    ]
    subprocess.run(cmd, cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return json.loads(js.read_text(encoding="utf-8"))


def key_for(item: dict) -> str:
    return f"{item.get('ruleGroup')}::{item.get('label')}"


def compact_item(item: dict) -> dict:
    return {
        "ruleGroup": item.get("ruleGroup"),
        "label": item.get("label"),
        "judgement": item.get("judgement"),
        "direction": item.get("direction"),
        "rowCount": item.get("rowCount"),
        "t1Support": item.get("windows", {}).get("t1", {}).get("support"),
        "t1WinRate": item.get("windows", {}).get("t1", {}).get("winRate"),
        "t5Support": item.get("windows", {}).get("t5", {}).get("support"),
        "t5WinRate": item.get("windows", {}).get("t5", {}).get("winRate"),
        "t20Support": item.get("windows", {}).get("t20", {}).get("support"),
        "t20WinRate": item.get("windows", {}).get("t20", {}).get("winRate"),
    }


def compare(results: dict[str, dict]) -> dict:
    indexes = {
        name: {key_for(item): item for item in data.get("ruleCandidates", [])}
        for name, data in results.items()
    }
    all_keys = sorted(set().union(*(idx.keys() for idx in indexes.values()))) if indexes else []
    changed = []
    only_in: dict[str, list[str]] = {name: [] for name in indexes}
    for key in all_keys:
        present = [name for name, idx in indexes.items() if key in idx]
        if len(present) == 1:
            only_in[present[0]].append(key)
            continue
        judgements = {name: indexes[name][key].get("judgement") for name in present}
        directions = {name: indexes[name][key].get("direction") for name in present}
        counts = {name: indexes[name][key].get("rowCount") for name in present}
        if len(set(judgements.values())) > 1 or len(set(directions.values())) > 1 or max(counts.values()) != min(counts.values()):
            changed.append({
                "key": key,
                "judgements": judgements,
                "directions": directions,
                "rowCounts": counts,
                "items": {name: compact_item(indexes[name][key]) for name in present},
            })
    return {"onlyIn": only_in, "changed": changed}


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare investment rule-check results by seed list.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    parser.add_argument("--seed-list", action="append", dest="seed_lists", default=None)
    parser.add_argument("--min-count", type=int, default=8)
    parser.add_argument("--output-md", type=Path, default=None)
    parser.add_argument("--output-json", type=Path, default=None)
    args = parser.parse_args()
    seed_lists = args.seed_lists or ["rough_backtest_light", "rough_backtest_full"]

    with tempfile.TemporaryDirectory(prefix="investment-seed-compare-") as td:
        tmpdir = Path(td)
        results = {name: run_rule_check(args.date, name, args.min_count, tmpdir) for name in seed_lists}
    diff = compare(results)
    summary = {
        "createdAt": datetime.now(JST).replace(microsecond=0).isoformat(),
        "date": args.date,
        "mode": "seed-list-comparison",
        "seedLists": seed_lists,
        "minCount": args.min_count,
        "candidateCounts": {name: len(data.get("ruleCandidates", [])) for name, data in results.items()},
        "onlyInCounts": {name: len(items) for name, items in diff["onlyIn"].items()},
        "changedCount": len(diff["changed"]),
        "diff": diff,
    }
    output_json = args.output_json or Path(str(DEFAULT_JSON).format(date=args.date))
    output_md = args.output_md or Path(str(DEFAULT_MD).format(date=args.date))
    output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        f"# {args.date} Seed List Comparison",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {args.date}",
        "- mode: seed-list-comparison",
        "- caution: seed list差分の機械集計。売買助言ではない。",
        "",
        "## Summary",
        f"- seedLists: {', '.join(seed_lists)}",
        f"- minCount: {args.min_count}",
        f"- changedRules: {summary['changedCount']}",
    ]
    for name, count in summary["candidateCounts"].items():
        lines.append(f"- candidates.{name}: {count}")
    for name, count in summary["onlyInCounts"].items():
        lines.append(f"- onlyIn.{name}: {count}")
    lines.extend(["", "## Changed Rules"])
    if not diff["changed"]:
        lines.append("- none")
    for item in diff["changed"][:40]:
        lines.append(f"- `{item['key']}`")
        lines.append(f"  - judgements: {item['judgements']}")
        lines.append(f"  - rowCounts: {item['rowCounts']}")
    lines.extend(["", "## Only In"])
    for name, keys in diff["onlyIn"].items():
        lines.append(f"### {name}")
        if not keys:
            lines.append("- none")
        for key in keys[:40]:
            lines.append(f"- `{key}`")
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {output_md.relative_to(ROOT)} changed={summary['changedCount']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
