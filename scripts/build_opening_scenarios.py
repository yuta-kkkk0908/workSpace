#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "topics" / "investment-research" / "inbox"
HEAD_RE = re.compile(r"^###\s+([^:]+):\s*(.+)$", re.M)
FIELD_RE = re.compile(r"^-\s+([A-Za-z0-9+_-]+):\s*(.*)$")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build opening trading scenarios from entry candidates")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--fallback-days", type=int, default=3)
    p.add_argument("--risk-per-trade-jpy", type=int, default=5000)
    p.add_argument("--max-candidates", type=int, default=6)
    return p.parse_args()


def find_entry_json(date_str: str, fallback_days: int) -> tuple[Path, str]:
    d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
    for i in range(0, max(0, fallback_days) + 1):
        d = (d0 - timedelta(days=i)).isoformat()
        p = INBOX / f"{d}-entry-candidates.json"
        if p.exists():
            return p, d
    raise SystemExit(f"entry-candidates not found for {date_str} (fallback_days={fallback_days})")


def find_board_snapshot(date_str: str, fallback_days: int) -> tuple[Path | None, str | None]:
    d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
    for i in range(0, max(0, fallback_days) + 1):
        d = (d0 - timedelta(days=i)).isoformat()
        p = INBOX / f"{d}-board-snapshot.json"
        if p.exists():
            return p, d
    return None, None


def find_rule_dashboard(date_str: str, fallback_days: int) -> tuple[Path | None, str | None]:
    d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
    for i in range(0, max(0, fallback_days) + 1):
        d = (d0 - timedelta(days=i)).isoformat()
        p = INBOX / f"{d}-rule-dashboard.json"
        if p.exists():
            return p, d
    return None, None


def find_market_signals(date_str: str, fallback_days: int) -> tuple[Path | None, str | None]:
    d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
    for i in range(0, max(0, fallback_days) + 1):
        d = (d0 - timedelta(days=i)).isoformat()
        p = INBOX / f"{d}-market-signals.md"
        if p.exists():
            return p, d
    return None, None


def fmt_price(v: float) -> str:
    return f"{int(round(v)):,}円"


def horizon_from_rank(rank: str) -> str:
    r = (rank or "").upper()
    if r.startswith("A"):
        return "T+5中心（T+1で一部利確、残りをT+5目線）"
    if r.startswith("B"):
        return "T+1〜T+3中心（デイトレ〜短期スイング）"
    return "T+1中心（短期限定）"


def invalidation_text(direction: str) -> str:
    if direction == "long":
        return "寄り後に下方向へ急変し、想定支持を割る場合は見送り/撤退"
    return "寄り後に上方向へ急変し、想定抵抗を超える場合は見送り/撤退"


def build_rule_context(rule_rows: list[dict], side: str) -> dict:
    rows = [r for r in rule_rows if r.get("side") == side]
    rows.sort(
        key=lambda r: (
            {"active_rule": 0, "watch_rule": 1, "hypothesis_only": 2}.get(r.get("status", ""), 9),
            -(int(r.get("appearances") or 0)),
        )
    )
    if not rows:
        return {"summary": "該当ルール統計なし", "status": "unknown"}
    top = rows[0]
    return {
        "summary": f"{top.get('bucket','')} / status={top.get('status','')} / n={top.get('appearances','')} / T+1 {top.get('t1','')} / T+5 {top.get('t5','')} / T+20 {top.get('t20','')}",
        "status": top.get("status", ""),
        "bucket": top.get("bucket", ""),
        "t1": top.get("t1", ""),
        "t5": top.get("t5", ""),
        "t20": top.get("t20", ""),
    }


def parse_signal_map(text: str) -> dict[str, dict[str, str]]:
    starts = [m.start() for m in HEAD_RE.finditer(text)]
    if not starts:
        return {}
    starts.append(len(text))
    out: dict[str, dict[str, str]] = {}
    for i in range(len(starts) - 1):
        chunk = text[starts[i] : starts[i + 1]]
        head = chunk.splitlines()[0]
        hm = HEAD_RE.match(head)
        if not hm:
            continue
        sid = hm.group(1).strip()
        d: dict[str, str] = {"title": hm.group(2).strip()}
        for line in chunk.splitlines()[1:]:
            fm = FIELD_RE.match(line.strip())
            if fm:
                d[fm.group(1)] = fm.group(2)
        out[sid] = d
    return out


def parse_wr(text: str) -> float | None:
    m = re.search(r"wr=([0-9]+(?:\.[0-9]+)?)%", text or "")
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def pick_horizon_by_wr(rule_ctx: dict) -> tuple[str, str]:
    wr1 = parse_wr(rule_ctx.get("t1", ""))
    wr5 = parse_wr(rule_ctx.get("t5", ""))
    wr20 = parse_wr(rule_ctx.get("t20", ""))
    cand = [("T+1", wr1), ("T+5", wr5), ("T+20", wr20)]
    cand = [(k, v) for k, v in cand if v is not None]
    if not cand:
        return ("T+1", "勝率目安データ不足")
    best = max(cand, key=lambda x: x[1])
    verdict = "50%超" if best[1] >= 50.0 else "50%未満"
    return best[0], f"{best[0]}想定勝率={best[1]:.1f}%（{verdict}）"


