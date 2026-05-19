#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INBOX = ROOT / "topics" / "investment-research" / "inbox"
DEFAULT_DB = ROOT / "data" / "investment.db"
JST = timezone(timedelta(hours=9))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Post opening scenarios to Discord channel (1 symbol = 1 message)")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--fallback-days", type=int, default=3)
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--max-posts", type=int, default=12)
    p.add_argument("--watch-posts", type=int, default=4, help="max watch-tier posts from rejected scenarios")
    p.add_argument(
        "--min-trade-posts",
        type=int,
        default=3,
        help="target minimum number of trade posts. If fewer trades exist, watch posts are expanded up to max-posts",
    )
    p.add_argument("--dedupe-hours", type=int, default=6, help="skip same ticker/direction/tier posted within this window")
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


def find_scenario_json(date_str: str, fallback_days: int) -> tuple[Path, str]:
    d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
    for i in range(0, max(0, fallback_days) + 1):
        d = (d0 - timedelta(days=i)).isoformat()
        p = INBOX / f"{d}-opening-scenarios.json"
        if p.exists():
            return p, d
    raise SystemExit(f"opening-scenarios not found for {date_str} (fallback_days={fallback_days})")


def find_watch_promotion_json(date_str: str, fallback_days: int) -> tuple[Path | None, str | None]:
    d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
    for i in range(0, max(0, fallback_days) + 1):
        d = (d0 - timedelta(days=i)).isoformat()
        p = INBOX / f"{d}-watch-promotion-candidates.json"
        if p.exists():
            return p, d
    return None, None


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


def direction_ja(v: str) -> str:
    return {"long": "ロング", "short": "ショート"}.get((v or "").strip(), v or "")


def hold_days_ja(v: str) -> str:
    x = (v or "").strip().upper()
    if x == "T+1":
        return "1営業日程度"
    if x == "T+5":
        return "3-5営業日程度"
    if x == "T+20":
        return "10-20営業日程度"
    return "未定（短期監視）"


def invalidation(row: dict) -> str:
    skips = row.get("skipConditions", []) or []
    if skips:
        return str(skips[0])
    return str(row.get("invalidationCondition", "") or "前提が崩れた場合は見送り/撤退")


def rationale(row: dict) -> str:
    parts = [
        str(row.get("trigger", "") or ""),
        str(row.get("ruleReproducibility", "") or ""),
        str(row.get("estimatedWinRate", "") or ""),
    ]
    parts = [p for p in parts if p]
    return " / ".join(parts) if parts else "根拠情報不足"


def to_message(date_str: str, idx: int, row: dict) -> str:
    hold_code = str(row.get("suggestedHorizon", "") or "")
    tier = str(row.get("scenarioTier", "trade"))
    tier_label = "TRADE" if tier == "trade" else "WATCH"
    entry = row.get("entryLimitRule", "") or "条件未設定（watch観測用）"
    take = row.get("takeProfitRule", "") or "条件未設定（watch観測用）"
    stop = row.get("stopLossRule", "") or "条件未設定（watch観測用）"
    lines = [
        f"【{date_str} シナリオ #{idx} / {tier_label}】{row.get('ticker','')} {row.get('company','')}",
        f"方向: {direction_ja(row.get('direction',''))}",
        f"品質: score={row.get('scenarioScore',0)} / ruleHits={row.get('ruleHitCount',0)} / {row.get('estimatedWinRate','')}",
        f"根拠: {rationale(row)}",
        f"エントリー: {entry}",
        f"利確: {take}",
        f"損切: {stop}",
        f"想定保有日数: {hold_days_ja(hold_code)}（{hold_code or 'N/A'}）",
        f"無効化条件: {invalidation(row)}",
        f"補足: ruleHits={row.get('ruleHitCount',0)} / source={row.get('candidateSource','primary')}",
        "返信コマンド例: entry 100 4022 / entry lots=100 price=4022 / exit tp 4070 / exit reason=sl / cancel",
    ]
    if tier != "trade":
        ladder = str(row.get("watchLadder", "") or "").strip()
        lines.append(f"優先度: Ladder={ladder or 'none'}")
        lines.append("注意: WATCH枠（検証優先）。entry時は paper_trades.mode=watch で記録")
    msg = "\n".join(lines)
    return msg[:1900]


def post_message(token: str, channel_id: str, content: str) -> dict:
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    body = json.dumps({"content": content}, ensure_ascii=False).encode("utf-8")
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
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def upsert_scenario_message(conn: sqlite3.Connection, *, scenario_date: str, scenario_index: int, channel_id: str, message_id: str, row: dict, source_path: str) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    conn.execute(
        """
        INSERT INTO scenario_messages(
          scenario_date, scenario_index, channel_id, message_id, ticker, company, direction, scenario_tier, watch_ladder, signal_id, source_path, posted_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(message_id) DO UPDATE SET
          scenario_date=excluded.scenario_date,
          scenario_index=excluded.scenario_index,
          ticker=excluded.ticker,
          company=excluded.company,
          direction=excluded.direction,
          scenario_tier=excluded.scenario_tier,
          watch_ladder=excluded.watch_ladder,
          signal_id=excluded.signal_id,
          source_path=excluded.source_path,
          updated_at=excluded.updated_at
        """,
        (
            scenario_date,
            scenario_index,
            channel_id,
            message_id,
            str(row.get("ticker", "")),
            str(row.get("company", "")),
            str(row.get("direction", "")),
            str(row.get("scenarioTier", "trade")),
            str(row.get("watchLadder", "")),
            str(row.get("signalId", "")),
            source_path,
            now,
            now,
        ),
    )


