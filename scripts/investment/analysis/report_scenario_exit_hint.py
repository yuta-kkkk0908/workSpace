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
PROMPTS = ROOT / "prompts"
JST = timezone(timedelta(hours=9))


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Lightweight exit hint for a single scenario")
    p.add_argument("--date", required=True, help="scenario date YYYY-MM-DD")
    p.add_argument("--index", type=int, required=True, help="scenario index on that date")
    p.add_argument("--message-id", default="", help="optional scenario message_id override")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    return p.parse_args()


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


def _count_by(rows: list[sqlite3.Row], key: str, limit: int = 8) -> list[dict[str, object]]:
    c = Counter()
    for r in rows:
        v = str(r[key] or "").strip()
        if not v:
            continue
        c[v] += 1
    return [{"value": k, "count": v} for k, v in c.most_common(limit)]


def _trade_side(direction: str | None) -> str:
    return "short" if str(direction or "").strip().lower() == "short" else "long"


def _trade_horizon_summary(rows: list[sqlite3.Row]) -> dict[str, object]:
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
    }


def _pick_primary_trade(trades: list[sqlite3.Row], signal_id: str) -> sqlite3.Row | None:
    if not trades:
        return None
    if signal_id:
        matched = [r for r in trades if str(r["signal_id"] or "").strip() == signal_id]
        if matched:
            trades = matched
    return max(
        trades,
        key=lambda r: (
            str(r["updated_at"] or ""),
            str(r["trade_id"] or ""),
        ),
    )


def _build_exit_hint(primary_trade: sqlite3.Row | None, replies: list[sqlite3.Row]) -> str:
    if primary_trade is None:
        return "取引がまだ紐づいていないので、まず entry / exit の反映待ちです。"

    t1 = primary_trade["t1_return_pct"]
    t5 = primary_trade["t5_return_pct"]
    t20 = primary_trade["t20_return_pct"]
    status = _status_bucket(primary_trade["status"])
    direction = str(primary_trade["side"] or "").strip().lower() or "long"
    age_days = max(0, (datetime.now(JST).date() - datetime.strptime(str(primary_trade["entry_date"]), "%Y-%m-%d").date()).days)
    exit_replies = sum(1 for r in replies if str(r["command"] or "").lower() in {"exit", "cancel"})
    open_flag = status in {"open_pending_outcome", "open_partial"}

    if t1 is not None and t5 is not None and t20 is not None:
        if float(t1) >= float(t5) + 8.0 and float(t1) >= float(t20) + 8.0:
            core = "T+1優位なので、早めの利確 or 縮小を先に考える目安です。"
        elif float(t20) >= float(t5) + 8.0:
            core = "T+20優位なので、強材料なら少し長めに持つ余地があります。"
        elif float(t5) >= float(t1) and float(t5) >= float(t20):
            core = "T+5中心なので、まずは中期保有を基準に見るのが無難です。"
        else:
            core = "T+1/T+5/T+20の差が小さいので、現行の保有目安をそのまま使うのが無難です。"
    elif t5 is not None:
        core = "T+5の値が取れているので、まずはそこを基準に exit を考えるのが無難です。"
    else:
        core = "まだ十分な horizon データがないので、entry 時の想定保有期間を基準にするのが無難です。"

    t3_hint = ""
    primary_dict = dict(primary_trade) if primary_trade is not None else None
    if primary_dict and primary_dict.get("price_path_json"):
        t3_vals = collect_price_path_returns([primary_dict], offset=3)
        if t3_vals:
            t3_val = t3_vals[0]
            if t3_val >= 0:
                t3_hint = f" T+3は +{t3_val:.2f}% で、早めの判断はまだ有利です。"
            else:
                t3_hint = f" T+3は {t3_val:.2f}% で、短期の伸び切り注意です。"

    parts = [f"{direction.upper()} / {status}"]
    parts.append(core)
    if t3_hint:
        parts.append(t3_hint.strip())
    if open_flag and age_days >= 2:
        parts.append("未 exit が 2 日超なので、進捗確認を先に入れる目安です。")
    elif open_flag and age_days >= 1:
        parts.append("未 exit が 1 日超なので、返信同期の遅れがないか軽く見る目安です。")
    if exit_replies > 0:
        parts.append(f"exit/cancel 返信は {exit_replies} 件あります。")
    return " ".join(parts)