def as_entry_row(signal_id: str, meta: dict[str, str], side: str) -> dict[str, str] | None:
    exp = (meta.get("expectedDirection") or "").strip()
    if side == "long" and exp not in {"up", "up_watch"}:
        return None
    if side == "short" and exp not in {"down", "down_watch"}:
        return None
    gate = (meta.get("gateStatus") or "").strip().lower()
    material = (meta.get("materialSignalChecked") or "").strip().lower()
    external = (meta.get("externalContextChecked") or "").strip().lower()
    if not (gate == "pass" and material == "yes" and external == "yes"):
        return None
    rank_field = "longSignalRank" if side == "long" else "shortSignalRank"
    rank = (meta.get(rank_field) or "").strip()
    if rank not in {"A", "A-", "B", "B+"}:
        return None
    return {
        "signalId": signal_id,
        "ticker": meta.get("ticker", ""),
        "company": meta.get("company", ""),
        "expectedDirection": exp,
        "longSignalRank": meta.get("longSignalRank", ""),
        "shortSignalRank": meta.get("shortSignalRank", ""),
        "tradeUse": "supplemental_from_market_signals",
        "url": meta.get("url", ""),
    }


def scenario_for_row(
    row: dict, side: str, risk_jpy: int, rule_ctx: dict, signal_meta: dict[str, str], board: dict | None = None
) -> dict:
    ticker = row.get("ticker", "")
    company = row.get("company", "")
    rank = row.get("longSignalRank" if side == "long" else "shortSignalRank", row.get("rank", "C"))
    direction = "long" if side == "long" else "short"

    entry_price = None
    take_price = None
    stop_price = None
    board_available = bool(board)
    if board and direction == "long":
        base = board.get("bestAsk") or board.get("indicativeOpen") or board.get("bestBid")
        if isinstance(base, (int, float)) and base > 0:
            entry_price = float(base)
            take_price = entry_price * 1.012
            stop_price = entry_price * 0.994
    if board and direction == "short":
        base = board.get("bestBid") or board.get("indicativeOpen") or board.get("bestAsk")
        if isinstance(base, (int, float)) and base > 0:
            entry_price = float(base)
            take_price = entry_price * 0.988
            stop_price = entry_price * 1.006

    if entry_price and take_price and stop_price:
        entry_rule = f"{fmt_price(entry_price)}（板気配ベース）"
        take_rule = f"{fmt_price(take_price)}（第一利確）"
        stop_rule = f"{fmt_price(stop_price)}（損切）"
    else:
        if direction == "long":
            entry_rule = "寄り付き価格×0.998（押し待ち）"
            take_rule = "約定価格×1.012（第一利確）"
            stop_rule = "約定価格×0.994（損切）"
        else:
            entry_rule = "寄り付き価格×1.002（戻り待ち）"
            take_rule = "約定価格×0.988（第一利確）"
            stop_rule = "約定価格×1.006（損切）"

    lot_rule = f"1トレード許容損失 {risk_jpy}円 ÷ (エントリー価格 - 損切価格の絶対値)"
    rationale = [
        f"rank={rank}",
        f"expectedDirection={row.get('expectedDirection','')}",
        "source=entry-candidates + market-signals",
        f"boardSnapshot={'yes' if board_available else 'no'}",
    ]
    trigger = f"{signal_meta.get('signalType','')} / source={signal_meta.get('source','')} / session={signal_meta.get('session','')}"
    horizon_code, win_text = pick_horizon_by_wr(rule_ctx)
    skip_conditions = [
        invalidation_text(direction),
        "寄り直後の出来高が細い/気配が飛ぶ場合は見送り",
        "前提材料の否定ニュースが出た場合は見送り",
    ]
    return {
        "ticker": ticker,
        "company": company,
        "direction": direction,
        "entryLimitRule": entry_rule,
        "takeProfitRule": take_rule,
        "stopLossRule": stop_rule,
        "lotRule": lot_rule,
        "entryPrice": entry_price,
        "takeProfitPrice": take_price,
        "stopLossPrice": stop_price,
        "holdHorizon": horizon_from_rank(rank),
        "invalidationCondition": invalidation_text(direction),
        "ruleReproducibility": rule_ctx.get("summary", ""),
        "ruleStatus": rule_ctx.get("status", ""),
        "suggestedHorizon": horizon_code,
        "estimatedWinRate": win_text,
        "trigger": trigger,
        "skipConditions": skip_conditions,
        "rationale": rationale,
        "sourceUrl": row.get("url", ""),
    }