def is_recent_duplicate(
    conn: sqlite3.Connection,
    *,
    channel_id: str,
    ticker: str,
    direction: str,
    scenario_tier: str,
    dedupe_hours: int,
) -> bool:
    if dedupe_hours <= 0:
        return False
    rows = conn.execute(
        """
        select posted_at
        from scenario_messages
        where channel_id=?
          and ticker=?
          and direction=?
          and scenario_tier=?
        """,
        (channel_id, ticker, direction, scenario_tier),
    ).fetchall()
    if not rows:
        return False
    threshold = datetime.now(timezone.utc) - timedelta(hours=dedupe_hours)
    for r in rows:
        raw = str(r[0] or "").strip()
        if not raw:
            continue
        # Stored as ISO8601 with Z in this repo.
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt >= threshold:
            return True
    return False


def direction_to_side(v: str) -> str:
    x = (v or "").strip().lower()
    return "long" if x == "long" else "short"


def bucket_none_ladder(row: dict, *, high_score_threshold: int = 80) -> str:
    score = int(row.get("scenarioScore", 0) or 0)
    return "none-high-score" if score >= high_score_threshold else "none-low-score"


def main() -> int:
    args = parse_args()
    load_dotenv()
    token, channel_id = load_env()
    src, src_date = find_scenario_json(args.date, args.fallback_days)
    promo_path, promo_date = find_watch_promotion_json(args.date, args.fallback_days)
    data = json.loads(src.read_text(encoding="utf-8"))
    max_posts = max(0, args.max_posts)
    trade_rows = (data.get("scenarios", []) or [])[:max_posts]
    for r in trade_rows:
        r["scenarioTier"] = "trade"
    trade_count = len(trade_rows)
    base_watch_posts = max(0, args.watch_posts)
    # If trade scenarios are thin, backfill with watch scenarios to keep observation throughput.
    shortfall = max(0, int(args.min_trade_posts) - trade_count)
    watch_cap = min(max_posts, base_watch_posts + shortfall)
    # Avoid overfill beyond total post cap.
    watch_cap = max(0, min(watch_cap, max_posts - trade_count))
    watch_rows = []
    for r in (data.get("rejectedScenarios", []) or []):
        if len(watch_rows) >= watch_cap:
            break
        x = dict(r)
        x["scenarioTier"] = "watch"
        watch_rows.append(x)

    # Prioritize watch rows by ladder candidates (early > balanced > strict).
    ladder_rank: dict[tuple[str, str], int] = {}
    ladder_label: dict[tuple[str, str], str] = {}
    if promo_path:
        try:
            promo = json.loads(promo_path.read_text(encoding="utf-8"))
            ladder = promo.get("ladder", {}) or {}
            for rank, key in enumerate(("early", "balanced", "strict")):
                for row in (ladder.get(key, []) or []):
                    tk = str(row.get("ticker", "")).strip()
                    sd = str(row.get("side", "")).strip().lower()
                    if not tk or sd not in {"long", "short"}:
                        continue
                    k = (tk, sd)
                    if k not in ladder_rank:
                        ladder_rank[k] = rank
                        ladder_label[k] = key
        except Exception:
            ladder_rank = {}
            ladder_label = {}
    if ladder_rank:
        watch_rows.sort(
            key=lambda r: (
                ladder_rank.get((str(r.get("ticker", "")).strip(), direction_to_side(str(r.get("direction", "")))), 99),
                -(int(r.get("scenarioScore", 0) or 0)),
            )
        )
    for r in watch_rows:
        k = (str(r.get("ticker", "")).strip(), direction_to_side(str(r.get("direction", ""))))
        lb = ladder_label.get(k)
        if lb:
            r["watchLadder"] = lb
        else:
            r["watchLadder"] = bucket_none_ladder(r)
    rows = (trade_rows + watch_rows)[:max_posts]

    db = Path(args.db)
    conn = sqlite3.connect(db)
    try:
        posted = 0
        for idx, row in enumerate(rows, 1):
            if is_recent_duplicate(
                conn,
                channel_id=channel_id,
                ticker=str(row.get("ticker", "")),
                direction=str(row.get("direction", "")),
                scenario_tier=str(row.get("scenarioTier", "trade")),
                dedupe_hours=args.dedupe_hours,
            ):
                print(
                    f"skip_duplicate ticker={row.get('ticker','')} direction={row.get('direction','')} tier={row.get('scenarioTier','trade')}"
                )
                continue
            content = to_message(args.date, idx, row)
            if args.dry_run:
                print("----")
                print(content)
                continue
            resp = post_message(token, channel_id, content)
            message_id = str(resp.get("id", ""))
            if not message_id:
                continue
            upsert_scenario_message(
                conn,
                scenario_date=args.date,
                scenario_index=idx,
                channel_id=channel_id,
                message_id=message_id,
                row=row,
                source_path=str(src.relative_to(ROOT)),
            )
            posted += 1
        if not args.dry_run:
            conn.commit()
    finally:
        conn.close()

    print(
        "posted_scenarios={posted} trade={trade_count} watch={watch_count} watchCap={watch_cap} minTradePosts={min_trade} source={source} sourceDate={source_date} promoDate={promo_date}".format(
            posted=0 if args.dry_run else posted,
            trade_count=trade_count,
            watch_count=len(watch_rows),
            watch_cap=watch_cap,
            min_trade=int(args.min_trade_posts),
            source=src.relative_to(ROOT),
            source_date=src_date,
            promo_date=(promo_date or ""),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
