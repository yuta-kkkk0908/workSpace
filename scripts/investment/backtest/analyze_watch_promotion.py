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
    p = argparse.ArgumentParser(description="Analyze watch->trade promotion candidates from paper_trades")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--start-date")
    p.add_argument("--end-date")
    p.add_argument("--out-date", required=True)
    p.add_argument("--min-samples", type=int, default=3)
    p.add_argument("--min-winrate", type=float, default=55.0)
    p.add_argument("--min-avg-ret", type=float, default=0.2)
    p.add_argument("--warn-samples", type=int, default=2, help="near-threshold warning sample count")
    p.add_argument(
        "--ladder",
        action="store_true",
        help="also evaluate early/balanced/strict promotion ladders in addition to base thresholds",
    )
    return p.parse_args()


def win_rate(vals: list[float]) -> float:
    return (sum(1 for v in vals if v > 0) / len(vals) * 100.0) if vals else 0.0


def avg(vals: list[float]) -> float:
    return (sum(vals) / len(vals)) if vals else 0.0


def pick_by_threshold(rows: list[dict], *, min_samples: int, min_wr: float, min_ret: float) -> list[dict]:
    out = []
    for r in rows:
        if int(r.get("samples", 0)) < int(min_samples):
            continue
        if float(r.get("t5_win_rate", 0.0)) < float(min_wr):
            continue
        if float(r.get("t5_avg_ret", 0.0)) < float(min_ret):
            continue
        out.append(r)
    out.sort(key=lambda x: (x["t5_win_rate"], x["t5_avg_ret"], x["samples"]), reverse=True)
    return out


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        where = ["mode='watch'"]
        params: list[object] = []
        if args.start_date:
            where.append("entry_date>=?")
            params.append(args.start_date)
        if args.end_date:
            where.append("entry_date<=?")
            params.append(args.end_date)
        rows = conn.execute(
            """
            select ticker,company,side,signal_id,t1_return_pct,t5_return_pct,t20_return_pct
            from paper_trades
            where """
            + " and ".join(where)
            + " order by ticker,entry_date",
            params,
        ).fetchall()
    finally:
        conn.close()

    groups: dict[tuple[str, str, str], list[sqlite3.Row]] = {}
    for r in rows:
        key = (r["ticker"], r["company"], r["side"])
        groups.setdefault(key, []).append(r)

    candidates: list[dict] = []
    near_candidates: list[dict] = []
    scored_rows: list[dict] = []
    for (ticker, company, side), items in groups.items():
        t5_vals = [float(x["t5_return_pct"]) for x in items if x["t5_return_pct"] is not None]
        n = len(t5_vals)
        wr = win_rate(t5_vals) if t5_vals else 0.0
        ar = avg(t5_vals) if t5_vals else 0.0
        if n < args.min_samples:
            if n >= max(1, args.warn_samples):
                near_candidates.append(
                    {
                        "ticker": ticker,
                        "company": company,
                        "side": side,
                        "samples": n,
                        "t5_win_rate": round(wr, 1),
                        "t5_avg_ret": round(ar, 3),
                        "reason": f"samples不足({n}<{args.min_samples})",
                        "signal_ids": sorted({str(x["signal_id"] or "") for x in items if x["signal_id"]}),
                    }
                )
            continue
        row = {
            "ticker": ticker,
            "company": company,
            "side": side,
            "samples": n,
            "t5_win_rate": round(wr, 1),
            "t5_avg_ret": round(ar, 3),
            "signal_ids": sorted({str(x["signal_id"] or "") for x in items if x["signal_id"]}),
        }
        scored_rows.append(row)
        if wr >= args.min_winrate and ar >= args.min_avg_ret:
            candidates.append(row)
        else:
            near_candidates.append(
                {
                    "ticker": ticker,
                    "company": company,
                    "side": side,
                    "samples": n,
                    "t5_win_rate": round(wr, 1),
                    "t5_avg_ret": round(ar, 3),
                    "reason": "閾値未達(wr/avgRet)",
                    "signal_ids": sorted({str(x["signal_id"] or "") for x in items if x["signal_id"]}),
                }
            )

    candidates.sort(key=lambda x: (x["t5_win_rate"], x["t5_avg_ret"], x["samples"]), reverse=True)
    near_candidates.sort(key=lambda x: (x["samples"], x["t5_win_rate"], x["t5_avg_ret"]), reverse=True)

    out = OUT / f"{args.out_date}-watch-promotion-candidates.md"
    out_json = OUT / f"{args.out_date}-watch-promotion-candidates.json"
    lines = [
        f"# {args.out_date} Watch Promotion Candidates",
        "",
        "- caution: 検証用 watch データの昇格候補。売買助言ではない。",
        f"- thresholds: min_samples={args.min_samples}, min_t5_winRate={args.min_winrate}%, min_t5_avgRet={args.min_avg_ret}%",
        f"- watch_rows: {len(rows)}",
        f"- promotion_candidates: {len(candidates)}",
        f"- near_candidates: {len(near_candidates)}",
        "",
        "## Promotion Rule (Tentative)",
        "- T+5を基準に評価する",
        "- samples >= min_samples",
        "- winRate >= min_t5_winRate",
        "- avgRet >= min_t5_avgRet",
        "- 上記を満たすまでは watch 継続（いきなり trade 昇格しない）",
        "",
        "## Candidates",
    ]
    if not candidates:
        lines.append("- none")
    else:
        for c in candidates:
            lines.extend(
                [
                    f"### {c['ticker']} {c['company']} [{c['side']}]",
                    f"- samples: {c['samples']}",
                    f"- T+5 winRate: {c['t5_win_rate']}%",
                    f"- T+5 avgRet: {c['t5_avg_ret']}%",
                    f"- signalIds: {', '.join(c['signal_ids']) if c['signal_ids'] else 'none'}",
                    "",
                ]
            )
    lines.append("")
    lines.append("## Near / Keep Watch")
    if not near_candidates:
        lines.append("- none")
    else:
        for c in near_candidates[:20]:
            lines.extend(
                [
                    f"- {c['ticker']} {c['company']} [{c['side']}] n={c['samples']} T+5 wr={c['t5_win_rate']}% avgRet={c['t5_avg_ret']}% / {c['reason']}",
                ]
            )
        if len(near_candidates) > 20:
            lines.append(f"- ...(省略) total={len(near_candidates)}")

    ladder_payload: dict[str, object] = {}
    if args.ladder:
        early = pick_by_threshold(scored_rows, min_samples=2, min_wr=52.0, min_ret=0.10)
        balanced = pick_by_threshold(scored_rows, min_samples=3, min_wr=55.0, min_ret=0.20)
        strict = pick_by_threshold(scored_rows, min_samples=5, min_wr=58.0, min_ret=0.30)
        ladder_payload = {
            "early": early,
            "balanced": balanced,
            "strict": strict,
            "thresholds": {
                "early": {"min_samples": 2, "min_winrate": 52.0, "min_avg_ret": 0.10},
                "balanced": {"min_samples": 3, "min_winrate": 55.0, "min_avg_ret": 0.20},
                "strict": {"min_samples": 5, "min_winrate": 58.0, "min_avg_ret": 0.30},
            },
        }
        lines.extend(
            [
                "",
                "## Promotion Ladder (Auto)",
                "- early: n>=2 / wr>=52% / avgRet>=0.10%",
                f"- early_count: {len(early)}",
                "- balanced: n>=3 / wr>=55% / avgRet>=0.20%",
                f"- balanced_count: {len(balanced)}",
                "- strict: n>=5 / wr>=58% / avgRet>=0.30%",
                f"- strict_count: {len(strict)}",
                "",
                "### Ladder Top Picks",
            ]
        )
        for label, group in (("early", early), ("balanced", balanced), ("strict", strict)):
            if not group:
                lines.append(f"- {label}: none")
                continue
            top = group[0]
            lines.append(
                f"- {label}: {top['ticker']} {top['company']} [{top['side']}] n={top['samples']} wr={top['t5_win_rate']}% avgRet={top['t5_avg_ret']}%"
            )
    out.write_text("\n".join(lines), encoding="utf-8")
    payload = {
        "date": args.out_date,
        "watch_rows": len(rows),
        "thresholds": {
            "base": {"min_samples": args.min_samples, "min_winrate": args.min_winrate, "min_avg_ret": args.min_avg_ret}
        },
        "candidates": candidates,
        "near_candidates": near_candidates,
        "ladder": ladder_payload,
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
    print(f"wrote {out_json.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
