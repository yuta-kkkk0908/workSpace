#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from investment.analysis.exit_horizon_utils import avg, collect_price_path_returns, win_rate
from utils.investment_db_path import resolve_investment_db
from utils.pipeline_events import write_pipeline_event

DEFAULT_DB = resolve_investment_db()
INBOX = ROOT / "topics" / "investment-research" / "inbox"
PROMPTS = ROOT / "tmp" / "prompts"
JST = timezone(timedelta(hours=9))


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Aggregate ExitAnalyzer report for collection/analysis/processing bottlenecks")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--window-days", type=int, default=30)
    p.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    return p.parse_args()


def _max_drawdown(returns_pct: list[float]) -> float:
    if not returns_pct:
        return 0.0
    equity = 1.0
    peak = 1.0
    mdd = 0.0
    for r in returns_pct:
        equity *= 1.0 + (r / 100.0)
        if equity > peak:
            peak = equity
        dd = (equity / peak) - 1.0
        if dd < mdd:
            mdd = dd
    return mdd * 100.0


def _age_days(end_date: str, entry_date: str) -> int:
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    start = datetime.strptime(entry_date, "%Y-%m-%d").date()
    return max(0, (end - start).days)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(JST)


def _minutes_since(value: str | None, *, now: datetime) -> float | None:
    dt = _parse_dt(value)
    if dt is None:
        return None
    return round((now - dt).total_seconds() / 60.0, 2)


def _count_by(rows: list[sqlite3.Row], key: str, limit: int = 6) -> list[dict[str, object]]:
    c = Counter()
    for r in rows:
        v = str(r[key] or "").strip()
        if not v:
            continue
        c[v] += 1
    return [{"value": k, "count": v} for k, v in c.most_common(limit)]


def _age_bucket(days: int) -> str:
    if days == 0:
        return "0d"
    if days == 1:
        return "1d"
    if days <= 3:
        return "2-3d"
    if days <= 5:
        return "4-5d"
    if days <= 7:
        return "6-7d"
    if days <= 14:
        return "8-14d"
    if days <= 21:
        return "15-21d"
    if days <= 30:
        return "22-30d"
    return "31d+"


def _group_by_label(rows: list[sqlite3.Row], label_fn) -> list[tuple[str, list[sqlite3.Row]]]:
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        label = str(label_fn(row) or "").strip() or "unknown"
        grouped.setdefault(label, []).append(row)
    return sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))


def _collect_trade_horizons(rows: list[sqlite3.Row]) -> dict[str, object]:
    t1 = [float(r["t1_return_pct"]) for r in rows if r["t1_return_pct"] is not None]
    t5 = [float(r["t5_return_pct"]) for r in rows if r["t5_return_pct"] is not None]
    t20 = [float(r["t20_return_pct"]) for r in rows if r["t20_return_pct"] is not None]
    t3 = collect_price_path_returns(rows, offset=3)
    t10 = collect_price_path_returns(rows, offset=10)
    return {
        "sampleTrades": len(rows),
        "t1": {"n": len(t1), "winRatePct": round(win_rate(t1), 3), "avgRetPct": round(avg(t1), 3)},
        "t3_ref": {"n": len(t3), "winRatePct": round(win_rate(t3), 3), "avgRetPct": round(avg(t3), 3)},
        "t5": {"n": len(t5), "winRatePct": round(win_rate(t5), 3), "avgRetPct": round(avg(t5), 3)},
        "t10_ref": {"n": len(t10), "winRatePct": round(win_rate(t10), 3), "avgRetPct": round(avg(t10), 3)},
        "t20": {"n": len(t20), "winRatePct": round(win_rate(t20), 3), "avgRetPct": round(avg(t20), 3)},
        "t5_mdd_pct": round(_max_drawdown(t5), 3),
        "t10_ref_mdd_pct": round(_max_drawdown(t10), 3),
    }