def build_payload(args: argparse.Namespace) -> dict:
    now = datetime.now(JST)
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        scenario_row = None
        if args.message_id:
            scenario_row = conn.execute(
                """
                SELECT scenario_date, scenario_index, channel_id, thread_id, anchor_message_id, message_id,
                       ticker, company, direction, scenario_tier, watch_ladder, signal_id, source_path, posted_at
                FROM scenario_messages
                WHERE message_id=?
                LIMIT 1
                """,
                (args.message_id,),
            ).fetchone()
        if scenario_row is None:
            scenario_row = conn.execute(
                """
                SELECT scenario_date, scenario_index, channel_id, thread_id, anchor_message_id, message_id,
                       ticker, company, direction, scenario_tier, watch_ladder, signal_id, source_path, posted_at
                FROM scenario_messages
                WHERE scenario_date=? AND scenario_index=?
                ORDER BY posted_at DESC
                LIMIT 1
                """,
                (args.date, int(args.index)),
            ).fetchone()
        if scenario_row is None:
            raise SystemExit(f"scenario not found: date={args.date} index={args.index}")

        scenario_message_id = str(scenario_row["message_id"] or "")
        replies = conn.execute(
            """
            SELECT reply_message_id, parent_message_id, command, raw_content, parsed_json, processed_at
            FROM scenario_reply_events
            WHERE parent_message_id=?
            ORDER BY processed_at ASC, reply_message_id ASC
            """,
            (scenario_message_id,),
        ).fetchall()

        direction = str(scenario_row["direction"] or "").strip().lower()
        side = _trade_side(direction)
        signal_id = str(scenario_row["signal_id"] or "").strip()
        linked_trades = conn.execute(
            """
            SELECT trade_id, mode, entry_date, ticker, company, side, lots, entry_style, planned_entry_price,
                   exit_price, exit_reason, status, signal_id, source_path, price_path_json,
                   t1_return_pct, t5_return_pct, t20_return_pct, updated_at
            FROM paper_trades
            WHERE (COALESCE(signal_id,'')<>'' AND signal_id=?)
               OR (entry_date=? AND ticker=? AND side=?)
            ORDER BY CASE WHEN COALESCE(signal_id,'')=? THEN 0 ELSE 1 END, updated_at DESC
            """,
            (signal_id, str(scenario_row["scenario_date"]), str(scenario_row["ticker"]), side, signal_id),
        ).fetchall()
    finally:
        conn.close()

    reply_counts = _count_by(replies, "command", limit=8)
    latest_reply_minutes = _minutes_since(str(replies[-1]["processed_at"]) if replies else None, now=now)
    latest_exit_reply = next((r for r in reversed(replies) if str(r["command"] or "").lower() in {"exit", "cancel"}), None)
    latest_exit_reply_minutes = _minutes_since(str(latest_exit_reply["processed_at"]) if latest_exit_reply else None, now=now)
    primary_trade = _pick_primary_trade(linked_trades, signal_id)
    primary_summary = _trade_horizon_summary([primary_trade] if primary_trade is not None else [])
    linked_status_mix = _count_by(linked_trades, "status", limit=8)
    linked_mode_mix = _count_by(linked_trades, "mode", limit=8)
    linked_exit_reason_mix = _count_by([r for r in linked_trades if str(r["exit_reason"] or "").strip()], "exit_reason", limit=8)
    linked_open_count = sum(1 for r in linked_trades if _status_bucket(r["status"]) in {"open_pending_outcome", "open_partial"})
    linked_closed_count = sum(1 for r in linked_trades if _status_bucket(r["status"]) == "closed")
    hint = _build_exit_hint(primary_trade, replies)

    scenario = {
        "date": str(scenario_row["scenario_date"]),
        "index": int(scenario_row["scenario_index"] or 0),
        "messageId": str(scenario_row["message_id"] or ""),
        "channelId": str(scenario_row["channel_id"] or ""),
        "threadId": str(scenario_row["thread_id"] or ""),
        "anchorMessageId": str(scenario_row["anchor_message_id"] or ""),
        "ticker": str(scenario_row["ticker"] or ""),
        "company": str(scenario_row["company"] or ""),
        "direction": str(scenario_row["direction"] or ""),
        "scenarioTier": str(scenario_row["scenario_tier"] or "trade"),
        "watchLadder": str(scenario_row["watch_ladder"] or ""),
        "signalId": str(scenario_row["signal_id"] or ""),
        "postedAt": str(scenario_row["posted_at"] or ""),
        "sourcePath": str(scenario_row["source_path"] or ""),
    }

    trade = {
        "linkedTradeCount": len(linked_trades),
        "openTradeCount": linked_open_count,
        "closedTradeCount": linked_closed_count,
        "statusMix": linked_status_mix,
        "modeMix": linked_mode_mix,
        "exitReasonMix": linked_exit_reason_mix,
        "primaryTrade": dict(primary_trade) if primary_trade is not None else None,
        "primarySummary": primary_summary,
    }
    reply_summary = {
        "replyCount": len(replies),
        "replyCommandMix": reply_counts,
        "latestReplyAgeMinutes": latest_reply_minutes,
        "latestExitReplyAgeMinutes": latest_exit_reply_minutes,
        "exitReplyCount": sum(1 for r in replies if str(r["command"] or "").lower() in {"exit", "cancel"}),
        "entryReplyCount": sum(1 for r in replies if str(r["command"] or "").lower() == "entry"),
    }
    return {
        "date": args.date,
        "scenario": scenario,
        "trade": trade,
        "replies": reply_summary,
        "hint": {
            "text": hint,
        },
    }


