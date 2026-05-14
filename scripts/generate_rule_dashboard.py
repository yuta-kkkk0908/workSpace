#!/usr/bin/env python3
"""Generate a unified long/short rule dashboard for daily use."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
LONG_INPUT = ROOT / "topics/investment-research/inbox/{date}-long-rule-reproducibility.json"
SHORT_INPUT = ROOT / "topics/investment-research/inbox/{date}-short-conviction-data.json"
OUTPUT_MD = ROOT / "topics/investment-research/inbox/{date}-rule-dashboard.md"
OUTPUT_JSON = ROOT / "topics/investment-research/inbox/{date}-rule-dashboard.json"
BRIEF_MD = ROOT / "topics/investment-research/inbox/{date}-daily-rule-brief.md"


def compact_counts(counts: dict | None) -> str:
    counts = counts or {}
    win = counts.get("win", 0)
    loss = counts.get("loss", 0)
    flat = counts.get("flat", 0)
    pending = counts.get("pending", 0)
    judged = win + loss + flat
    wr = win / judged * 100 if judged else 0
    return f"{win}/{loss}/{flat} pending={pending} wr={wr:.1f}%"


def window_text_from_windows(windows: dict) -> dict[str, str]:
    out = {}
    for key in ("t1", "t5", "t20"):
        item = (windows or {}).get(key, {})
        win = item.get("win", 0)
        loss = item.get("loss", 0)
        flat = item.get("flat", 0)
        support = item.get("support", 0)
        wr = item.get("winRate")
        wr_text = "n/a" if wr is None else f"{float(wr):.1f}%"
        out[key] = f"{win}/{loss}/{flat} n={support} wr={wr_text}"
    return out


def long_daily_use(bucket: str) -> str:
    return {
        "strict_long_signal": "long_core_watch",
        "long_watch": "long_watch",
        "long_downgrade_or_avoid": "buy_avoid_or_exit",
        "long_short_term_only": "short_term_only",
    }.get(bucket, "watch")


def short_daily_use(bucket: str) -> str:
    return {
        "strict_short_signal": "short_core_watch",
        "return_short_wait": "return_short_wait",
        "tactical_low_liquidity_watch": "low_liquidity_short_caution",
        "buy_avoid_no_system_short": "buy_avoid_no_system_short",
        "return_short_wait_or_avoid": "return_short_wait_or_avoid",
        "exit_or_buy_avoid": "buy_avoid_or_exit",
        "event_only": "short_term_event_only",
    }.get(bucket, "watch")


def status_for(bucket: str, appearances: int, side: str) -> str:
    if side == "long" and bucket == "strict_long_signal" and appearances >= 20:
        return "active_rule"
    if side == "short" and bucket == "strict_short_signal" and appearances >= 8:
        return "active_rule"
    if appearances < 8:
        return "hypothesis_only"
    return "watch_rule"


def load_long(date: str) -> list[dict]:
    path = Path(str(LONG_INPUT).format(date=date))
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for row in data.get("rows", []):
        windows = row.get("windows") or {}
        wt = window_text_from_windows(windows)
        appearances = int(row.get("rowCount") or 0)
        rows.append({
            "side": "long",
            "bucket": row.get("bucket"),
            "rule": f"{row.get('ruleGroup')}: {row.get('label')}",
            "appearances": appearances,
            "period": f"{row.get('occurrencePeriodFirst', '')}..{row.get('occurrencePeriodLast', '')}",
            "t1": wt["t1"],
            "t5": wt["t5"],
            "t20": wt["t20"],
            "dailyUse": long_daily_use(row.get("bucket", "")),
            "status": status_for(row.get("bucket", ""), appearances, "long"),
        })
    return rows


def load_short(date: str) -> list[dict]:
    path = Path(str(SHORT_INPUT).format(date=date))
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    stats = data.get("ruleStats") or {}
    rows = []
    for bucket, stat in stats.items():
        appearances = int(stat.get("count") or 0)
        rows.append({
            "side": "short",
            "bucket": bucket,
            "rule": bucket,
            "appearances": appearances,
            "period": f"{stat.get('firstSignalDate', '')}..{stat.get('lastSignalDate', '')}",
            "t1": compact_counts(stat.get("t1")),
            "t5": compact_counts(stat.get("t5")),
            "t20": compact_counts(stat.get("t20")),
            "dailyUse": short_daily_use(bucket),
            "status": status_for(bucket, appearances, "short"),
        })
    order = {
        "strict_short_signal": 0,
        "return_short_wait": 1,
        "tactical_low_liquidity_watch": 2,
        "return_short_wait_or_avoid": 3,
        "buy_avoid_no_system_short": 4,
        "exit_or_buy_avoid": 5,
        "event_only": 6,
    }
    return sorted(rows, key=lambda r: (order.get(r["bucket"], 99), -r["appearances"]))


def row_line(row: dict) -> str:
    return (
        f"- {row['side']} / {row['bucket']}: `{row['rule']}` appearances={row['appearances']} "
        f"period={row['period']} status={row['status']} dailyUse={row['dailyUse']} / "
        f"T+1 {row['t1']} / T+5 {row['t5']} / T+20 {row['t20']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate unified rule dashboard.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    args = parser.parse_args()

    rows = load_long(args.date) + load_short(args.date)
    active = [r for r in rows if r["status"] == "active_rule"]
    watch = [r for r in rows if r["status"] == "watch_rule"]
    hypothesis = [r for r in rows if r["status"] == "hypothesis_only"]

    output = {
        "createdAt": datetime.now(JST).replace(microsecond=0).isoformat(),
        "mode": "rule-dashboard",
        "caution": "売買助言ではなく、ルール再現性を日次表示へ使うための整理。",
        "rows": rows,
    }
    Path(str(OUTPUT_JSON).format(date=args.date)).write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        f"# {args.date} Rule Dashboard",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {args.date}",
        "- mode: rule-dashboard",
        "- caution: 売買助言ではなく、ルール再現性を日次表示へ使うための整理。",
        "",
        "## Summary",
        f"- totalRules: {len(rows)}",
        f"- activeRule: {len(active)}",
        f"- watchRule: {len(watch)}",
        f"- hypothesisOnly: {len(hypothesis)}",
        "",
        "## Active Rules",
    ]
    for row in active[:20]:
        lines.append(row_line(row))
    lines.extend(["", "## Watch Rules"])
    for row in watch[:30]:
        lines.append(row_line(row))
    lines.extend(["", "## Hypothesis Only"])
    for row in hypothesis[:20]:
        lines.append(row_line(row))

    Path(str(OUTPUT_MD).format(date=args.date)).write_text("\n".join(lines) + "\n", encoding="utf-8")

    brief_lines = [
        f"# {args.date} Daily Rule Brief",
        "",
        "## 投資ルール表示用",
        "- daily本文では `active_rule` を優先表示し、`watch_rule` は重要な該当がある場合だけ補足する。",
        "- `hypothesis_only` は日次ランク補正に強く使わず、検証中として明示する。",
        "",
        "## Long Core",
    ]
    for row in [r for r in active if r["side"] == "long"][:8]:
        brief_lines.append(row_line(row))
    brief_lines.extend(["", "## Short Core / Caution"])
    for row in [r for r in rows if r["side"] == "short"][:8]:
        brief_lines.append(row_line(row))
    Path(str(BRIEF_MD).format(date=args.date)).write_text("\n".join(brief_lines) + "\n", encoding="utf-8")

    print(f"wrote {Path(str(OUTPUT_MD).format(date=args.date)).relative_to(ROOT)} rows={len(rows)} active={len(active)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
