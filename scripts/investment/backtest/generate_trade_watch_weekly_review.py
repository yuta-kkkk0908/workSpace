#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"
OUT = ROOT / "topics" / "investment-research" / "inbox"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate weekly trade/watch review snapshot")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--out-date", required=True)
    p.add_argument("--start-date")
    p.add_argument("--end-date")
    p.add_argument("--promotion-file", help="optional watch-promotion markdown file path")
    return p.parse_args()


def wr(vals: list[float]) -> float:
    return (sum(1 for v in vals if v > 0) / len(vals) * 100.0) if vals else 0.0


def avg(vals: list[float]) -> float:
    return (sum(vals) / len(vals)) if vals else 0.0


def summarize(rows: list[sqlite3.Row]) -> dict:
    t1 = [float(r["t1_return_pct"]) for r in rows if r["t1_return_pct"] is not None]
    t5 = [float(r["t5_return_pct"]) for r in rows if r["t5_return_pct"] is not None]
    t20 = [float(r["t20_return_pct"]) for r in rows if r["t20_return_pct"] is not None]
    return {
        "samples": len(rows),
        "t1_n": len(t1),
        "t1_wr": wr(t1),
        "t1_avg": avg(t1),
        "t5_n": len(t5),
        "t5_wr": wr(t5),
        "t5_avg": avg(t5),
        "t20_n": len(t20),
        "t20_wr": wr(t20),
        "t20_avg": avg(t20),
    }


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        where = ["1=1"]
        params: list[object] = []
        if args.start_date:
            where.append("entry_date>=?")
            params.append(args.start_date)
        if args.end_date:
            where.append("entry_date<=?")
            params.append(args.end_date)
        rows = conn.execute(
            """
            select mode,entry_date,ticker,company,side,t1_return_pct,t5_return_pct,t20_return_pct
            from paper_trades
            where """
            + " and ".join(where)
            + " order by entry_date,ticker",
            params,
        ).fetchall()

        # Scenario operations throughput (for bot-ops health).
        scen_where = ["1=1"]
        scen_params: list[object] = []
        if args.start_date:
            scen_where.append("scenario_date>=?")
            scen_params.append(args.start_date)
        if args.end_date:
            scen_where.append("scenario_date<=?")
            scen_params.append(args.end_date)
        scenario_rows = conn.execute(
            """
            select message_id,scenario_tier,watch_ladder
            from scenario_messages
            where """
            + " and ".join(scen_where),
            scen_params,
        ).fetchall()

        reply_rows = conn.execute(
            """
            select command, parent_message_id, parsed_json
            from scenario_reply_events
            """,
        ).fetchall()

        trade_by_id_rows = conn.execute(
            """
            select trade_id, t5_return_pct
            from paper_trades
            where trade_id is not null
            """,
        ).fetchall()
    finally:
        conn.close()

    trade_rows = [r for r in rows if r["mode"] == "live"]
    watch_rows = [r for r in rows if r["mode"] == "watch"]
    all_rows = [r for r in rows if r["mode"] in ("live", "watch", "backtest")]

    trade = summarize(trade_rows)
    watch = summarize(watch_rows)
    total = summarize(all_rows)
    t5_wr_gap = trade["t5_wr"] - watch["t5_wr"]
    t5_avg_gap = trade["t5_avg"] - watch["t5_avg"]

    # Simple uncertainty proxy (sample-size caution)
    caution = []
    if trade["t5_n"] < 20:
        caution.append(f"trade T+5 sample不足 n={trade['t5_n']}")
    if watch["t5_n"] < 20:
        caution.append(f"watch T+5 sample不足 n={watch['t5_n']}")

    if t5_wr_gap >= 8.0:
        verdict = "trade優位（watch→trade昇格の候補抽出を強める）"
    elif t5_wr_gap <= -8.0:
        verdict = "watch優位（trade条件が厳しすぎる可能性）"
    else:
        verdict = "拮抗（現行ルール維持でサンプル追加）"

    scenario_ids = {str(r["message_id"]) for r in scenario_rows}
    trade_posts = sum(1 for r in scenario_rows if str(r["scenario_tier"] or "trade") == "trade")
    watch_posts = sum(1 for r in scenario_rows if str(r["scenario_tier"] or "") == "watch")
    entry_replies = 0
    exit_replies = 0
    cancel_replies = 0
    for r in reply_rows:
        parent = str(r["parent_message_id"] or "")
        if parent not in scenario_ids:
            continue
        cmd = str(r["command"] or "").strip().lower()
        if cmd == "entry":
            entry_replies += 1
        elif cmd == "exit":
            exit_replies += 1
        elif cmd == "cancel":
            cancel_replies += 1
    total_posts = trade_posts + watch_posts
    entry_rate = (entry_replies / total_posts * 100.0) if total_posts > 0 else 0.0

    # Ladder effectiveness snapshot (watch only)
    watch_msg_ladder: dict[str, str] = {}
    for r in scenario_rows:
        if str(r["scenario_tier"] or "") != "watch":
            continue
        mid = str(r["message_id"] or "")
        if not mid:
            continue
        ladder = str(r["watch_ladder"] or "").strip().lower() or "none-low-score"
        if ladder == "none":
            ladder = "none-low-score"
        watch_msg_ladder[mid] = ladder

    t5_by_trade_id = {str(r["trade_id"]): r["t5_return_pct"] for r in trade_by_id_rows if r["trade_id"] is not None}
    ladder_posts: dict[str, int] = {"strict": 0, "balanced": 0, "early": 0, "none-high-score": 0, "none-low-score": 0}
    ladder_entries: dict[str, int] = {"strict": 0, "balanced": 0, "early": 0, "none-high-score": 0, "none-low-score": 0}
    ladder_t5_vals: dict[str, list[float]] = {"strict": [], "balanced": [], "early": [], "none-high-score": [], "none-low-score": []}

    for lb in watch_msg_ladder.values():
        ladder_posts[lb if lb in ladder_posts else "none-low-score"] += 1

    for r in reply_rows:
        if str(r["command"] or "").lower() != "entry":
            continue
        parent = str(r["parent_message_id"] or "")
        if parent not in watch_msg_ladder:
            continue
        lb = watch_msg_ladder[parent]
        raw = str(r["parsed_json"] or "").strip()
        trade_id = ""
        if raw:
            try:
                pj = json.loads(raw)
                trade_id = str((pj or {}).get("trade_id") or "")
            except Exception:
                trade_id = ""
        ladder_entries[lb] += 1
        if trade_id:
            v = t5_by_trade_id.get(trade_id)
            if v is not None:
                try:
                    ladder_t5_vals[lb].append(float(v))
                except Exception:
                    pass

    next_actions: list[str] = []
    # 1) trade運用の強弱
    if trade["t5_n"] < 10:
        next_actions.append("trade母数が薄い。次週はロット固定で検証優先（拡大しない）。")
    elif trade["t5_wr"] < 50.0:
        next_actions.append("trade T+5勝率が50%未満。エントリーを絞り、見送り条件を厳格化する。")
    else:
        next_actions.append("trade側は現行維持。勝率が維持できるかを週次で再確認する。")

    # 2) watch->trade昇格方針
    if watch["t5_n"] < 10:
        next_actions.append("watch母数を優先して積む。昇格判定は急がず、まずサンプル確保を継続する。")
    elif t5_wr_gap <= -8.0:
        next_actions.append("watch優位。昇格しきい値（min_samples/min_winrate）を段階緩和して候補を増やす。")
    else:
        next_actions.append("watch候補は現行しきい値で継続。週次で昇格候補を再判定する。")

    # 3) horizon/exit側の改善方針
    if trade["t1_n"] > 0 and trade["t5_n"] > 0 and trade["t1_wr"] >= trade["t5_wr"] + 8.0:
        next_actions.append("T+1優位。利確の前倒し（部分利確）を増やし、T+5持ち越しを抑制する。")
    elif trade["t20_n"] > 0 and trade["t20_wr"] >= trade["t5_wr"] + 8.0:
        next_actions.append("T+20優位。強い材料のみホールド延長する条件を試験導入する。")
    else:
        next_actions.append("exit設計は現行維持。T+1/T+5/T+20の差分が明確化するまでデータ蓄積を継続する。")

    out = OUT / f"{args.out_date}-weekly-trade-watch-review.md"
    lines = [
        f"# {args.out_date} Weekly Trade/Watch Review",
        "",
        "- caution: 仮想トレード検証の集計。売買助言ではない。",
        f"- period: {args.start_date or 'N/A'} .. {args.end_date or 'N/A'}",
        "",
        "## Scenario Ops Throughput",
        f"- posts: total={total_posts} (trade={trade_posts}, watch={watch_posts})",
        f"- replies: entry={entry_replies}, exit={exit_replies}, cancel={cancel_replies}",
        f"- entry conversion: {entry_rate:.1f}%",
        "",
        "## Ladder Effectiveness (Watch)",
        f"- strict: posts={ladder_posts['strict']} entries={ladder_entries['strict']} entryRate={(ladder_entries['strict']/ladder_posts['strict']*100.0 if ladder_posts['strict'] else 0.0):.1f}% / T+5 n={len(ladder_t5_vals['strict'])} wr={wr(ladder_t5_vals['strict']):.1f}% avgRet={avg(ladder_t5_vals['strict']):.2f}%",
        f"- balanced: posts={ladder_posts['balanced']} entries={ladder_entries['balanced']} entryRate={(ladder_entries['balanced']/ladder_posts['balanced']*100.0 if ladder_posts['balanced'] else 0.0):.1f}% / T+5 n={len(ladder_t5_vals['balanced'])} wr={wr(ladder_t5_vals['balanced']):.1f}% avgRet={avg(ladder_t5_vals['balanced']):.2f}%",
        f"- early: posts={ladder_posts['early']} entries={ladder_entries['early']} entryRate={(ladder_entries['early']/ladder_posts['early']*100.0 if ladder_posts['early'] else 0.0):.1f}% / T+5 n={len(ladder_t5_vals['early'])} wr={wr(ladder_t5_vals['early']):.1f}% avgRet={avg(ladder_t5_vals['early']):.2f}%",
        f"- none-high-score: posts={ladder_posts['none-high-score']} entries={ladder_entries['none-high-score']} entryRate={(ladder_entries['none-high-score']/ladder_posts['none-high-score']*100.0 if ladder_posts['none-high-score'] else 0.0):.1f}% / T+5 n={len(ladder_t5_vals['none-high-score'])} wr={wr(ladder_t5_vals['none-high-score']):.1f}% avgRet={avg(ladder_t5_vals['none-high-score']):.2f}%",
        f"- none-low-score: posts={ladder_posts['none-low-score']} entries={ladder_entries['none-low-score']} entryRate={(ladder_entries['none-low-score']/ladder_posts['none-low-score']*100.0 if ladder_posts['none-low-score'] else 0.0):.1f}% / T+5 n={len(ladder_t5_vals['none-low-score'])} wr={wr(ladder_t5_vals['none-low-score']):.1f}% avgRet={avg(ladder_t5_vals['none-low-score']):.2f}%",
        "",
        "## Mode Summary (T+5中心)",
        f"- trade(live): samples={trade['samples']} / T+5 n={trade['t5_n']} wr={trade['t5_wr']:.1f}% avgRet={trade['t5_avg']:.2f}%",
        f"- watch: samples={watch['samples']} / T+5 n={watch['t5_n']} wr={watch['t5_wr']:.1f}% avgRet={watch['t5_avg']:.2f}%",
        f"- gap(trade-watch): wr={t5_wr_gap:+.1f}pt / avgRet={t5_avg_gap:+.2f}%",
        f"- verdict: {verdict}",
        "",
        "## Horizons",
        f"- trade T+1/T+5/T+20: {trade['t1_wr']:.1f}% / {trade['t5_wr']:.1f}% / {trade['t20_wr']:.1f}%",
        f"- watch T+1/T+5/T+20: {watch['t1_wr']:.1f}% / {watch['t5_wr']:.1f}% / {watch['t20_wr']:.1f}%",
        f"- all samples: {total['samples']}",
        "",
        "## Uncertainty / Notes",
    ]
    if caution:
        for c in caution:
            lines.append(f"- {c}")
    else:
        lines.append("- サンプルサイズ警告なし")
    lines.extend(
        [
            "",
            "## Next Week Actions (Auto)",
            f"- 1) {next_actions[0]}",
            f"- 2) {next_actions[1]}",
            f"- 3) {next_actions[2]}",
            "",
            "## Operation Notes",
            "- trade側: T+5勝率が50%未満ならサイズ縮小 or 見送りを優先",
            "- watch側: 閾値未達でも一定サンプルまでは継続観測",
            "- 週次で昇格候補を再判定し、翌週のシナリオ閾値に反映",
            "",
            "## Promotion Link",
            f"- see: {args.promotion_file or f'{args.out_date}-watch-promotion-candidates.md'}",
        ]
    )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
