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
CREDIT_RE = re.compile(r"^credit\s+(?P<status>ok|ng|unknown)$", re.I)
TICKER_PREFIX_RE = re.compile(r"^\s*(?P<ticker>\d{4,5})\s*[／/]\s*")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sync Discord replies for scenario messages into investment.db")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--entry-cooldown-seconds", type=int, default=30, help="cooldown for repeated entry by same user on same scenario")
    p.add_argument("--max-reply-age-hours", type=float, default=3.0, help="ignore replies older than this window")
    p.add_argument("--debug-summary", action="store_true", help="print skip reason summary")
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


def should_ignore_by_age(created_at_raw: str, max_age_hours: float) -> bool:
    if max_age_hours <= 0:
        return False
    dt = parse_iso_utc(created_at_raw)
    if dt is None:
        return False
    age_sec = (datetime.now(timezone.utc) - dt).total_seconds()
    return age_sec > (max_age_hours * 3600.0)


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


def api_get_active_threads(token: str, channel_id: str) -> list[dict]:
    channel = api_get_channel(token, channel_id)
    guild_id = str((channel or {}).get("guild_id", "") or "")
    if not guild_id:
        return []
    url = f"https://discord.com/api/v10/guilds/{guild_id}/threads/active"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": "aios-scenario-bot/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    parent_match = []
    for th in list(payload.get("threads") or []):
        if str(th.get("parent_id", "") or "") == channel_id:
            parent_match.append(th)
    return parent_match


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


def api_get_message(token: str, channel_id: str, message_id: str) -> dict | None:
    if not message_id:
        return None
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": "aios-scenario-bot/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def api_get_channel(token: str, channel_id: str) -> dict | None:
    url = f"https://discord.com/api/v10/channels/{channel_id}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": "aios-scenario-bot/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


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


def extract_entry_mode(text: str) -> str | None:
    s = (text or "").strip().lower()
    if "机上" in (text or ""):
        return "paper"
    if re.search(r"\bpaper\b", s):
        return "paper"
    return None