def main() -> int:
    args = parse_args()
    src, src_date = find_entry_json(args.date, args.fallback_days)
    data = json.loads(src.read_text(encoding="utf-8"))
    board_path, board_date = find_board_snapshot(args.date, args.fallback_days)
    rule_path, rule_date = find_rule_dashboard(args.date, args.fallback_days)
    signal_path, signal_date = find_market_signals(args.date, args.fallback_days)
    board_map: dict[str, dict] = {}
    if board_path:
        board_data = json.loads(board_path.read_text(encoding="utf-8"))
        for r in board_data.get("rows", []):
            board_map[str(r.get("ticker", "")).strip()] = r
    rule_rows: list[dict] = []
    if rule_path:
        rule_data = json.loads(rule_path.read_text(encoding="utf-8"))
        rule_rows = rule_data.get("rows", []) or []
    signal_map: dict[str, dict[str, str]] = {}
    if signal_path:
        signal_map = parse_signal_map(signal_path.read_text(encoding="utf-8"))
    long_rule_ctx = build_rule_context(rule_rows, "long")
    short_rule_ctx = build_rule_context(rule_rows, "short")

    long_rows = data.get("longEntryCandidates", [])[: args.max_candidates]
    short_rows = data.get("shortEntryCandidates", [])[: args.max_candidates]
    existing_long = {str(r.get("signalId", "")) for r in long_rows}
    existing_short = {str(r.get("signalId", "")) for r in short_rows}
    if len(long_rows) < args.max_candidates:
        for sid, meta in signal_map.items():
            if sid in existing_long:
                continue
            row = as_entry_row(sid, meta, "long")
            if row:
                long_rows.append(row)
                existing_long.add(sid)
            if len(long_rows) >= args.max_candidates:
                break
    if len(short_rows) < args.max_candidates:
        for sid, meta in signal_map.items():
            if sid in existing_short:
                continue
            row = as_entry_row(sid, meta, "short")
            if row:
                short_rows.append(row)
                existing_short.add(sid)
            if len(short_rows) >= args.max_candidates:
                break

    scenarios = []
    for r in long_rows:
        scenarios.append(
            scenario_for_row(
                r,
                "long",
                args.risk_per_trade_jpy,
                long_rule_ctx,
                signal_map.get(str(r.get("signalId", "")).strip(), {}),
                board_map.get(str(r.get("ticker", "")).strip()),
            )
        )
    for r in short_rows:
        scenarios.append(
            scenario_for_row(
                r,
                "short",
                args.risk_per_trade_jpy,
                short_rule_ctx,
                signal_map.get(str(r.get("signalId", "")).strip(), {}),
                board_map.get(str(r.get("ticker", "")).strip()),
            )
        )

    out = {
        "date": args.date,
        "sourceDate": src_date,
        "source": str(src.relative_to(ROOT)),
        "boardSnapshotDate": board_date or "",
        "boardSnapshotSource": str(board_path.relative_to(ROOT)) if board_path else "",
        "ruleDashboardDate": rule_date or "",
        "ruleDashboardSource": str(rule_path.relative_to(ROOT)) if rule_path else "",
        "signalSourceDate": signal_date or "",
        "signalSourcePath": str(signal_path.relative_to(ROOT)) if signal_path else "",
        "riskPerTradeJpy": args.risk_per_trade_jpy,
        "caution": "売買助言ではなく、寄り前シナリオ整理。板・気配・売建可否の人手確認が必須。",
        "scenarios": scenarios,
    }

    out_json = INBOX / f"{args.date}-opening-scenarios.json"
    out_md = INBOX / f"{args.date}-opening-scenarios.md"
    out_json.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# {args.date} Opening Scenarios",
        "",
        f"- sourceDate: {src_date}",
        f"- source: {src.relative_to(ROOT)}",
        f"- riskPerTradeJpy: {args.risk_per_trade_jpy}",
        "- caution: 売買助言ではなく、寄り前シナリオ整理。板・気配・売建可否の人手確認が必須。",
        "",
        "## Scenarios",
    ]
    if not scenarios:
        lines.append("- N/C")
    else:
        for i, s in enumerate(scenarios, 1):
            lines.extend(
                [
                    f"### {i}. {s['ticker']} {s['company']}",
                    f"- direction: {s['direction']}",
                    f"- entryLimit: {s['entryLimitRule']}",
                    f"- takeProfit: {s['takeProfitRule']}",
                    f"- stopLoss: {s['stopLossRule']}",
                    f"- lot: {s['lotRule']}",
                    f"- rationale: {' / '.join(s['rationale'])}",
                    f"- sourceUrl: {s['sourceUrl']}",
                    "",
                ]
            )

    out_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {out_md.relative_to(ROOT)} and {out_json.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
