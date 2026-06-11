#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from notify.post_scenarios_bot import clean_company_name, patch_channel, post_message
from notify.sync_scenario_replies_bot import exit_condition_lines, hold_window_from_entry, parse_command
from utils.investment_db_path import resolve_investment_db

DEFAULT_DB = resolve_investment_db()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Post follow-up replies to scenario threads with open trades")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--max-posts", type=int, default=20)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def load_dotenv() -> None:
    for env_file in (ROOT / ".env.local", ROOT / ".env"):
        if not env_file.exists():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def load_env() -> tuple[str, str]:
    token = (
        os.getenv("DISCORD_SCENARIOS_BOT_TOKEN", "").strip()
        or os.getenv("DISCORD_SCENARIO_BOT_TOKEN", "").strip()
        or os.getenv("DISCORD_BOT_TOKEN", "").strip()
        or os.getenv("DISCORD_TASKS_BOT_TOKEN", "").strip()
    )
    channel_id = os.getenv("DISCORD_SCENARIO_CHANNEL_ID", "").strip()
    if not token:
        raise SystemExit("DISCORD_SCENARIOS_BOT_TOKEN is empty")
    if not channel_id:
        raise SystemExit("DISCORD_SCENARIO_CHANNEL_ID is empty")
    return token, channel_id


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _entry_parse_text(raw_content: str) -> str:
    text = re.sub(r"^\s*\d{4,5}\s*[／/]\s*", "", (raw_content or "").strip())
    text = re.split(r"\b(?:credit|exit|cancel)\b", text, maxsplit=1, flags=re.I)[0].strip()
    return text


def extract_entry_price(raw_content: str, parsed_json_raw: str | None) -> float | None:
    if parsed_json_raw:
        try:
            parsed = json.loads(parsed_json_raw)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            price = parsed.get("price")
            if price not in (None, ""):
                try:
                    return float(price)
                except Exception:
                    pass

    text = _entry_parse_text(raw_content)
    cmd, payload = parse_command(text)
    if cmd == "entry":
        price = payload.get("price")
        if price not in (None, ""):
            try:
                return float(price)
            except Exception:
                return None
    return None


def post_followup_content(row: dict, open_trade_count: int) -> str:
    entry_price = row.get("entry_price")
    direction = str(row["direction"] or "").strip().lower()
    company = clean_company_name(row["company"])
    scenario_tier = str(row["scenario_tier"] or "trade").strip().lower()
    tier_label = "TRADE" if scenario_tier == "trade" else ("PAPER" if scenario_tier == "paper_trade_only" else "WATCH")
    hold_window = hold_window_from_entry(float(entry_price) if entry_price is not None else None, direction)

    lines = [
        "追記: エントリー済み・未 exit のため監視継続。",
        f"対象: {row['ticker']} {company} / {direction.upper()} / {tier_label}",
        f"未 exit 建玉: {open_trade_count}件",
        f"保有目安: {hold_window}",
    ]
    if entry_price is not None:
        lines.extend(
            [
                *exit_condition_lines(row, {"price": float(entry_price)}),
                f"entry価格: {float(entry_price):.0f}円",
            ]
        )
    else:
        lines.extend(exit_condition_lines(row, {"price": None}))

    if scenario_tier != "trade":
        ladder = str(row["watch_ladder"] or "").strip()
        lines.append(f"監視強度: {ladder or 'none'}")

    lines.append("必要なら entry / exit / cancel を同じスレッドへ追記してください。")
    return "\n".join(lines)[:1900]


