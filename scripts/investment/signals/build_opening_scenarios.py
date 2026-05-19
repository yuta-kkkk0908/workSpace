#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INBOX = ROOT / "topics" / "investment-research" / "inbox"
HEAD_RE = re.compile(r"^###\s+([^:]+):\s*(.+)$", re.M)
FIELD_RE = re.compile(r"^-\s+([A-Za-z0-9+_-]+):\s*(.*)$")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build opening trading scenarios from entry candidates")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--fallback-days", type=int, default=3)
    p.add_argument("--risk-per-trade-jpy", type=int, default=5000)
    p.add_argument("--max-candidates", type=int, default=6)
    p.add_argument("--min-long", type=int, default=2, help="minimum long scenarios for trade mode")
    p.add_argument("--min-short", type=int, default=2, help="minimum short scenarios for trade mode")
    p.add_argument("--min-rule-hits", type=int, default=5, help="minimum rule hit count for publish gate")
    p.add_argument("--min-score", type=int, default=70, help="minimum scenarioScore for publish gate")
    p.add_argument("--min-winrate", type=float, default=50.0, help="minimum estimated winrate for publish gate")
    p.add_argument("--allow-unknown-winrate", action="store_true", help="allow scenarios with unknown winrate (for testing/backfill phases)")
    p.add_argument("--auto-relax-gate", action="store_true", help="auto relax quality gate only when accepted scenarios are insufficient")
    p.add_argument("--auto-relax-steps", type=int, default=3, help="max relax attempts when auto-relax-gate is enabled")
    p.add_argument("--relax-min-rule-hits-floor", type=int, default=3, help="lower bound of min-rule-hits during auto relax")
    p.add_argument("--relax-min-score-floor", type=int, default=62, help="lower bound of min-score during auto relax")
    p.add_argument("--relax-min-winrate-floor", type=float, default=46.0, help="lower bound of min-winrate during auto relax")
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


def pick_horizon_by_wr(rule_ctx: dict) -> tuple[str, str, float | None]:
    wr1 = parse_wr(rule_ctx.get("t1", ""))
    wr5 = parse_wr(rule_ctx.get("t5", ""))
    wr20 = parse_wr(rule_ctx.get("t20", ""))
    cand = [("T+1", wr1), ("T+5", wr5), ("T+20", wr20)]
    cand = [(k, v) for k, v in cand if v is not None]
    if not cand:
        return ("T+1", "勝率目安データ不足", None)
    best = max(cand, key=lambda x: x[1])
    verdict = "50%超" if best[1] >= 50.0 else "50%未満"
    return (best[0], f"{best[0]}想定勝率={best[1]:.1f}%（{verdict}）", float(best[1]))


def scenario_score(row: dict, signal_meta: dict[str, str], rule_ctx: dict, rule_hits: int, winrate_value: float | None, board_available: bool) -> int:
    side = "long" if (row.get("expectedDirection", "") or "").startswith("up") else "short"
    rank = ((row.get("longSignalRank") if side == "long" else row.get("shortSignalRank")) or "").upper()
    score = 35
    score += min(rule_hits, 7) * 4
    if rank.startswith("A"):
        score += 16
    elif rank.startswith("B"):
        score += 10
    if (signal_meta.get("technicalSignalChecked", "") or "").lower() == "yes":
        score += 8
    if (signal_meta.get("externalContextChecked", "") or "").lower() == "yes":
        score += 6
    if (signal_meta.get("materialSignalChecked", "") or "").lower() == "yes":
        score += 6
    if (signal_meta.get("gateStatus", "") or "").lower() == "pass":
        score += 6
    if winrate_value is not None:
        score += max(-8, min(12, int((winrate_value - 50.0) / 2.0)))
    else:
        score -= 6
    st = (rule_ctx.get("status", "") or "").strip()
    if st == "active_rule":
        score += 8
    elif st == "watch_rule":
        score += 4
    elif st == "hypothesis_only":
        score -= 4
    src = (row.get("candidateSource", "primary") or "primary").strip()
    if src == "watch":
        score -= 3
    elif src == "supplemental":
        score -= 6
    if board_available:
        score += 3
    return max(0, min(100, int(score)))


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
        "candidateSource": "supplemental",
    }


