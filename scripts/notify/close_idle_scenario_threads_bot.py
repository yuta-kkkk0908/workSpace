#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from notify.post_scenarios_bot import discord_request
from utils.investment_db_path import resolve_investment_db

DEFAULT_DB = resolve_investment_db()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Delete scenario threads with no open trades")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-threads", type=int, default=200)
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


def load_env() -> str:
    token = (
        os.getenv("DISCORD_SCENARIOS_BOT_TOKEN", "").strip()
        or os.getenv("DISCORD_SCENARIO_BOT_TOKEN", "").strip()
        or os.getenv("DISCORD_BOT_TOKEN", "").strip()
        or os.getenv("DISCORD_TASKS_BOT_TOKEN", "").strip()
    )
    if not token:
        raise SystemExit("DISCORD_SCENARIOS_BOT_TOKEN is empty")
    return token


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _discord_delete(token: str, url: str) -> dict:
    req = urllib.request.Request(
        url,
        method="DELETE",
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "aios-scenario-bot/1.0",
        },
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8", errors="replace").strip()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code == 404 and ("Unknown Channel" in body or "Unknown Message" in body):
                return {}
            if e.code == 204:
                return {}
            if e.code == 429:
                try:
                    retry_after = float(json.loads(body or "{}").get("retry_after", 0.5))
                except Exception:
                    retry_after = 0.5
                time.sleep(max(0.5, retry_after) + 0.1 * attempt)
                continue
            raise RuntimeError(f"Discord API DELETE {url} failed: {e.code} {body}") from e
    raise RuntimeError(f"Discord API DELETE {url} failed after retries")


def delete_thread(token: str, thread_id: str) -> dict:
    return _discord_delete(token, f"https://discord.com/api/v10/channels/{thread_id}")


def delete_message(token: str, channel_id: str, message_id: str) -> dict:
    return _discord_delete(token, f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}")


def load_targets(conn: sqlite3.Connection, date_str: str, limit: int) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute(
        """
        WITH candidate_rows AS (
        SELECT
          sm.thread_id,
          sm.channel_id,
          COALESCE(
            NULLIF(sm.anchor_message_id, ''),
            (
              SELECT x.anchor_message_id
              FROM scenario_messages x
              WHERE x.thread_id = sm.thread_id
                AND COALESCE(x.anchor_message_id, '') <> ''
              ORDER BY x.scenario_date ASC, x.scenario_index ASC, x.message_id ASC
              LIMIT 1
            ),
            ''
          ) AS anchor_message_id,
          sm.message_id,
          sm.scenario_date,
          sm.scenario_index,
          sm.ticker,
          sm.company,
          sm.direction,
          sm.scenario_tier,
            CASE WHEN er.parent_message_id IS NOT NULL THEN 1 ELSE 0 END AS has_entry,
            CASE WHEN xr.parent_message_id IS NOT NULL THEN 1 ELSE 0 END AS has_exit,
            ROW_NUMBER() OVER (
              PARTITION BY sm.thread_id
              ORDER BY sm.scenario_date DESC, sm.scenario_index DESC, sm.message_id DESC
            ) AS rn
          FROM scenario_messages sm
          LEFT JOIN (
            SELECT DISTINCT parent_message_id
            FROM scenario_reply_events
            WHERE command='entry'
          ) er
            ON er.parent_message_id = sm.message_id
          LEFT JOIN (
            SELECT DISTINCT parent_message_id
            FROM scenario_reply_events
            WHERE command='exit'
          ) xr
            ON xr.parent_message_id = sm.message_id
          WHERE COALESCE(sm.thread_id, '') <> ''
        )
        SELECT *
        FROM candidate_rows
        WHERE rn = 1
          AND has_entry = 0
          AND has_exit = 0
        ORDER BY scenario_index ASC, ticker ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def record_result(
    conn: sqlite3.Connection,
    *,
    thread_id: str,
    channel_id: str,
    date_str: str,
    ticker: str,
    direction: str,
    scenario_tier: str,
    action: str,
    note: str,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO scenario_reply_events(
          reply_message_id, channel_id, parent_message_id, author_id, command, raw_content, parsed_json, processed_at
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            f"close-thread:{thread_id}",
            channel_id,
            thread_id,
            "bot",
            action,
            note,
            json.dumps(
                {
                    "date": date_str,
                    "ticker": ticker,
                    "direction": direction,
                    "scenario_tier": scenario_tier,
                },
                ensure_ascii=False,
            ),
            now_iso(),
        ),
    )


def main() -> int:
    args = parse_args()
    load_dotenv()
    token = load_env()
    db = Path(args.db)
    conn = sqlite3.connect(db)
    try:
        targets = load_targets(conn, args.date, int(args.max_threads))
        closed = 0
        skipped = 0
        for row in targets:
            thread_id = str(row["thread_id"] or "")
            channel_id = str(row["channel_id"] or "")
            anchor_message_id = str(row["anchor_message_id"] or "")
            if not thread_id:
                skipped += 1
                continue
            note = (
                f"auto_close_idle_thread date={args.date} ticker={row['ticker']} "
                f"direction={row['direction']} tier={row['scenario_tier']}"
            )
            if args.dry_run:
                if anchor_message_id:
                    print(f"[dry-run] delete anchor={anchor_message_id} thread={thread_id} {note}")
                else:
                    print(f"[dry-run] delete thread={thread_id} {note}")
                closed += 1
                continue
            try:
                if anchor_message_id:
                    try:
                        delete_message(token, channel_id, anchor_message_id)
                    except Exception as e:
                        print(f"failed anchor={anchor_message_id} ticker={row['ticker']}: {e}", file=sys.stderr)
                delete_thread(token, thread_id)
                record_result(
                    conn,
                    thread_id=thread_id,
                    channel_id=channel_id,
                    date_str=args.date,
                    ticker=str(row["ticker"] or ""),
                    direction=str(row["direction"] or ""),
                    scenario_tier=str(row["scenario_tier"] or ""),
                    action="auto_close_idle_thread",
                    note=note,
                )
                closed += 1
            except Exception as e:
                print(f"failed thread={thread_id} ticker={row['ticker']}: {e}", file=sys.stderr)
        if not args.dry_run:
            conn.commit()
        print(f"closed_threads={closed} skipped={skipped} date={args.date}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