def load_targets(conn: sqlite3.Connection, date_str: str) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute(
        """
        WITH open_entries AS (
          SELECT
            e.parent_message_id,
            e.channel_id,
            e.raw_content,
            e.parsed_json,
            e.processed_at,
            ROW_NUMBER() OVER (
              PARTITION BY e.parent_message_id
              ORDER BY e.processed_at DESC, e.reply_message_id DESC
            ) AS rn
          FROM scenario_reply_events e
          WHERE e.command = 'entry'
            AND NOT EXISTS (
              SELECT 1
              FROM scenario_reply_events x
              WHERE x.command = 'exit'
                AND x.parent_message_id = e.parent_message_id
            )
        ),
        matched AS (
          SELECT
            sm.message_id AS scenario_message_id,
            sm.thread_id,
            sm.channel_id,
            sm.scenario_date,
            sm.scenario_index,
            sm.ticker,
            sm.company,
            sm.direction,
            sm.scenario_tier,
            sm.watch_ladder,
            oe.raw_content AS entry_raw_content,
            oe.parsed_json AS entry_parsed_json,
            oe.processed_at AS entry_processed_at,
            ROW_NUMBER() OVER (
              PARTITION BY oe.parent_message_id
              ORDER BY sm.posted_at DESC, sm.scenario_index DESC, sm.message_id DESC
            ) AS rn
          FROM open_entries oe
          JOIN scenario_messages sm
            ON sm.message_id = oe.parent_message_id
            OR sm.anchor_message_id = oe.parent_message_id
          WHERE oe.rn = 1
            AND sm.scenario_date = ?
            AND COALESCE(sm.thread_id, '') <> ''
        )
        SELECT
          scenario_message_id,
          thread_id,
          channel_id,
          scenario_date,
          scenario_index,
          ticker,
          company,
          direction,
          scenario_tier,
          watch_ladder,
          entry_raw_content,
          entry_parsed_json,
          entry_processed_at,
          1 AS open_trade_count
        FROM matched
        WHERE rn = 1
        ORDER BY scenario_index ASC, ticker ASC
        """,
        (date_str,),
    ).fetchall()


def already_posted(conn: sqlite3.Connection, scenario_message_id: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM scenario_reply_events
        WHERE command='auto_followup' AND parent_message_id=?
        LIMIT 1
        """,
        (scenario_message_id,),
    ).fetchone()
    return bool(row)


def record_followup(
    conn: sqlite3.Connection,
    *,
    reply_message_id: str,
    channel_id: str,
    parent_message_id: str,
    content: str,
    row: dict,
    open_trade_count: int,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO scenario_reply_events(
          reply_message_id, channel_id, parent_message_id, author_id, command, raw_content, parsed_json, processed_at
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            reply_message_id,
            channel_id,
            parent_message_id,
            "bot",
            "auto_followup",
            content,
            json.dumps(
                {
                    "scenario_date": str(row["scenario_date"] or ""),
                    "scenario_index": int(row["scenario_index"] or 0),
                    "ticker": str(row["ticker"] or ""),
                    "direction": str(row["direction"] or ""),
                    "scenario_tier": str(row["scenario_tier"] or ""),
                    "open_trade_count": int(open_trade_count),
                    "entry_price": row.get("entry_price"),
                },
                ensure_ascii=False,
            ),
            now_iso(),
        ),
    )


def main() -> int:
    args = parse_args()
    load_dotenv()
    token, default_channel_id = load_env()
    db = Path(args.db)
    conn = sqlite3.connect(db)
    try:
        targets = load_targets(conn, args.date)
        sent = 0
        skipped = 0
        for row in targets:
            if sent >= int(args.max_posts):
                break
            scenario_message_id = str(row["scenario_message_id"] or "")
            thread_id = str(row["thread_id"] or "")
            channel_id = str(row["channel_id"] or "") or default_channel_id
            if not scenario_message_id or not thread_id:
                skipped += 1
                continue
            if already_posted(conn, scenario_message_id):
                skipped += 1
                continue
            entry_price = extract_entry_price(str(row["entry_raw_content"] or ""), str(row["entry_parsed_json"] or ""))
            target_row = dict(row)
            target_row["entry_price"] = entry_price
            content = post_followup_content(target_row, int(row["open_trade_count"] or 0))
            if args.dry_run:
                print(f"[dry-run] thread={thread_id} ticker={row['ticker']}\n{content}\n")
                sent += 1
                continue
            try:
                try:
                    patch_channel(token, thread_id, {"archived": False, "locked": False, "auto_archive_duration": 1440})
                except Exception:
                    pass
                resp = post_message(token, thread_id, content)
                reply_message_id = str(resp.get("id", "") or "")
                if reply_message_id:
                    record_followup(
                        conn,
                        reply_message_id=reply_message_id,
                        channel_id=thread_id or channel_id,
                        parent_message_id=scenario_message_id,
                        content=content,
                        row=target_row,
                        open_trade_count=int(row["open_trade_count"] or 0),
                    )
                sent += 1
            except Exception as e:
                print(f"failed thread={thread_id} ticker={row['ticker']}: {e}", file=sys.stderr)
        if not args.dry_run:
            conn.commit()
        print(f"followups_sent={sent} skipped={skipped} date={args.date}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
