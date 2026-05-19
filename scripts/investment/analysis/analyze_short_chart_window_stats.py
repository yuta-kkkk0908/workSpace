#!/usr/bin/env python3
"""Summarize short chart-window outcomes by follow-through and rebound risk."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
JST = timezone(timedelta(hours=9))
INPUT = ROOT / "topics/investment-research/inbox/{date}-short-chart-window-data.json"
OUTPUT_MD = ROOT / "topics/investment-research/inbox/{date}-short-chart-window-stats.md"
OUTPUT_JSON = ROOT / "topics/investment-research/inbox/{date}-short-chart-window-stats.json"


def outcome_label(value: str | None) -> str:
    return value if value in {"win", "loss", "flat", "pending"} else "unknown"


def win_rate(rows: list[dict], window: str) -> str:
    counts = Counter(outcome_label(row.get(window)) for row in rows)
    judged = counts["win"] + counts["loss"] + counts["flat"]
    rate = counts["win"] / judged * 100 if judged else 0.0
    return f"{counts['win']}/{counts['loss']}/{counts['flat']} pending={counts['pending']} wr={rate:.1f}%"


def group_key(row: dict) -> str:
    review = row.get("review", {})
    follow = review.get("followThrough", "unknown")
    rebound = review.get("reboundRisk", "unknown")
    return f"follow={follow} / rebound={rebound}"


def readiness_key(row: dict) -> str:
    return row.get("shortReadiness") or "unknown"


def serialize_group(rows: list[dict]) -> dict:
    return {
        "count": len(rows),
        "t1": Counter(outcome_label(r.get("t1")) for r in rows),
        "t5": Counter(outcome_label(r.get("t5")) for r in rows),
        "t20": Counter(outcome_label(r.get("t20")) for r in rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize short chart-window stats.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    args = parser.parse_args()

    src = Path(str(INPUT).format(date=args.date))
    data = json.loads(src.read_text(encoding="utf-8"))
    rows = [r for r in data.get("rows", []) if r.get("review", {}).get("status") == "ok"]

    by_chart: dict[str, list[dict]] = defaultdict(list)
    by_readiness: dict[str, list[dict]] = defaultdict(list)
    by_combo: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_chart[group_key(row)].append(row)
        by_readiness[readiness_key(row)].append(row)
        by_combo[f"{readiness_key(row)} / {group_key(row)}"].append(row)

    output = {
        "createdAt": datetime.now(JST).replace(microsecond=0).isoformat(),
        "mode": "short-chart-window-stats",
        "source": src.relative_to(ROOT).as_posix(),
        "caution": "粗い日足集計。売買助言ではない。nが小さいグループは仮説扱い。",
        "summary": {
            "rows": len(rows),
            "all": serialize_group(rows),
        },
        "byChart": {k: serialize_group(v) for k, v in sorted(by_chart.items())},
        "byReadiness": {k: serialize_group(v) for k, v in sorted(by_readiness.items())},
        "byReadinessAndChart": {k: serialize_group(v) for k, v in sorted(by_combo.items())},
    }
    Path(str(OUTPUT_JSON).format(date=args.date)).write_text(
        json.dumps(output, ensure_ascii=False, indent=2, default=dict) + "\n",
        encoding="utf-8",
    )

    lines = [
        f"# {args.date} Short Chart Window Stats",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {args.date}",
        "- mode: short-chart-window-stats",
        f"- sourceLog: {src.relative_to(ROOT / 'topics/investment-research').as_posix()}",
        "- caution: 粗い日足集計。売買助言ではない。nが小さいグループは仮説扱い。",
        "",
        "## Overall",
        f"- rows: {len(rows)}",
        f"- T+1: {win_rate(rows, 't1')}",
        f"- T+5: {win_rate(rows, 't5')}",
        f"- T+20: {win_rate(rows, 't20')}",
        "",
        "## By Chart Window",
    ]
    for key, group_rows in sorted(by_chart.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines.append(f"- {key} ({len(group_rows)}): T+1 {win_rate(group_rows, 't1')} / T+5 {win_rate(group_rows, 't5')} / T+20 {win_rate(group_rows, 't20')}")

    lines.extend(["", "## By Readiness"])
    for key, group_rows in sorted(by_readiness.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines.append(f"- {key} ({len(group_rows)}): T+1 {win_rate(group_rows, 't1')} / T+5 {win_rate(group_rows, 't5')} / T+20 {win_rate(group_rows, 't20')}")

    lines.extend(["", "## Candidate Lessons"])
    follow_rows = [r for r in rows if r.get("review", {}).get("followThrough") == "yes"]
    rebound_rows = [r for r in rows if r.get("review", {}).get("reboundRisk") == "yes"]
    no_rebound_rows = [r for r in rows if r.get("review", {}).get("reboundRisk") == "no"]
    lines.append(f"- `followThrough=yes`: {len(follow_rows)}件。T+1 {win_rate(follow_rows, 't1')} / T+5 {win_rate(follow_rows, 't5')}。短期ショート監視の中核候補。")
    lines.append(f"- `reboundRisk=yes`: {len(rebound_rows)}件。T+1 {win_rate(rebound_rows, 't1')} / T+5 {win_rate(rebound_rows, 't5')}。即追随より戻り売り待ちの検証対象。")
    lines.append(f"- `reboundRisk=no`: {len(no_rebound_rows)}件。T+1 {win_rate(no_rebound_rows, 't1')} / T+5 {win_rate(no_rebound_rows, 't5')}。下落継続候補として比較対象にする。")

    Path(str(OUTPUT_MD).format(date=args.date)).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {Path(str(OUTPUT_MD).format(date=args.date)).relative_to(ROOT)} rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
