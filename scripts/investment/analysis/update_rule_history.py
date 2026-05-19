#!/usr/bin/env python3
"""Update cumulative rule history from daily rule dashboards."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
JST = timezone(timedelta(hours=9))
DASHBOARD = ROOT / "topics/investment-research/inbox/{date}-rule-dashboard.json"
OUTPUT_JSON = ROOT / "topics/investment-research/rule-history.json"
OUTPUT_MD = ROOT / "topics/investment-research/rule-history.md"


def rule_id(row: dict) -> str:
    safe_rule = str(row.get("rule", "")).replace(" ", "_")
    return f"{row.get('side')}::{row.get('bucket')}::{safe_rule}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Update cumulative rule history.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    args = parser.parse_args()

    src = Path(str(DASHBOARD).format(date=args.date))
    dashboard = json.loads(src.read_text(encoding="utf-8"))
    if OUTPUT_JSON.exists():
        history = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
    else:
        history = {"updatedAt": "", "rules": {}}

    rules = history.setdefault("rules", {})
    for row in dashboard.get("rows", []):
        rid = rule_id(row)
        item = rules.setdefault(rid, {
            "side": row.get("side"),
            "bucket": row.get("bucket"),
            "rule": row.get("rule"),
            "snapshots": [],
        })
        item["side"] = row.get("side")
        item["bucket"] = row.get("bucket")
        item["rule"] = row.get("rule")
        snapshots = [s for s in item.get("snapshots", []) if s.get("date") != args.date]
        snapshots.append({
            "date": args.date,
            "appearances": row.get("appearances"),
            "period": row.get("period"),
            "t1": row.get("t1"),
            "t5": row.get("t5"),
            "t20": row.get("t20"),
            "dailyUse": row.get("dailyUse"),
            "status": row.get("status"),
        })
        item["snapshots"] = sorted(snapshots, key=lambda s: s.get("date", ""))

    history["updatedAt"] = datetime.now(JST).replace(microsecond=0).isoformat()
    OUTPUT_JSON.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    latest = []
    for item in rules.values():
        if not item.get("snapshots"):
            continue
        snap = item["snapshots"][-1]
        latest.append((item, snap))
    latest.sort(key=lambda pair: (
        {"active_rule": 0, "watch_rule": 1, "hypothesis_only": 2}.get(pair[1].get("status"), 9),
        pair[0].get("side", ""),
        pair[0].get("bucket", ""),
        pair[0].get("rule", ""),
    ))

    lines = [
        "# Investment Rule History",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- updatedAt: {history['updatedAt']}",
        "- caution: 売買助言ではなく、ルール再現性の累積履歴。",
        "",
        "## Latest Snapshot",
    ]
    for item, snap in latest[:80]:
        lines.append(
            f"- {item['side']} / {item['bucket']}: `{item['rule']}` latest={snap['date']} "
            f"appearances={snap['appearances']} status={snap['status']} dailyUse={snap['dailyUse']} / "
            f"T+1 {snap['t1']} / T+5 {snap['t5']} / T+20 {snap['t20']}"
        )
    lines.extend([
        "",
        "## How To Use",
        "- `active_rule` はdaily表示の優先候補。",
        "- `watch_rule` は該当銘柄が出た場合に補足する。",
        "- `hypothesis_only` は検証中として扱い、強いランク補正に使わない。",
    ])
    OUTPUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT_JSON.relative_to(ROOT)} rules={len(rules)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
