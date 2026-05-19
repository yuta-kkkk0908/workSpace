#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "investment.db"

ENTRY_RE = re.compile(r"^entry(?:\s+(?P<lots>\d+))?(?:\s+(?P<price>\d+(?:\.\d+)?))?$", re.I)
EXIT_RE = re.compile(r"^exit(?:\s+(?P<price>\d+(?:\.\d+)?))?$", re.I)
CANCEL_RE = re.compile(r"^cancel$", re.I)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sync Discord replies for scenario messages into investment.db")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--entry-cooldown-seconds", type=int, default=30, help="cooldown for repeated entry by same user on same scenario")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso_utc(raw: str) -> datetime | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_env() -> tuple[str, str]:
    token = (
        os.getenv("DISCORD_SCENARIOS_BOT_TOKEN", "").strip()
        or os.getenv("DISCORD_SCENARIO_BOT_TOKEN", "").strip()
        or os.getenv("DISCORD_BOT_TOKEN", "").strip()
    )
    channel_id = os.getenv("DISCORD_SCENARIO_CHANNEL_ID", "").strip()
    if not token:
        raise SystemExit("DISCORD_SCENARIOS_BOT_TOKEN is empty")
    if not channel_id:
        raise SystemExit("DISCORD_SCENARIO_CHANNEL_ID is empty")
    return token, channel_id