def quality_hit_count(row: dict, signal_meta: dict[str, str]) -> int:
    hits = 0
    gate = (signal_meta.get("gateStatus") or "").lower() == "pass"
    material = (signal_meta.get("materialSignalChecked") or "").lower() == "yes"
    external = (signal_meta.get("externalContextChecked") or "").lower() == "yes"
    technical = (signal_meta.get("technicalSignalChecked") or "").lower() == "yes"
    if gate:
        hits += 1
    if material:
        hits += 1
    if external:
        hits += 1
    if technical:
        hits += 1
    side = "long" if (row.get("expectedDirection", "") or "").startswith("up") else "short"
    rank = (row.get("longSignalRank") if side == "long" else row.get("shortSignalRank")) or ""
    if rank.upper().startswith("A"):
        hits += 2
    elif rank.upper().startswith("B"):
        hits += 1
    return hits


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
    rule_hits = quality_hit_count(row, signal_meta)
    horizon_code, win_text, win_value = pick_horizon_by_wr(rule_ctx)
    score = scenario_score(row, signal_meta, rule_ctx, rule_hits, win_value, board_available)
    skip_conditions = [
        invalidation_text(direction),
        "寄り直後の出来高が細い/気配が飛ぶ場合は見送り",
        "前提材料の否定ニュースが出た場合は見送り",
    ]
    return {
        "signalId": row.get("signalId", ""),
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
        "ruleHitCount": rule_hits,
        "scenarioScore": score,
        "suggestedHorizon": horizon_code,
        "estimatedWinRate": win_text,
        "estimatedWinRateValue": win_value,
        "trigger": trigger,
        "skipConditions": skip_conditions,
        "rationale": rationale,
        "sourceUrl": row.get("url", ""),
        "candidateSource": row.get("candidateSource", "primary"),
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
    for r in long_rows:
        r["candidateSource"] = "primary"
    for r in short_rows:
        r["candidateSource"] = "primary"

    # 1) watch候補で補完
    long_watch = data.get("longWatchCandidates", []) or []
    short_watch = data.get("shortWatchCandidates", []) or []
    for r in long_watch:
        if len(long_rows) >= args.max_candidates:
            break
        sid = str(r.get("signalId", ""))
        if sid and sid not in {str(x.get("signalId", "")) for x in long_rows}:
            x = dict(r)
            x["candidateSource"] = "watch"
            long_rows.append(x)
    for r in short_watch:
        if len(short_rows) >= args.max_candidates:
            break
        sid = str(r.get("signalId", ""))
        if sid and sid not in {str(x.get("signalId", "")) for x in short_rows}:
            x = dict(r)
            x["candidateSource"] = "watch"
            short_rows.append(x)
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

    raw_scenarios = []
    for r in long_rows:
        raw_scenarios.append(
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
        raw_scenarios.append(
            scenario_for_row(
                r,
                "short",
                args.risk_per_trade_jpy,
                short_rule_ctx,
                signal_map.get(str(r.get("signalId", "")).strip(), {}),
                board_map.get(str(r.get("ticker", "")).strip()),
            )
        )

    def apply_quality_gate(min_rule_hits: int, min_score: int, min_winrate: float) -> tuple[list[dict], list[dict]]:
        accepted_local: list[dict] = []
        rejected_local: list[dict] = []
        for s in raw_scenarios:
            reasons: list[str] = []
            if int(s.get("ruleHitCount") or 0) < min_rule_hits:
                reasons.append(f"ruleHits<{min_rule_hits}")
            if int(s.get("scenarioScore") or 0) < min_score:
                reasons.append(f"score<{min_score}")
            wv = s.get("estimatedWinRateValue")
            if isinstance(wv, (int, float)):
                if float(wv) < float(min_winrate):
                    reasons.append(f"winRate<{min_winrate:.1f}%")
            else:
                if not args.allow_unknown_winrate:
                    reasons.append("winRate_unknown")
            if reasons:
                rejected_local.append(
                    {
                        "ticker": s.get("ticker", ""),
                        "company": s.get("company", ""),
                        "direction": s.get("direction", ""),
                        "scenarioScore": s.get("scenarioScore", 0),
                        "ruleHitCount": s.get("ruleHitCount", 0),
                        "estimatedWinRate": s.get("estimatedWinRate", ""),
                        "rejectReasons": reasons,
                    }
                )
            else:
                accepted_local.append(s)
        return accepted_local, rejected_local

    min_rule_hits_eff = args.min_rule_hits
    min_score_eff = args.min_score
    min_winrate_eff = float(args.min_winrate)
    relax_applied = False
    relax_rounds = 0
    relax_history: list[dict] = []

    accepted, rejected = apply_quality_gate(min_rule_hits_eff, min_score_eff, min_winrate_eff)
    need_total = int(args.min_long) + int(args.min_short)
    if args.auto_relax_gate and len(accepted) < need_total:
        step_rule_hits = 1
        step_score = 3
        step_winrate = 1.0
        for i in range(max(0, args.auto_relax_steps)):
            next_rule_hits = max(int(args.relax_min_rule_hits_floor), min_rule_hits_eff - step_rule_hits)
            next_score = max(int(args.relax_min_score_floor), min_score_eff - step_score)
            next_winrate = max(float(args.relax_min_winrate_floor), min_winrate_eff - step_winrate)
            if (
                next_rule_hits == min_rule_hits_eff
                and next_score == min_score_eff
                and abs(next_winrate - min_winrate_eff) < 1e-9
            ):
                break
            min_rule_hits_eff, min_score_eff, min_winrate_eff = next_rule_hits, next_score, next_winrate
            cand_acc, cand_rej = apply_quality_gate(min_rule_hits_eff, min_score_eff, min_winrate_eff)
            relax_history.append(
                {
                    "round": i + 1,
                    "minRuleHits": min_rule_hits_eff,
                    "minScore": min_score_eff,
                    "minWinRate": round(min_winrate_eff, 1),
                    "accepted": len(cand_acc),
                }
            )
            accepted, rejected = cand_acc, cand_rej
            relax_applied = True
            relax_rounds = i + 1
            if len(accepted) >= need_total:
                break

    scenarios = accepted

    # 3) 最低件数ガード
    plan_mode = "trade"
    plan_notes: list[str] = []
    accepted_long = sum(1 for x in scenarios if x.get("direction") == "long")
    accepted_short = sum(1 for x in scenarios if x.get("direction") == "short")
    if accepted_long < args.min_long or accepted_short < args.min_short:
        plan_mode = "watch_only"
        plan_notes.append(
            f"最低件数未達のため様子見優先（long={accepted_long}/{args.min_long}, short={accepted_short}/{args.min_short}）"
        )
        plan_notes.append("新規エントリーは見送り、監視継続と条件再確認を優先する。")
    if rejected:
        plan_notes.append(f"品質ゲート除外: {len(rejected)}件（score/ruleHits/winRate 条件未達）")
    if relax_applied:
        plan_notes.append(
            f"サンプル不足のため品質ゲートを段階緩和（rounds={relax_rounds}, effective: hits>={min_rule_hits_eff}, score>={min_score_eff}, winRate>={min_winrate_eff:.1f}%）"
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
        "planMode": plan_mode,
        "planNotes": plan_notes,
        "counts": {
            "long": accepted_long,
            "short": accepted_short,
            "minLong": args.min_long,
            "minShort": args.min_short,
            "rejected": len(rejected),
        },
        "qualityGate": {
            "minRuleHits": args.min_rule_hits,
            "minScore": args.min_score,
            "minWinRate": args.min_winrate,
            "effectiveMinRuleHits": min_rule_hits_eff,
            "effectiveMinScore": min_score_eff,
            "effectiveMinWinRate": round(min_winrate_eff, 1),
            "autoRelaxEnabled": bool(args.auto_relax_gate),
            "autoRelaxApplied": relax_applied,
            "autoRelaxRounds": relax_rounds,
            "autoRelaxHistory": relax_history,
        },
        "caution": "売買助言ではなく、寄り前シナリオ整理。板・気配・売建可否の人手確認が必須。",
        "scenarios": scenarios,
        "rejectedScenarios": rejected,
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
        f"- planMode: {plan_mode}",
        "- caution: 売買助言ではなく、寄り前シナリオ整理。板・気配・売建可否の人手確認が必須。",
        "",
        "## Scenarios",
    ]
    if plan_notes:
        lines.extend(["## Plan Notes", *[f"- {x}" for x in plan_notes], ""])
    if not scenarios:
        lines.append("- N/C")
    else:
        for i, s in enumerate(scenarios, 1):
            lines.extend(
                [
                    f"### {i}. {s['ticker']} {s['company']}",
                    f"- direction: {s['direction']}",
                    f"- scenarioScore: {s.get('scenarioScore',0)}",
                    f"- entryLimit: {s['entryLimitRule']}",
                    f"- takeProfit: {s['takeProfitRule']}",
                    f"- stopLoss: {s['stopLossRule']}",
                    f"- lot: {s['lotRule']}",
                    f"- ruleHits: {s.get('ruleHitCount',0)}",
                    f"- estimatedWinRate: {s.get('estimatedWinRate','')}",
                    f"- sourceType: {s.get('candidateSource','primary')}",
                    f"- rationale: {' / '.join(s['rationale'])}",
                    f"- invalidation: {s.get('invalidationCondition','')}",
                    f"- sourceUrl: {s['sourceUrl']}",
                    "",
                ]
            )
    lines.extend(["", "## Rejected (Quality Gate)"])
    if not rejected:
        lines.append("- none")
    else:
        for r in rejected:
            lines.append(
                f"- {r['ticker']} {r['company']} [{r['direction']}] score={r.get('scenarioScore',0)} hits={r.get('ruleHitCount',0)} reason={','.join(r.get('rejectReasons',[]))}"
            )

    out_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {out_md.relative_to(ROOT)} and {out_json.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