def render_md(payload: dict) -> str:
    s = payload["scenario"]
    t = payload["trade"]
    r = payload["replies"]
    p = t.get("primaryTrade") or {}
    lines = [
        f"# {s['date']} Scenario Exit Hint",
        "",
        f"- scenario: #{s['index']} {s['ticker']} {s['direction']} / {s['scenarioTier']}",
        f"- thread: {s['threadId'] or 'n/a'}",
        f"- signal_id: {s['signalId'] or 'n/a'}",
        "",
        "## 目安",
        f"- {payload['hint']['text']}",
        "",
        "## 返信",
        f"- replies: {r['replyCount']}",
        f"- entry/exit/cancel: {r['entryReplyCount']} / {r['exitReplyCount']}",
        f"- latest reply age: {r['latestReplyAgeMinutes'] if r['latestReplyAgeMinutes'] is not None else 'n/a'} min",
        f"- latest exit reply age: {r['latestExitReplyAgeMinutes'] if r['latestExitReplyAgeMinutes'] is not None else 'n/a'} min",
        "",
        "## Linked Trade",
        f"- linked trades: {t['linkedTradeCount']} (open={t['openTradeCount']}, closed={t['closedTradeCount']})",
        f"- mode mix: {', '.join(f'{x['value']}={x['count']}' for x in (t['modeMix'] or [])) or 'none'}",
        f"- status mix: {', '.join(f'{x['value']}={x['count']}' for x in (t['statusMix'] or [])) or 'none'}",
    ]
    if p:
        lines.extend(
            [
                f"- primary trade: {p.get('trade_id', '')} / {p.get('mode', '')} / {p.get('status', '')}",
                (
                    f"- T+1/T+3/T+5/T+20: "
                    f"{payload['trade']['primarySummary']['t1']['winRatePct']:.1f}% / "
                    f"{payload['trade']['primarySummary']['t3_ref']['winRatePct']:.1f}% / "
                    f"{payload['trade']['primarySummary']['t5']['winRatePct']:.1f}% / "
                    f"{payload['trade']['primarySummary']['t20']['winRatePct']:.1f}%"
                ),
            ]
        )
        if p.get("exit_reason"):
            lines.append(f"- exit_reason: {p['exit_reason']}")
    else:
        lines.append("- primary trade: none")
    return "\n".join(lines) + "\n"


def render_discord(payload: dict) -> str:
    s = payload["scenario"]
    t = payload["trade"]
    r = payload["replies"]
    primary = t.get("primarySummary") or {}
    lines = [
        f"Scenario Exit Hint {s['date']} #{s['index']}",
        f"- {s['ticker']} {s['direction']} / {s['scenarioTier']} / {s['watchLadder'] or 'no-ladder'}",
        f"- hint: {payload['hint']['text']}",
        (
            f"- trade: open={t['openTradeCount']} closed={t['closedTradeCount']} "
            f"/ T+3 wr={primary.get('t3_ref', {}).get('winRatePct', 0.0):.1f}% "
            f"/ T+5 wr={primary.get('t5', {}).get('winRatePct', 0.0):.1f}%"
        ),
        (
            f"- replies: total={r['replyCount']} exit={r['exitReplyCount']} "
            f"/ latest_exit_age={r['latestExitReplyAgeMinutes'] if r['latestExitReplyAgeMinutes'] is not None else 'n/a'}m"
        ),
    ]
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    payload = build_payload(args)
    if args.write_files:
        out_json = INBOX / f"{args.date}-scenario-{int(args.index):02d}-exit-hint.json"
        out_md = INBOX / f"{args.date}-scenario-{int(args.index):02d}-exit-hint.md"
        out_txt = PROMPTS / f"scenario-{int(args.index):02d}-exit-hint-discord-message.txt"
        out_txt_md = PROMPTS / f"scenario-{int(args.index):02d}-exit-hint-discord-message.md"
        INBOX.mkdir(parents=True, exist_ok=True)
        PROMPTS.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        out_md.write_text(render_md(payload), encoding="utf-8")
        discord = render_discord(payload)
        out_txt.write_text(discord, encoding="utf-8")
        out_txt_md.write_text("```text\n" + discord + "```\n", encoding="utf-8")
        print(f"wrote {_display_path(out_md)}")
        print(f"wrote {_display_path(out_json)}")
        print(f"wrote {_display_path(out_txt)}")
    try:
        write_pipeline_event(
            pipeline="investment_analysis",
            slot="inv-scenario",
            stage="report_scenario_exit_hint",
            status="ok",
            event_date=args.date,
            return_code=0,
            payload=payload,
            source_path="scripts/investment/analysis/report_scenario_exit_hint.py",
        )
    except Exception as exc:  # pragma: no cover - telemetry should not block report output
        print(f"warn: failed to record pipeline event: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