def _summarize_trade_groups(
    rows: list[sqlite3.Row],
    label_fn,
    *,
    limit: int = 6,
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for label, group_rows in _group_by_label(rows, label_fn)[:limit]:
        summary = _collect_trade_horizons(group_rows)
        items.append(
            {
                "value": label,
                "count": len(group_rows),
                "analysis": summary,
            }
        )
    return items


def _label_mode_age(row: sqlite3.Row, *, end: str) -> str:
    return f"{str(row['mode'] or '').strip() or 'unknown'} | {_age_bucket(_age_days(end, str(row['entry_date'])))}"


def _count_by_label(rows: list[sqlite3.Row], label_fn, limit: int = 6) -> list[dict[str, object]]:
    c = Counter()
    for row in rows:
        label = str(label_fn(row) or "").strip()
        if not label:
            continue
        c[label] += 1
    return [{"value": k, "count": v} for k, v in c.most_common(limit)]


def _format_count_pairs(items: list[dict[str, object]]) -> str:
    if not items:
        return "none"
    return ", ".join(f"{x['value']}={x['count']}" for x in items)


def _summarize_nested_trade_groups(
    rows: list[sqlite3.Row],
    outer_label_fn,
    inner_label_fn,
    *,
    outer_limit: int = 5,
    inner_limit: int = 3,
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for outer_label, outer_rows in _group_by_label(rows, outer_label_fn)[:outer_limit]:
        nested_counts = _count_by_label(outer_rows, inner_label_fn, limit=inner_limit)
        summary = _collect_trade_horizons(outer_rows)
        items.append(
            {
                "value": outer_label,
                "count": len(outer_rows),
                "analysis": summary,
                "innerMix": nested_counts,
            }
        )
    return items


def _pick_breakdown_item(items: list[dict[str, object]]) -> dict[str, object] | None:
    if not items:
        return None
    return max(
        items,
        key=lambda item: (
            int(((item.get("analysis") or {}).get("sampleTrades")) or 0),
            int(item.get("count") or 0),
            str(item.get("value") or ""),
        ),
    )


def _status_bucket(status: str | None) -> str:
    s = str(status or "").strip().lower()
    if s in {"open_pending_outcome", "open_partial"}:
        return s
    if s.startswith("closed_"):
        return "closed"
    if s == "cancelled":
        return "cancelled"
    if not s:
        return "unknown"
    return s


def build_payload(args: argparse.Namespace) -> dict:
    d0 = datetime.strptime(args.date, "%Y-%m-%d").date()
    start = (d0 - timedelta(days=max(1, int(args.window_days)) - 1)).isoformat()
    end = args.date
    now = datetime.now(JST)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        trades = conn.execute(
            """
            SELECT trade_id, ticker, mode, entry_date, side, status, exit_reason, t1_return_pct, t5_return_pct, t20_return_pct, price_path_json
            FROM paper_trades
            WHERE entry_date<=?
            ORDER BY entry_date, ticker, trade_id
            """,
            (end,),
        ).fetchall()
        recent_trades = [r for r in trades if r["entry_date"] >= start]

        scenario_rows = conn.execute(
            """
            SELECT message_id, scenario_date, scenario_tier, watch_ladder
            FROM scenario_messages
            WHERE scenario_date BETWEEN ? AND ?
            """,
            (start, end),
        ).fetchall()
        reply_rows = conn.execute(
            """
            SELECT reply_message_id, parent_message_id, command, processed_at
            FROM scenario_reply_events
            WHERE substr(processed_at, 1, 10) BETWEEN ? AND ?
            """,
            (start, end),
        ).fetchall()
        latest_exit_reply = conn.execute(
            """
            SELECT processed_at
            FROM scenario_reply_events
            WHERE lower(command) IN ('exit', 'cancel')
            ORDER BY processed_at DESC
            LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()

    open_rows = [r for r in trades if _status_bucket(r["status"]) in {"open_pending_outcome", "open_partial"}]
    open_ages = [_age_days(end, str(r["entry_date"])) for r in open_rows]
    pending_exit_rows = [age for age in open_ages if age >= 1]
    stuck_rows = [age for age in open_ages if age >= 2]
    # Approximate backlog by subtracting auto_followup replies already recorded for each scenario.
    auto_followups = {str(r["parent_message_id"] or "") for r in reply_rows if str(r["command"] or "").lower() == "auto_followup"}
    followup_backlog = sum(1 for r in scenario_rows if str(r["message_id"] or "") not in auto_followups and str(r["scenario_tier"] or "") in {"trade", "watch"})

    exits = [r for r in trades if str(r["exit_reason"] or "").strip()]
    exit_reason_mix = _count_by(exits, "exit_reason", limit=8)
    mode_mix = _count_by(trades, "mode", limit=8)
    status_mix = _count_by(trades, "status", limit=8)

    analysis_rows = recent_trades if recent_trades else trades
    analysis = _collect_trade_horizons(analysis_rows)
    ticker_breakdown = _summarize_trade_groups(analysis_rows, lambda r: r["ticker"], limit=8)
    side_breakdown = _summarize_trade_groups(analysis_rows, lambda r: r["side"], limit=4)
    mode_breakdown = _summarize_trade_groups(analysis_rows, lambda r: r["mode"], limit=6)
    mode_age_breakdown = _summarize_trade_groups(analysis_rows, lambda r: _label_mode_age(r, end=end), limit=8)
    mode_age_exit_reason_breakdown = _summarize_nested_trade_groups(
        [r for r in analysis_rows if str(r["exit_reason"] or "").strip()],
        lambda r: _label_mode_age(r, end=end),
        lambda r: r["exit_reason"],
        outer_limit=5,
        inner_limit=3,
    )
    mode_age_status_breakdown = _summarize_nested_trade_groups(
        analysis_rows,
        lambda r: _label_mode_age(r, end=end),
        lambda r: _status_bucket(r["status"]),
        outer_limit=5,
        inner_limit=3,
    )
    age_status_breakdown = _summarize_nested_trade_groups(
        analysis_rows,
        lambda r: _age_bucket(_age_days(end, str(r["entry_date"]))),
        lambda r: _status_bucket(r["status"]),
        outer_limit=8,
        inner_limit=4,
    )
    exit_reason_breakdown = _summarize_trade_groups(
        [r for r in analysis_rows if str(r["exit_reason"] or "").strip()],
        lambda r: r["exit_reason"],
        limit=6,
    )
    age_breakdown = _summarize_trade_groups(analysis_rows, lambda r: _age_bucket(_age_days(end, str(r["entry_date"]))), limit=6)
    stuck_breakdown = []
    if open_rows:
        open_grouped = {
            "stuck": [],
            "not_stuck": [],
        }
        for row in open_rows:
            age = _age_days(end, str(row["entry_date"]))
            key = "stuck" if age >= 2 else "not_stuck"
            open_grouped[key].append(row)
        for label in ["stuck", "not_stuck"]:
            group_rows = open_grouped[label]
            if not group_rows:
                continue
            ages = [_age_days(end, str(r["entry_date"])) for r in group_rows]
            stuck_breakdown.append(
                {
                    "value": label,
                    "count": len(group_rows),
                    "pendingExitCount": sum(1 for age in ages if age >= 1),
                    "ageDaysAvg": round(avg([float(age) for age in ages]), 2) if ages else 0.0,
                    "ageDaysMax": max(ages) if ages else 0,
                }
            )
    processing_reply_count = len(reply_rows)
    latest_reply = max((_parse_dt(str(r["processed_at"] or "")) for r in reply_rows), default=None)
    latest_reply_minutes = round((now - latest_reply).total_seconds() / 60.0, 2) if latest_reply else None
    exit_sync_lag_minutes = _minutes_since(str(latest_exit_reply["processed_at"]) if latest_exit_reply else None, now=now)

    collection = {
        "openTradeCount": len(open_rows),
        "openTradeAgeDaysAvg": round(avg([float(x) for x in open_ages]), 2) if open_ages else 0.0,
        "openTradeAgeDaysMax": max(open_ages) if open_ages else 0,
        "pendingExitCount": len(pending_exit_rows),
        "stuckTradeCount": len(stuck_rows),
        "followupBacklogCount": followup_backlog,
        "scenarioCount": len(scenario_rows),
        "modeMix": mode_mix,
        "statusMix": status_mix,
    }

    processing = {
        "replyEventCount": processing_reply_count,
        "latestReplyAgeMinutes": latest_reply_minutes,
        "latestExitReplyAgeMinutes": exit_sync_lag_minutes,
        "recentScenarioCount": len(scenario_rows),
        "recentReplyCount": len(reply_rows),
    }

    level = "OK"
    reasons: list[str] = []
    if collection["stuckTradeCount"] > 0 or (exit_sync_lag_minutes is not None and exit_sync_lag_minutes >= 180):
        level = "ALERT"
        reasons.append("stuck_or_sync_lag")
    elif collection["pendingExitCount"] > 0 or collection["followupBacklogCount"] > 0 or (
        exit_sync_lag_minutes is not None and exit_sync_lag_minutes >= 60
    ):
        level = "WARN"
        reasons.append("pending_or_backlog")

    return {
        "date": args.date,
        "window": {"start": start, "end": end, "days": int(args.window_days)},
        "level": level,
        "reasons": reasons,
        "collection": collection,
        "analysis": analysis,
        "processing": processing,
        "analysis_window": {"recentTradeCount": len(recent_trades), "allTradeCount": len(trades)},
        "exitReasonMix": exit_reason_mix,
        "tickerBreakdown": ticker_breakdown,
        "sideBreakdown": side_breakdown,
        "modeBreakdown": mode_breakdown,
        "modeAgeBreakdown": mode_age_breakdown,
        "modeAgeExitReasonBreakdown": mode_age_exit_reason_breakdown,
        "modeAgeStatusBreakdown": mode_age_status_breakdown,
        "ageStatusBreakdown": age_status_breakdown,
        "exitReasonBreakdown": exit_reason_breakdown,
        "ageBreakdown": age_breakdown,
        "stuckBreakdown": stuck_breakdown,
    }


def render_md(payload: dict) -> str:
    w = payload["window"]
    c = payload["collection"]
    a = payload["analysis"]
    p = payload["processing"]
    lines = [
        f"# {payload['date']} ExitAnalyzer",
        "",
        f"- window: {w['start']} .. {w['end']} ({w['days']}d)",
        f"- level: {payload['level']}",
        f"- reason: {', '.join(payload.get('reasons') or ['none'])}",
        "",
        "## 収集",
        f"- open trades: {c['openTradeCount']}",
        f"- pending exits: {c['pendingExitCount']}",
        f"- stuck trades: {c['stuckTradeCount']}",
        f"- follow-up backlog: {c['followupBacklogCount']}",
        f"- open age avg/max: {c['openTradeAgeDaysAvg']:.2f} / {c['openTradeAgeDaysMax']}",
        "",
        "## Ticker Breakdown",
    ]
    ticker_breakdown = payload.get("tickerBreakdown") or []
    if ticker_breakdown:
        for item in ticker_breakdown:
            a0 = item["analysis"]
            lines.append(
                f"- {item['value']}: n={item['count']} "
                f"T+5 wr={a0['t5']['winRatePct']:.1f}% avg={a0['t5']['avgRetPct']:.2f}%"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Side Breakdown",
        ]
    )
    side_breakdown = payload.get("sideBreakdown") or []
    if side_breakdown:
        for item in side_breakdown:
            a0 = item["analysis"]
            lines.append(
                f"- {item['value']}: n={item['count']} "
                f"T+5 wr={a0['t5']['winRatePct']:.1f}% avg={a0['t5']['avgRetPct']:.2f}%"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## 分析",
        f"- T+1: n={a['t1']['n']} wr={a['t1']['winRatePct']:.1f}% avg={a['t1']['avgRetPct']:.2f}%",
        f"- T+3(ref): n={a['t3_ref']['n']} wr={a['t3_ref']['winRatePct']:.1f}% avg={a['t3_ref']['avgRetPct']:.2f}%",
        f"- T+5: n={a['t5']['n']} wr={a['t5']['winRatePct']:.1f}% avg={a['t5']['avgRetPct']:.2f}%",
        f"- T+10(ref): n={a['t10_ref']['n']} wr={a['t10_ref']['winRatePct']:.1f}% avg={a['t10_ref']['avgRetPct']:.2f}%",
        f"- T+20: n={a['t20']['n']} wr={a['t20']['winRatePct']:.1f}% avg={a['t20']['avgRetPct']:.2f}%",
        f"- T+5 MDD: {a['t5_mdd_pct']:.2f}%",
        f"- T+10(ref) MDD: {a['t10_ref_mdd_pct']:.2f}%",
        "",
        "## 処理",
        f"- reply events: {p['replyEventCount']}",
        f"- latest reply age: {p['latestReplyAgeMinutes'] if p['latestReplyAgeMinutes'] is not None else 'n/a'} min",
        f"- latest exit reply age: {p['latestExitReplyAgeMinutes'] if p['latestExitReplyAgeMinutes'] is not None else 'n/a'} min",
        f"- recent scenario/reply: {p['recentScenarioCount']} / {p['recentReplyCount']}",
        "",
        "## Exit Reason Mix",
        ]
    )
    mix = payload.get("exitReasonMix") or []
    if mix:
        for item in mix:
            lines.append(f"- {item['value']}: {item['count']}")
    else:
        lines.append("- none")
    lines.extend(
        [
        "",
        "## Mode Breakdown",
    ]
    )
    mode_breakdown = payload.get("modeBreakdown") or []
    if mode_breakdown:
        for item in mode_breakdown:
            a = item["analysis"]
            lines.append(
                f"- {item['value']}: n={item['count']} "
                f"T+5 wr={a['t5']['winRatePct']:.1f}% avg={a['t5']['avgRetPct']:.2f}%"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Mode x Age Breakdown",
        ]
    )
    mode_age_breakdown = payload.get("modeAgeBreakdown") or []
    if mode_age_breakdown:
        for item in mode_age_breakdown:
            a = item["analysis"]
            lines.append(
                f"- {item['value']}: n={item['count']} "
                f"T+5 wr={a['t5']['winRatePct']:.1f}% avg={a['t5']['avgRetPct']:.2f}%"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Mode x Age x Exit Reason Breakdown (closed only)",
        ]
    )
    mode_age_exit_reason_breakdown = payload.get("modeAgeExitReasonBreakdown") or []
    if mode_age_exit_reason_breakdown:
        for item in mode_age_exit_reason_breakdown:
            a = item["analysis"]
            inner = item.get("innerMix") or []
            inner_text = ", ".join(f"{x['value']}={x['count']}" for x in inner) if inner else "none"
            lines.append(
                f"- {item['value']}: n={item['count']} "
                f"T+5 wr={a['t5']['winRatePct']:.1f}% avg={a['t5']['avgRetPct']:.2f}% "
                f"reason={inner_text}"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Mode x Age x Status Breakdown",
        ]
    )
    mode_age_status_breakdown = payload.get("modeAgeStatusBreakdown") or []
    if mode_age_status_breakdown:
        for item in mode_age_status_breakdown:
            a = item["analysis"]
            inner = item.get("innerMix") or []
            inner_text = _format_count_pairs(inner)
            lines.append(
                f"- {item['value']}: n={item['count']} "
                f"T+5 wr={a['t5']['winRatePct']:.1f}% avg={a['t5']['avgRetPct']:.2f}% "
                f"status={inner_text}"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Exit Reason Breakdown",
        ]
    )
    exit_reason_breakdown = payload.get("exitReasonBreakdown") or []
    if exit_reason_breakdown:
        for item in exit_reason_breakdown:
            a = item["analysis"]
            lines.append(
                f"- {item['value']}: n={item['count']} "
                f"T+5 wr={a['t5']['winRatePct']:.1f}% avg={a['t5']['avgRetPct']:.2f}%"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Age Breakdown",
        ]
    )
    age_breakdown = payload.get("ageBreakdown") or []
    if age_breakdown:
        for item in age_breakdown:
            a = item["analysis"]
            lines.append(
                f"- {item['value']}: n={item['count']} "
                f"T+5 wr={a['t5']['winRatePct']:.1f}% avg={a['t5']['avgRetPct']:.2f}%"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Age x Status Breakdown",
        ]
    )
    age_status_breakdown = payload.get("ageStatusBreakdown") or []
    if age_status_breakdown:
        for item in age_status_breakdown:
            a = item["analysis"]
            inner_text = _format_count_pairs(item.get("innerMix") or [])
            lines.append(
                f"- {item['value']}: n={item['count']} "
                f"T+5 wr={a['t5']['winRatePct']:.1f}% avg={a['t5']['avgRetPct']:.2f}% "
                f"status={inner_text}"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Stuck Breakdown",
        ]
    )
    stuck_breakdown = payload.get("stuckBreakdown") or []
    if stuck_breakdown:
        for item in stuck_breakdown:
            lines.append(
                f"- {item['value']}: n={item['count']} "
                f"pending={item['pendingExitCount']} age avg/max={item['ageDaysAvg']:.2f}/{item['ageDaysMax']}"
            )
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def render_discord(payload: dict) -> str:
    c = payload["collection"]
    a = payload["analysis"]
    p = payload["processing"]
    ticker_breakdown = payload.get("tickerBreakdown") or []
    side_breakdown = payload.get("sideBreakdown") or []
    mode_breakdown = payload.get("modeBreakdown") or []
    mode_age_breakdown = payload.get("modeAgeBreakdown") or []
    mode_age_exit_reason_breakdown = payload.get("modeAgeExitReasonBreakdown") or []
    mode_age_status_breakdown = payload.get("modeAgeStatusBreakdown") or []
    age_status_breakdown = payload.get("ageStatusBreakdown") or []
    exit_reason_breakdown = payload.get("exitReasonBreakdown") or []
    age_breakdown = payload.get("ageBreakdown") or []
    stuck_breakdown = payload.get("stuckBreakdown") or []
    ticker_focus = _pick_breakdown_item(ticker_breakdown)
    side_focus = _pick_breakdown_item(side_breakdown)
    mode_focus = _pick_breakdown_item(mode_breakdown)
    mode_age_focus = _pick_breakdown_item(mode_age_breakdown)
    mode_age_exit_reason_focus = _pick_breakdown_item(mode_age_exit_reason_breakdown)
    mode_age_status_focus = _pick_breakdown_item(mode_age_status_breakdown)
    age_status_focus = _pick_breakdown_item(age_status_breakdown)
    exit_reason_focus = _pick_breakdown_item(exit_reason_breakdown)
    age_focus = _pick_breakdown_item(age_breakdown)
    stuck_focus = _pick_breakdown_item(stuck_breakdown)
    lines = [
        f"ExitAnalyzer {payload['date']}",
        f"- level: {payload['level']} ({', '.join(payload.get('reasons') or ['none'])})",
        (
            f"- 収集: open={c['openTradeCount']} pending={c['pendingExitCount']} "
            f"stuck={c['stuckTradeCount']} backlog={c['followupBacklogCount']}"
        ),
        (
            f"- 分析: T+5 wr={a['t5']['winRatePct']:.1f}% avg={a['t5']['avgRetPct']:.2f}% "
            f"/ T+3(ref) wr={a['t3_ref']['winRatePct']:.1f}% / T+10(ref) wr={a['t10_ref']['winRatePct']:.1f}%"
        ),
        (
            f"- 処理: exit lag={p['latestExitReplyAgeMinutes'] if p['latestExitReplyAgeMinutes'] is not None else 'n/a'} min "
            f"/ replies={p['replyEventCount']}"
        ),
        (
            f"- ticker: {ticker_focus['value']} n={ticker_focus['count']} "
            f"T+5 wr={ticker_focus['analysis']['t5']['winRatePct']:.1f}%"
            if ticker_focus
            else "- ticker: none"
        ),
        (
            f"- side: {side_focus['value']} n={side_focus['count']} "
            f"T+5 wr={side_focus['analysis']['t5']['winRatePct']:.1f}%"
            if side_focus
            else "- side: none"
        ),
        (
            f"- mode: {mode_focus['value']} n={mode_focus['count']} "
            f"T+5 wr={mode_focus['analysis']['t5']['winRatePct']:.1f}%"
            if mode_focus
            else "- mode: none"
        ),
        (
            f"- mode_age: {mode_age_focus['value']} n={mode_age_focus['count']} "
            f"T+5 wr={mode_age_focus['analysis']['t5']['winRatePct']:.1f}%"
            if mode_age_focus
            else "- mode_age: none"
        ),
        (
            f"- mode_age_reason: {mode_age_exit_reason_focus['value']} n={mode_age_exit_reason_focus['count']} "
            f"reason={_format_count_pairs(mode_age_exit_reason_focus.get('innerMix') or [])}"
            if mode_age_exit_reason_focus
            else "- mode_age_reason: none"
        ),
        (
            f"- mode_age_status: {mode_age_status_focus['value']} n={mode_age_status_focus['count']} "
            f"status={_format_count_pairs(mode_age_status_focus.get('innerMix') or [])}"
            if mode_age_status_focus
            else "- mode_age_status: none"
        ),
        (
            f"- age_status: {age_status_focus['value']} n={age_status_focus['count']} "
            f"status={_format_count_pairs(age_status_focus.get('innerMix') or [])}"
            if age_status_focus
            else "- age_status: none"
        ),
        (
            f"- exit_reason: {exit_reason_focus['value']} n={exit_reason_focus['count']} "
            f"T+5 wr={exit_reason_focus['analysis']['t5']['winRatePct']:.1f}%"
            if exit_reason_focus
            else "- exit_reason: none"
        ),
        (
            f"- age: {age_focus['value']} n={age_focus['count']} "
            f"T+5 wr={age_focus['analysis']['t5']['winRatePct']:.1f}%"
            if age_focus
            else "- age: none"
        ),
        (
            f"- stuck: {stuck_focus['value']} n={stuck_focus['count']} "
            f"pending={stuck_focus['pendingExitCount']}"
            if stuck_focus
            else "- stuck: none"
        ),
        "- caution: 出口ボトルネックの観測メモ。売買助言ではありません。",
    ]
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    payload = build_payload(args)
    if args.write_files:
        out_json = INBOX / f"{args.date}-exit-analyzer.json"
        out_md = INBOX / f"{args.date}-exit-analyzer.md"
        out_txt = PROMPTS / "exit-analyzer-discord-message.txt"
        INBOX.mkdir(parents=True, exist_ok=True)
        PROMPTS.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        out_md.write_text(render_md(payload), encoding="utf-8")
        discord = render_discord(payload)
        out_txt.write_text(discord, encoding="utf-8")
        print(f"wrote {_display_path(out_md)}")
        print(f"wrote {_display_path(out_json)}")
        print(f"wrote {_display_path(out_txt)}")
    try:
        write_pipeline_event(
            pipeline="investment_analysis",
            slot="inv-evening",
            stage="report_exit_analyzer",
            status="ok",
            event_date=args.date,
            return_code=0,
            payload=payload,
            source_path="scripts/investment/analysis/report_exit_analyzer.py",
        )
    except Exception as exc:  # pragma: no cover - telemetry should not block report output
        print(f"warn: failed to record pipeline event: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