def api_get_messages(token: str, channel_id: str, limit: int) -> list[dict]:
    q = urllib.parse.urlencode({"limit": max(1, min(limit, 100))})
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages?{q}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": "aios-scenario-bot/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def api_post_ack(token: str, channel_id: str, parent_message_id: str, content: str) -> None:
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    body = json.dumps(
        {
            "content": content,
            "message_reference": {"message_id": parent_message_id, "channel_id": channel_id},
            "allowed_mentions": {"parse": []},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "aios-scenario-bot/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=20):
        return


def _token_kv_map(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for tok in text.split():
        if "=" not in tok:
            continue
        k, v = tok.split("=", 1)
        k = k.strip().lower()
        v = v.strip()
        if k:
            out[k] = v
    return out


def parse_command(content: str) -> tuple[str, dict] | tuple[None, dict]:
    text = (content or "").strip()
    low = text.lower()

    # 1) Backward-compatible positional style.
    m = ENTRY_RE.match(text)
    if m:
        lots = int(m.group("lots")) if m.group("lots") else 1
        price = float(m.group("price")) if m.group("price") else None
        return "entry", {"lots": lots, "price": price}
    m = EXIT_RE.match(text)
    if m:
        price = float(m.group("price")) if m.group("price") else None
        return "exit", {"price": price, "reason": "manual"}
    if CANCEL_RE.match(text):
        return "cancel", {}

    # 2) key=value style
    if low.startswith("entry"):
        rest = text[5:].strip()
        kv = _token_kv_map(rest)
        lots_raw = kv.get("lots", "1")
        price_raw = kv.get("price", "")
        try:
            lots = int(lots_raw)
        except ValueError:
            return None, {"error": "invalid_lots", "raw": text}
        if lots <= 0:
            return None, {"error": "invalid_lots", "raw": text}
        price = None
        if price_raw:
            try:
                price = float(price_raw)
            except ValueError:
                return None, {"error": "invalid_price", "raw": text}
        return "entry", {"lots": lots, "price": price}

    if low.startswith("exit"):
        # Supported:
        # - exit tp
        # - exit tp 4070
        # - exit reason=tp price=4070
        rest = text[4:].strip()
        if not rest:
            return "exit", {"price": None, "reason": "manual"}

        kv = _token_kv_map(rest)
        reason = kv.get("reason", "").lower()
        price_raw = kv.get("price", "")
        allowed = {"tp", "sl", "time", "manual"}

        if not reason:
            toks = rest.split()
            if toks and toks[0].lower() in allowed:
                reason = toks[0].lower()
                if len(toks) >= 2 and not price_raw:
                    price_raw = toks[1]
            elif toks and re.fullmatch(r"\d+(?:\.\d+)?", toks[0]):
                reason = "manual"
                price_raw = toks[0]
            else:
                return None, {"error": "invalid_exit_reason", "raw": text}

        if reason not in allowed:
            return None, {"error": "invalid_exit_reason", "raw": text}

        price = None
        if price_raw:
            try:
                price = float(price_raw)
            except ValueError:
                return None, {"error": "invalid_price", "raw": text}
        return "exit", {"price": price, "reason": reason}

    return None, {"error": "unknown_command", "raw": text}


def scenario_row(conn: sqlite3.Connection, parent_message_id: str) -> sqlite3.Row | None:
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "select scenario_date,scenario_index,ticker,company,direction,scenario_tier,signal_id,source_path from scenario_messages where message_id=?",
        (parent_message_id,),
    ).fetchone()


def reply_processed(conn: sqlite3.Connection, reply_message_id: str) -> bool:
    row = conn.execute("select 1 from scenario_reply_events where reply_message_id=?", (reply_message_id,)).fetchone()
    return bool(row)


def latest_trade_id(conn: sqlite3.Connection, scenario_date: str, ticker: str, side: str, mode: str) -> str | None:
    row = conn.execute(
        """
        select trade_id from paper_trades
        where mode=? and entry_date=? and ticker=? and side=?
        order by updated_at desc limit 1
        """,
        (mode, scenario_date, ticker, side),
    ).fetchone()
    return row[0] if row else None


def next_trade_id(conn: sqlite3.Connection, scenario_date: str, ticker: str, side: str, mode: str) -> str:
    base = f"{mode}_{scenario_date.replace('-', '')}_{ticker}_{side}_"
    rows = conn.execute(
        "select trade_id from paper_trades where trade_id like ?",
        (base + "%",),
    ).fetchall()
    max_no = 0
    for r in rows:
        tid = str(r[0] or "")
        tail = tid[len(base) :]
        try:
            n = int(tail)
        except ValueError:
            continue
        if n > max_no:
            max_no = n
    return f"{base}{max_no + 1:02d}"


def apply_entry(conn: sqlite3.Connection, sc: sqlite3.Row, payload: dict) -> tuple[str, bool]:
    side = "long" if sc["direction"] == "long" else "short"
    mode = "watch" if str(sc["scenario_tier"] or "trade") == "watch" else "live"
    trade_id = next_trade_id(conn, sc["scenario_date"], sc["ticker"], side, mode)
    lots = int(payload.get("lots") or 1)
    price = payload.get("price")
    conn.execute(
        """
        INSERT INTO paper_trades(
          trade_id, mode, entry_date, ticker, company, side, lots, entry_style,
          planned_entry_price, status, signal_id, source_path, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            trade_id,
            mode,
            sc["scenario_date"],
            sc["ticker"],
            sc["company"],
            side,
            lots,
            "discord_reply",
            price,
            "open_pending_outcome",
            sc["signal_id"],
            sc["source_path"],
            now_iso(),
        ),
    )
    return trade_id, True


def apply_exit(conn: sqlite3.Connection, sc: sqlite3.Row, payload: dict) -> str | None:
    side = "long" if sc["direction"] == "long" else "short"
    mode = "watch" if str(sc["scenario_tier"] or "trade") == "watch" else "live"
    trade_id = latest_trade_id(conn, sc["scenario_date"], sc["ticker"], side, mode)
    if not trade_id:
        return None
    price = payload.get("price")
    reason = str(payload.get("reason") or "manual")
    conn.execute(
        "update paper_trades set status='closed_manual', exit_price=?, exit_reason=?, updated_at=? where trade_id=?",
        (price, reason, now_iso(), trade_id),
    )
    return trade_id


def apply_cancel(conn: sqlite3.Connection, sc: sqlite3.Row) -> str | None:
    side = "long" if sc["direction"] == "long" else "short"
    mode = "watch" if str(sc["scenario_tier"] or "trade") == "watch" else "live"
    trade_id = latest_trade_id(conn, sc["scenario_date"], sc["ticker"], side, mode)
    if not trade_id:
        return None
    conn.execute(
        "update paper_trades set status='cancelled', updated_at=? where trade_id=?",
        (now_iso(), trade_id),
    )
    return trade_id


def ack_text(cmd: str, sc: sqlite3.Row, payload: dict, trade_id: str | None, status_label: str = "反映") -> str:
    head = f"ACK: {cmd.upper()} {status_label}"
    mode = "watch" if str(sc["scenario_tier"] or "trade") == "watch" else "live"
    base = f"{sc['ticker']} {sc['company']} / trade_id={trade_id or 'N/A'} / mode={mode}"
    if cmd == "entry":
        lots = payload.get("lots", 1)
        price = payload.get("price")
        px = f"{price}" if price is not None else "auto"
        return f"{head}\n{base}\nlots={lots} price={px} status=open_pending_outcome"
    if cmd == "exit":
        price = payload.get("price")
        reason = payload.get("reason", "manual")
        px = f"{price}" if price is not None else "manual"
        return f"{head}\n{base}\nexit_price={px} reason={reason} status=closed_manual"
    if cmd == "cancel":
        return f"{head}\n{base}\nstatus=cancelled"
    return f"{head}\n{base}"


def ack_error_text(sc: sqlite3.Row, raw: str, err: str) -> str:
    return (
        "ACK: FORMAT ERROR\n"
        f"{sc['ticker']} {sc['company']} / error={err}\n"
        "使い方:\n"
        "- entry 100 4022\n"
        "- entry lots=100 price=4022\n"
        "- exit 4070\n"
        "- exit tp 4070\n"
        "- exit reason=tp price=4070\n"
        "- cancel\n"
        f"received: {raw[:120]}"
    )


def log_reply(conn: sqlite3.Connection, *, reply_message_id: str, channel_id: str, parent_message_id: str, author_id: str, command: str, raw_content: str, parsed: dict) -> None:
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
            author_id,
            command,
            raw_content,
            json.dumps(parsed, ensure_ascii=False),
            now_iso(),
        ),
    )


def should_cooldown_entry(
    conn: sqlite3.Connection,
    *,
    channel_id: str,
    parent_message_id: str,
    author_id: str,
    cooldown_seconds: int,
) -> bool:
    if cooldown_seconds <= 0:
        return False
    row = conn.execute(
        """
        select processed_at
        from scenario_reply_events
        where channel_id=?
          and parent_message_id=?
          and author_id=?
          and command='entry'
        order by processed_at desc
        limit 1
        """,
        (channel_id, parent_message_id, author_id),
    ).fetchone()
    if not row:
        return False
    last_dt = parse_iso_utc(str(row[0] or ""))
    if last_dt is None:
        return False
    return (datetime.now(timezone.utc) - last_dt).total_seconds() < cooldown_seconds


def main() -> int:
    args = parse_args()
    load_dotenv()
    token, channel_id = load_env()
    messages = api_get_messages(token, channel_id, args.limit)

    db = Path(args.db)
    conn = sqlite3.connect(db)
    try:
        processed = 0
        applied = 0
        for m in messages:
            mid = str(m.get("id", ""))
            if not mid:
                continue
            ref = m.get("message_reference") or {}
            parent_mid = str(ref.get("message_id", "") or "")
            if not parent_mid:
                continue
            if reply_processed(conn, mid):
                continue
            sc = scenario_row(conn, parent_mid)
            if sc is None:
                continue
            cmd, payload = parse_command(str(m.get("content", "")))
            if not cmd:
                # Invalid format reply should be acknowledged.
                if not args.dry_run:
                    try:
                        api_post_ack(
                            token,
                            channel_id,
                            parent_mid,
                            ack_error_text(sc, str(m.get("content", "")), str((payload or {}).get("error", "invalid_format"))),
                        )
                    except Exception:
                        pass
                    log_reply(
                        conn,
                        reply_message_id=mid,
                        channel_id=channel_id,
                        parent_message_id=parent_mid,
                        author_id=str((m.get("author") or {}).get("id", "")),
                        command="invalid",
                        raw_content=str(m.get("content", "")),
                        parsed=payload or {"error": "invalid_format"},
                    )
                processed += 1
                continue

            if not args.dry_run:
                trade_id = None
                author_id = str((m.get("author") or {}).get("id", ""))
                if cmd == "entry":
                    if should_cooldown_entry(
                        conn,
                        channel_id=channel_id,
                        parent_message_id=parent_mid,
                        author_id=author_id,
                        cooldown_seconds=int(args.entry_cooldown_seconds),
                    ):
                        log_reply(
                            conn,
                            reply_message_id=mid,
                            channel_id=channel_id,
                            parent_message_id=parent_mid,
                            author_id=author_id,
                            command="entry",
                            raw_content=str(m.get("content", "")),
                            parsed={**payload, "trade_id": None, "ack_status": "SKIP（短時間連投）"},
                        )
                        try:
                            api_post_ack(
                                token,
                                channel_id,
                                parent_mid,
                                "ACK: ENTRY SKIP（短時間連投）\n同一シナリオへの連続entryは少し間隔を空けてください。",
                            )
                        except Exception:
                            pass
                        processed += 1
                        continue
                    trade_id, _ = apply_entry(conn, sc, payload)
                elif cmd == "exit":
                    trade_id = apply_exit(conn, sc, payload)
                elif cmd == "cancel":
                    trade_id = apply_cancel(conn, sc)
                log_reply(
                    conn,
                    reply_message_id=mid,
                    channel_id=channel_id,
                    parent_message_id=parent_mid,
                    author_id=author_id,
                    command=cmd,
                    raw_content=str(m.get("content", "")),
                    parsed={**payload, "trade_id": trade_id, "ack_status": "反映"},
                )
                try:
                    api_post_ack(
                        token,
                        channel_id,
                        parent_mid,
                        ack_text(cmd, sc, payload, trade_id, "反映"),
                    )
                except Exception:
                    # ACK failure should not block DB reflection.
                    pass
                applied += 1
            processed += 1

        if not args.dry_run:
            conn.commit()
    finally:
        conn.close()

    print(f"reply_candidates={processed} applied={0 if args.dry_run else applied}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
