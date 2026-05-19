#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
JST = timezone(timedelta(hours=9))
DEFAULT_DB = ROOT / "data" / "investment.db"
OUTPUT_MD = ROOT / "topics/investment-research/inbox/{date}-rule-dashboard.md"
OUTPUT_JSON = ROOT / "topics/investment-research/inbox/{date}-rule-dashboard.json"
BRIEF_MD = ROOT / "topics/investment-research/inbox/{date}-daily-rule-brief.md"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate a unified long/short rule dashboard (DB-first).")
    p.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--min-count", type=int, default=8)
    return p.parse_args()


def compact_counts(c: dict) -> str:
    win = int(c.get("win", 0) or 0)
    loss = int(c.get("loss", 0) or 0)
    flat = int(c.get("flat", 0) or 0)
    pending = int(c.get("pending", 0) or 0)
    judged = win + loss + flat
    wr = (win / judged * 100.0) if judged else 0.0
    return f"{win}/{loss}/{flat} pending={pending} wr={wr:.1f}%"


def status_for(bucket: str, appearances: int, side: str, min_count: int) -> str:
    if side == "long" and bucket == "strict_long_signal" and appearances >= max(20, min_count):
        return "active_rule"
    if side == "short" and bucket == "strict_short_signal" and appearances >= max(8, min_count):
        return "active_rule"
    if appearances < min_count:
        return "hypothesis_only"
    return "watch_rule"


def build_rows(conn: sqlite3.Connection, date_str: str, min_count: int) -> list[dict]:
    rows: list[dict] = []
    # Long side from rule_check_candidates payload.
    long_candidates = conn.execute(
        """
        SELECT payload_json,row_count
        FROM rule_check_candidates
        WHERE date=? AND min_count=?
        ORDER BY candidate_index
        """,
        (date_str, min_count),
    ).fetchall()
    for raw, row_count in long_candidates:
        try:
            item = json.loads(raw or "{}")
        except Exception:
            continue
        w = item.get("windows", {}) or {}
        t1 = w.get("t1", {})
        t5 = w.get("t5", {})
        t20 = w.get("t20", {})
        bucket = str(item.get("judgement", "watch_more"))
        appearances = int(row_count or item.get("rowCount", 0) or 0)
        rows.append(
            {
                "side": "long",
                "bucket": bucket,
                "rule": f"{item.get('ruleGroup','')}: {item.get('label','')}",
                "appearances": appearances,
                "period": "{0}..{1}".format(
                    ((item.get("occurrence", {}) or {}).get("firstSignalDate", "")),
                    ((item.get("occurrence", {}) or {}).get("lastSignalDate", "")),
                ),
                "t1": compact_counts(t1),
                "t5": compact_counts(t5),
                "t20": compact_counts(t20),
                "dailyUse": "long_watch",
                "status": status_for(bucket, appearances, "long", min_count),
            }
        )

    # Short side from short_conviction rows in DB (ingested into backtest_outcomes signal_type labels not guaranteed),
    # fallback: derive from opening_scenarios direction=short as operational proxy.
    short_rows = conn.execute(
        """
        SELECT ticker,scenario_tier,rule_hit_count,estimated_winrate_value
        FROM opening_scenarios
        WHERE scenario_date=? AND direction='short'
        """,
        (date_str,),
    ).fetchall()
    if short_rows:
        count = len(short_rows)
        win = sum(1 for _, _, _, wr in short_rows if isinstance(wr, (int, float)) and float(wr) >= 50.0)
        loss = sum(1 for _, _, _, wr in short_rows if isinstance(wr, (int, float)) and float(wr) < 50.0)
        flat = 0
        pending = count - win - loss
        rows.append(
            {
                "side": "short",
                "bucket": "strict_short_signal",
                "rule": "scenario short candidates (db proxy)",
                "appearances": count,
                "period": f"{date_str}..{date_str}",
                "t1": f"{win}/{loss}/{flat} pending={pending} wr={(win / max(1, (win+loss+flat)) * 100):.1f}%",
                "t5": "n/a",
                "t20": "n/a",
                "dailyUse": "short_core_watch",
                "status": status_for("strict_short_signal", count, "short", min_count),
            }
        )
    return rows


def row_line(row: dict) -> str:
    return (
        f"- {row['side']} / {row['bucket']}: `{row['rule']}` appearances={row['appearances']} "
        f"period={row['period']} status={row['status']} dailyUse={row['dailyUse']} / "
        f"T+1 {row['t1']} / T+5 {row['t5']} / T+20 {row['t20']}"
    )


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"db not found: {args.db}")
    conn = sqlite3.connect(args.db)
    try:
        rows = build_rows(conn, args.date, args.min_count)
        conn.execute("DELETE FROM rule_dashboard_rows WHERE date=?", (args.date,))
        for r in rows:
            conn.execute(
                """
                INSERT INTO rule_dashboard_rows(
                  date,side,bucket,rule,appearances,period,t1,t5,t20,daily_use,status,source_path,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                """,
                (
                    args.date,
                    r["side"],
                    r["bucket"],
                    r["rule"],
                    int(r["appearances"]),
                    r["period"],
                    r["t1"],
                    r["t5"],
                    r["t20"],
                    r["dailyUse"],
                    r["status"],
                    "db:rule_check_candidates/opening_scenarios",
                ),
            )
        conn.commit()
    finally:
        conn.close()

    active = [r for r in rows if r["status"] == "active_rule"]
    watch = [r for r in rows if r["status"] == "watch_rule"]
    hypothesis = [r for r in rows if r["status"] == "hypothesis_only"]
    output = {
        "createdAt": datetime.now(JST).replace(microsecond=0).isoformat(),
        "mode": "rule-dashboard",
        "rows": rows,
    }
    Path(str(OUTPUT_JSON).format(date=args.date)).write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"# {args.date} Rule Dashboard",
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
    Path(str(BRIEF_MD).format(date=args.date)).write_text("\n".join(lines[:40]) + "\n", encoding="utf-8")
    print(f"wrote {Path(str(OUTPUT_MD).format(date=args.date)).relative_to(ROOT)} rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