def strip_entry_mode_tokens(text: str) -> str:
    s = (text or "").replace("机上", " ")
    s = re.sub(r"\bpaper\b", " ", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_command(content: str) -> tuple[str, dict] | tuple[None, dict]:
    text = (content or "").strip()
    text = re.sub(r"^\s*\d{4,5}\s*[／/]\s*", "", text)
    text_core = strip_entry_mode_tokens(text)
    low = text.lower()
    norm = re.sub(r"[／/]+", " ", low)
    norm = re.sub(r"\s+", " ", norm).strip()

    # 1) Backward-compatible positional style.
    m = ENTRY_RE.match(text_core)
    if m:
        lots = int(m.group("lots")) if m.group("lots") else 1
        price = float(m.group("price")) if m.group("price") else None
        mode_override = extract_entry_mode(text)
        return "entry", {"lots": lots, "price": price, "mode_override": mode_override}
    m = EXIT_RE.match(text_core)
    if m:
        price = float(m.group("price")) if m.group("price") else None
        mode_override = extract_entry_mode(text)
        return "exit", {"price": price, "reason": "manual", "mode_override": mode_override}
    if CANCEL_RE.match(text_core):
        mode_override = extract_entry_mode(text)
        return "cancel", {"mode_override": mode_override}
    m = CREDIT_RE.match(text)
    if m:
        s = m.group("status").lower()
        mapped = {
            "ok": "manual_marginable",
            "ng": "manual_non_marginable",
            "unknown": "manual_unknown",
        }[s]
        # Shorthand policy:
        # credit ok      -> buy/sell both ok
        # credit ng      -> buy/sell both ng
        # credit unknown -> buy/sell both unknown
        return "credit", {"credit_status": mapped, "buy": s, "sell": s}

    # credit buy/sell variants:
    # - credit buy ok / credit sell ng
    # - creditbuy ok creditsell ng
    # - ticker/credit buy ok/credit sell ng  (ticker token is ignored here)
    compact = re.sub(r"\s+", "", low)
    compact = compact.replace("／", "/")
    if "credit" in compact:
        buy = None
        sell = None
        m_buy = re.search(r"credit\s*buy\s*(ok|ng|unknown)", norm, re.I) or re.search(r"creditbuy\s*(ok|ng|unknown)", compact, re.I)
        m_sell = re.search(r"credit\s*sell\s*(ok|ng|unknown)", norm, re.I) or re.search(r"creditsell\s*(ok|ng|unknown)", compact, re.I)
        if m_buy:
            buy = m_buy.group(1).lower()
        if m_sell:
            sell = m_sell.group(1).lower()
        if buy is not None or sell is not None:
            # Conservative mapping:
            # any NG => non-marginable, any unknown (without NG) => unknown, otherwise marginable.
            vals = [v for v in [buy, sell] if v is not None]
            if any(v == "ng" for v in vals):
                mapped = "manual_non_marginable"
            elif any(v == "unknown" for v in vals):
                mapped = "manual_unknown"
            else:
                mapped = "manual_marginable"
            return "credit", {"credit_status": mapped, "buy": buy, "sell": sell}

    # 2) key=value style
    if low.startswith("entry"):
        rest = text_core[5:].strip()
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
        mode_override = extract_entry_mode(text + " " + rest)
        return "entry", {"lots": lots, "price": price, "mode_override": mode_override}

    if low.startswith("exit"):
        # Supported:
        # - exit tp
        # - exit tp 4070
        # - exit reason=tp price=4070
        rest = text_core[4:].strip()
        if not rest:
            return "exit", {"price": None, "reason": "manual", "mode_override": extract_entry_mode(text)}

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
        return "exit", {"price": price, "reason": reason, "mode_override": extract_entry_mode(text)}

    return None, {"error": "unknown_command", "raw": text}


def extract_ticker_hint(content: str) -> str:
    m = TICKER_PREFIX_RE.match((content or "").strip())
    if not m:
        return ""
    return str(m.group("ticker") or "").strip()


def scenario_row(conn: sqlite3.Connection, parent_message_id: str) -> sqlite3.Row | None:
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "select scenario_date,scenario_index,ticker,company,direction,scenario_tier,signal_id,source_path,message_id from scenario_messages where message_id=? or anchor_message_id=? order by posted_at desc limit 1",
        (parent_message_id, parent_message_id),
    ).fetchone()


def scenario_row_by_thread(conn: sqlite3.Connection, thread_id: str) -> sqlite3.Row | None:
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "select scenario_date,scenario_index,ticker,company,direction,scenario_tier,signal_id,source_path,message_id from scenario_messages where thread_id=? order by posted_at desc limit 1",
        (thread_id,),
    ).fetchone()


