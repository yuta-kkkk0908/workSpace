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
    p = argparse.ArgumentParser(description="Report RULE_THIN diagnostics from scenario_gate_diagnostics")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    return p.parse_args()


def parse_reasons(raw: str) -> list[str]:
    s = (raw or "").strip()
    if not s:
        return []
    try:
        x = json.loads(s)
        if isinstance(x, list):
            return [str(v) for v in x]
    except Exception:
        pass
    return [s]


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT signal_id,ticker,direction,candidate_source,scenario_tier,scenario_score,rule_hit_count,
                   estimated_winrate_value,gate_result,reject_reasons_json,gate_thresholds_json
            FROM scenario_gate_diagnostics
            WHERE scenario_date=?
            ORDER BY gate_result,ticker,direction
            """,
            (args.date,),
        ).fetchall()
    finally:
        conn.close()

    accepted = [dict(r) for r in rows if (r["gate_result"] or "") == "accepted"]
    rejected = [dict(r) for r in rows if (r["gate_result"] or "") == "rejected"]

    reason_counts: dict[str, int] = {}
    credit_breakdown = {
        "manual_non_marginable": 0,
        "auto_regulation_hit": 0,
        "auto_unknown": 0,
        "other_credit_block": 0,
    }
    for r in rejected:
        rs = parse_reasons(r.get("reject_reasons_json") or "")
        if not rs:
            reason_counts["(none)"] = reason_counts.get("(none)", 0) + 1
            continue
        for x in rs:
            reason_counts[x] = reason_counts.get(x, 0) + 1
            if x.startswith("credit_unavailable:"):
                low = x.lower()
                if "manual_non_marginable" in low:
                    credit_breakdown["manual_non_marginable"] += 1
                elif "auto_non_marginable" in low:
                    # auto_non_marginable can mean regulation hit or explicit ng.
                    # source_detail parsing is not joined here, so keep as regulation-hit bucket by policy.
                    credit_breakdown["auto_regulation_hit"] += 1
                elif "auto_unknown" in low or "unknown" in low:
                    credit_breakdown["auto_unknown"] += 1
                else:
                    credit_breakdown["other_credit_block"] += 1

    # Simulate simple one-step relax impact on rejected rows.
    # ルール: ruleHits +1, score +5, winRate +2.0 の範囲で閾値未達を再判定
    salvage = {
        "ruleHits_plus1": 0,
        "score_plus5": 0,
        "winRate_plus2": 0,
    }
    for r in rejected:
        reasons = parse_reasons(r.get("reject_reasons_json") or "")
        if any(x.startswith("ruleHits<") for x in reasons):
            hit = int(r.get("rule_hit_count") or 0)
            # しきい値文字列の最小値を取得
            ths = []
            for x in reasons:
                if x.startswith("ruleHits<"):
                    try:
                        ths.append(int(x.split("<", 1)[1]))
                    except Exception:
                        pass
            if ths and (hit + 1) >= min(ths):
                salvage["ruleHits_plus1"] += 1
        if any(x.startswith("score<") for x in reasons):
            sc = int(r.get("scenario_score") or 0)
            ths = []
            for x in reasons:
                if x.startswith("score<"):
                    try:
                        ths.append(int(x.split("<", 1)[1]))
                    except Exception:
                        pass
            if ths and (sc + 5) >= min(ths):
                salvage["score_plus5"] += 1
        if any(x.startswith("winRate<") for x in reasons):
            wr = r.get("estimated_winrate_value")
            if wr is None:
                continue
            w = float(wr)
            ths = []
            for x in reasons:
                if x.startswith("winRate<"):
                    try:
                        ths.append(float(x.split("<", 1)[1].replace("%", "")))
                    except Exception:
                        pass
            if ths and (w + 2.0) >= min(ths):
                salvage["winRate_plus2"] += 1

    payload = {
        "date": args.date,
        "acceptedCount": len(accepted),
        "rejectedCount": len(rejected),
        "rejectReasonCounts": dict(sorted(reason_counts.items(), key=lambda x: (-x[1], x[0]))),
        "creditBlockBreakdown": credit_breakdown,
        "oneStepRelaxImpact": salvage,
    }

    if args.write_files:
        out_json = OUT / f"{args.date}-rule-thin-diagnostics.json"
        out_md = OUT / f"{args.date}-rule-thin-diagnostics.md"
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        lines = [
            f"# {args.date} RULE_THIN Diagnostics",
            "",
            f"- accepted: {payload['acceptedCount']}",
            f"- rejected: {payload['rejectedCount']}",
            "",
            "## Rejection Reasons",
        ]
        if not payload["rejectReasonCounts"]:
            lines.append("- none")
        else:
            for k, v in payload["rejectReasonCounts"].items():
                lines.append(f"- {k}: {v}")
        lines.extend(
            [
                "",
                "## Credit Block Breakdown",
                f"- manual_non_marginable: {credit_breakdown['manual_non_marginable']}",
                f"- auto_regulation_hit: {credit_breakdown['auto_regulation_hit']}",
                f"- auto_unknown: {credit_breakdown['auto_unknown']}",
                f"- other_credit_block: {credit_breakdown['other_credit_block']}",
                "",
                "## One-step Relax Impact (simulated)",
                f"- ruleHits +1 で救済見込み: {salvage['ruleHits_plus1']}",
                f"- score +5 で救済見込み: {salvage['score_plus5']}",
                f"- winRate +2pt で救済見込み: {salvage['winRate_plus2']}",
            ]
        )
        out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {out_md.relative_to(ROOT)}")
        print(f"wrote {out_json.relative_to(ROOT)}")

    print(
        "rule_thin_report date={0} accepted={1} rejected={2} top_reason={3}".format(
            args.date,
            payload["acceptedCount"],
            payload["rejectedCount"],
            next(iter(payload["rejectReasonCounts"].keys()), "none"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