def latest_scenario_by_ticker(conn: sqlite3.Connection, ticker: str) -> dict | None:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT scenario_date,scenario_index,ticker,company,direction,scenario_tier,signal_id,source_path
        FROM opening_scenarios
        WHERE ticker=?
        ORDER BY scenario_date DESC,
                 CASE source_kind WHEN 'scenario' THEN 0 ELSE 1 END,
                 scenario_index ASC
        LIMIT 1
        """,
        (ticker,),
    ).fetchone()
    return dict(row) if row else None


def resolve_scenario_row(
    conn: sqlite3.Connection,
    token: str,
    channel_id: str,
    initial_parent_message_id: str,
    max_depth: int = 5,
) -> tuple[sqlite3.Row | None, str]:
    """
    Follow reply chain to find a scenario message row.
    Returns (row, matched_parent_message_id).
    """
    current = initial_parent_message_id
    depth = 0
    while current and depth <= max_depth:
        sc = scenario_row(conn, current)
        if sc is not None:
            return sc, current
        msg = api_get_message(token, channel_id, current)
        if not msg:
            break
        ref = msg.get("message_reference") or {}
        nxt = str(ref.get("message_id", "") or "")
        if not nxt or nxt == current:
            break
        current = nxt
        depth += 1
    return None, initial_parent_message_id


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
    mode_override = str(payload.get("mode_override") or "").strip().lower()
    if mode_override == "paper":
        mode = "paper"
    else:
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
    mode_override = str(payload.get("mode_override") or "").strip().lower()
    if mode_override == "paper":
        mode = "paper"
    else:
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


def apply_cancel(conn: sqlite3.Connection, sc: sqlite3.Row, payload: dict | None = None) -> str | None:
    side = "long" if sc["direction"] == "long" else "short"
    mode_override = str((payload or {}).get("mode_override") or "").strip().lower()
    if mode_override == "paper":
        mode = "paper"
    else:
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
    mode_override = str(payload.get("mode_override") or "").strip().lower()
    if mode_override == "paper":
        mode = "paper"
    else:
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
    if cmd == "credit":
        cs = str(payload.get("credit_status") or "")
        return f"{head}\n{sc['ticker']} {sc['company']}\ncredit_status={cs}"
    return f"{head}\n{base}"


def apply_credit(conn: sqlite3.Connection, sc: sqlite3.Row, payload: dict) -> None:
    cs = str(payload.get("credit_status") or "").strip()
    buy = str(payload.get("buy") or "").strip().lower() or None
    sell = str(payload.get("sell") or "").strip().lower() or None
    if not cs:
        return
    d = str(sc["scenario_date"] or "")
    t = str(sc["ticker"] or "")
    conn.execute(
        """
        INSERT INTO credit_status_rows(date,ticker,credit_status,buy_status,sell_status,source_kind,source_detail,updated_at)
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(date,ticker) DO UPDATE SET
          credit_status=excluded.credit_status,
          buy_status=COALESCE(excluded.buy_status, credit_status_rows.buy_status),
          sell_status=COALESCE(excluded.sell_status, credit_status_rows.sell_status),
          source_kind=excluded.source_kind,
          source_detail=excluded.source_detail,
          updated_at=excluded.updated_at
        """,
        (
            d,
            t,
            cs,
            buy,
            sell,
            "manual_reply",
            "discord_scenario_reply",
            now_iso(),
        ),
    )


def ack_error_text(sc: sqlite3.Row, raw: str, err: str) -> str:
    return (
        "ACK: FORMAT ERROR\n"
        f"{sc['ticker']} {sc['company']} / error={err}\n"
        "使い方:\n"
        "- entry 100 4022\n"
        "- entry paper 100 4022 / entry 机上 100 4022\n"
        "- entry lots=100 price=4022\n"
        "- entry paper lots=100 price=4022\n"
        "- exit 4070\n"
        "- exit tp 4070\n"
        "- exit paper tp 4070\n"
        "- exit reason=tp price=4070\n"
        "- cancel\n"
        "- cancel paper\n"
        "- credit ng|ok|unknown\n"
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
    db = Path(args.db)
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    sync_log = log_dir / "sync-scenario-replies.log"

    conn = sqlite3.connect(db)
    try:
        processed = 0
        applied = 0
        messages: list[dict] = []
        messages.extend(api_get_messages(token, channel_id, args.limit))
        for th in api_get_active_threads(token, channel_id):
            thread_id = str(th.get("id", "") or "")
            if not thread_id:
                continue
            try:
                messages.extend(api_get_messages(token, thread_id, args.limit))
            except Exception:
                continue
        stats = {
            "total_messages": 0,
            "skip_bot": 0,
            "skip_no_parent": 0,
            "skip_already_processed": 0,
            "skip_too_old": 0,
            "skip_no_scenario_row": 0,
            "skip_unknown_text": 0,
            "skip_invalid": 0,
            "handled": 0,
        }
        for m in messages:
            stats["total_messages"] += 1
            mid = str(m.get("id", ""))
            if not mid:
                continue
            author = m.get("author") or {}
            if bool(author.get("bot")):
                # Ignore bot-authored messages (including our own ACK replies).
                stats["skip_bot"] += 1
                continue
            ref = m.get("message_reference") or {}
            parent_mid = str(ref.get("message_id", "") or "")
            if reply_processed(conn, mid):
                stats["skip_already_processed"] += 1
                continue
            if should_ignore_by_age(str(m.get("timestamp", "")), float(args.max_reply_age_hours)):
                stats["skip_too_old"] += 1
                continue
            raw_content = str(m.get("content", ""))
            message_channel_id = str(m.get("channel_id", "") or "")
            ticker_hint = extract_ticker_hint(raw_content)
            cmd, payload = parse_command(raw_content)
            sc = None
            resolved_parent_mid = parent_mid
            if message_channel_id and message_channel_id != channel_id:
                sc = scenario_row_by_thread(conn, message_channel_id)
                if sc is not None:
                    resolved_parent_mid = str(sc["message_id"] or "")
            elif parent_mid:
                sc, resolved_parent_mid = resolve_scenario_row(conn, token, channel_id, parent_mid)
            else:
                stats["skip_no_parent"] += 1
                continue
            if sc is None:
                # Fallback: credit command can be applied by ticker hint even if parent message is not registered.
                if cmd == "credit" and ticker_hint:
                    sc_fb = latest_scenario_by_ticker(conn, ticker_hint)
                    if sc_fb is not None:
                        sc = sc_fb
                        resolved_parent_mid = parent_mid
                if sc is None:
                    stats["skip_no_scenario_row"] += 1
                    continue
            if not cmd:
                err = str((payload or {}).get("error", "unknown_command"))
                if err == "unknown_command":
                    stats["skip_unknown_text"] += 1
                    continue
                stats["skip_invalid"] += 1
                # Invalid format reply should be acknowledged.
                if not args.dry_run:
                    try:
                        api_post_ack(
                            token,
                            message_channel_id or channel_id,
                            mid,
                            ack_error_text(sc, str(m.get("content", "")), err),
                        )
                    except Exception:
                        pass
                    log_reply(
                        conn,
                        reply_message_id=mid,
                        channel_id=message_channel_id or channel_id,
                        parent_message_id=resolved_parent_mid,
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
                        channel_id=message_channel_id or channel_id,
                        parent_message_id=resolved_parent_mid,
                        author_id=author_id,
                        cooldown_seconds=int(args.entry_cooldown_seconds),
                    ):
                        log_reply(
                            conn,
                            reply_message_id=mid,
                            channel_id=message_channel_id or channel_id,
                            parent_message_id=resolved_parent_mid,
                            author_id=author_id,
                            command="entry",
                            raw_content=str(m.get("content", "")),
                            parsed={**payload, "trade_id": None, "ack_status": "SKIP（短時間連投）"},
                        )
                        try:
                            api_post_ack(
                                token,
                                message_channel_id or channel_id,
                                mid,
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
                    trade_id = apply_cancel(conn, sc, payload)
                elif cmd == "credit":
                    apply_credit(conn, sc, payload)
                log_reply(
                    conn,
                    reply_message_id=mid,
                    channel_id=message_channel_id or channel_id,
                    parent_message_id=resolved_parent_mid,
                    author_id=author_id,
                    command=cmd,
                    raw_content=str(m.get("content", "")),
                    parsed={**payload, "trade_id": trade_id, "ack_status": "反映"},
                )
                try:
                    api_post_ack(
                        token,
                        message_channel_id or channel_id,
                        mid,
                        ack_text(cmd, sc, payload, trade_id, "反映"),
                    )
                except Exception:
                    # ACK failure should not block DB reflection.
                    pass
                applied += 1
            stats["handled"] += 1
            processed += 1

        if not args.dry_run:
            conn.commit()
    finally:
        conn.close()

    print(f"reply_candidates={processed} applied={0 if args.dry_run else applied}")
    if args.debug_summary:
        print("debug_summary=" + json.dumps(stats, ensure_ascii=False))
    try:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        line = {
            "ts": ts,
            "dry_run": bool(args.dry_run),
            "reply_candidates": int(processed),
            "applied": int(0 if args.dry_run else applied),
            "stats": stats,
        }
        with sync_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
