#!/usr/bin/env python3
"""Create a focused memo for high-readiness short candidates."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
DEFAULT_READINESS = ROOT / "topics/investment-research/inbox/{date}-short-readiness-data.json"
DEFAULT_OUTPUT_MD = ROOT / "topics/investment-research/inbox/{date}-short-high-readiness-review.md"
DEFAULT_OUTPUT_JSON = ROOT / "topics/investment-research/inbox/{date}-short-high-readiness-review-data.json"


def pct_label(row: dict, key: str) -> str:
    value = row.get(key)
    if value is None:
        return "unknown"
    try:
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError):
        return str(value)


def derive_lesson(row: dict) -> list[str]:
    lessons = []
    reasons = set(row.get("shortReadinessReasons", []))
    if "jpx_loan_margin_current" in reasons:
        lessons.append("JPX貸借銘柄で、制度信用売りの候補にできる余地がある")
    if "volume_confirmed" in reasons:
        lessons.append("出来高確認があり、単なる薄商いの下落ではない")
    if "technical_support" in reasons:
        lessons.append("弱いテクニカルが材料下落を補強している")
    if "borrow_check_required" in reasons:
        lessons.append("JPX貸借でも当日の売り禁・逆日歩・証券会社在庫確認が必要")
    if row.get("liquidityBucket") == "high":
        lessons.append("流動性は高く、監視対象として扱いやすい")
    elif row.get("liquidityBucket") == "medium":
        lessons.append("流動性は中程度で、板とスプレッド確認が必要")
    if row.get("t20") == "pending":
        lessons.append("T+20は未確定なので、中期継続性はまだ判断しない")
    elif row.get("t20") == "win":
        lessons.append("T+20まで下落方向が継続した実績がある")
    return lessons


def main() -> int:
    parser = argparse.ArgumentParser(description="Create high-readiness short review.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    parser.add_argument("--output-json", type=Path, default=None)
    args = parser.parse_args()

    input_path = args.input or Path(str(DEFAULT_READINESS).format(date=args.date))
    output_md = args.output_md or Path(str(DEFAULT_OUTPUT_MD).format(date=args.date))
    output_json = args.output_json or Path(str(DEFAULT_OUTPUT_JSON).format(date=args.date))

    rows = json.loads(input_path.read_text(encoding="utf-8"))["rows"]
    high = [r for r in rows if r.get("shortReadiness") == "high"]
    medium = [r for r in rows if r.get("shortReadiness") == "medium"]
    reason_counts = Counter(reason for row in high for reason in row.get("shortReadinessReasons", []))
    payload = {
        "createdAt": datetime.now(JST).replace(microsecond=0).isoformat(),
        "mode": "short-high-readiness-review",
        "highCount": len(high),
        "mediumCount": len(medium),
        "reasonCounts": dict(reason_counts),
        "rows": [
            {
                "ticker": r.get("ticker"),
                "signalDate": r.get("signalDate"),
                "category": r.get("category"),
                "signalType": r.get("signalType"),
                "expected": r.get("expected"),
                "shortRank": r.get("shortRank"),
                "shortUseCase": r.get("shortUseCase"),
                "shortReadiness": r.get("shortReadiness"),
                "borrowStatus": r.get("borrow_borrowStatus"),
                "liquidityBucket": r.get("liquidityBucket"),
                "avgTurnoverYen": r.get("avgTurnoverYen"),
                "technicalPattern": r.get("technicalPattern"),
                "t1Candle": r.get("t1Candle"),
                "volumeRatioBucket": r.get("volumeRatioBucket"),
                "marketContext": r.get("marketContext"),
                "sectorMarketContext": r.get("sectorMarketContext"),
                "t1": r.get("t1"),
                "t5": r.get("t5"),
                "t20": r.get("t20"),
                "lessons": derive_lesson(r),
            }
            for r in high
        ],
    }
    payload["date"] = args.date
    output_source = input_path.relative_to(ROOT / "topics/investment-research")
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        f"# {args.date} Short High Readiness Review",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {args.date}",
        "- mode: short-high-readiness-review",
        f"- sourceLog: {output_source}",
        "- caution: 過去データの研究メモ。売買助言ではない。実運用前に当日の売建可否、逆日歩、売り禁、板、寄り付き後の反応を確認する。",
        "",
        "## Summary",
        f"- highReadinessCount: {len(high)}",
        f"- mediumReadinessCount: {len(medium)}",
    ]
    for reason, count in reason_counts.most_common():
        lines.append(f"- reason.{reason}: {count}")

    lines.extend(["", "## High Readiness Rows"])
    if not high:
        lines.append("- none")
    for r in high:
        turnover = r.get("avgTurnoverYen")
        turnover_s = f"{turnover/100_000_000:.1f}億円" if turnover else "unknown"
        lines.extend([
            f"### {r['ticker']} {r['signalDate']} {r['category']} / {r['signalType']}",
            f"- shortRank: {r.get('shortRank')}",
            f"- shortUseCase: {r.get('shortUseCase')}",
            f"- shortReadiness: {r.get('shortReadiness')}",
            f"- borrowStatus: {r.get('borrow_borrowStatus')} / {r.get('borrow_jpxCreditCategory')}",
            f"- liquidity: {r.get('liquidityBucket')} / avgTurnover: {turnover_s}",
            f"- marketContext: {r.get('marketContext')} / sectorMarketContext: {r.get('sectorMarketContext')}",
            f"- technicalPattern: {r.get('technicalPattern')} / candle: {r.get('t1Candle')} / volume: {r.get('volumeRatioBucket')}",
            f"- outcome: T+1={r.get('t1')} / T+5={r.get('t5')} / T+20={r.get('t20')}",
            f"- reasons: {', '.join(r.get('shortReadinessReasons', []))}",
            "- lessons:",
        ])
        for lesson in derive_lesson(r):
            lines.append(f"  - {lesson}")
        lines.append("")

    lines.extend([
        "## Practical Rule Draft",
        "- High Readiness shortは `negative_material + weak_reaction + volume_confirmed + jpx_loan_margin_current + high/medium liquidity` を最低条件にする。",
        "- `technical_support` があれば強いが、なくても悪材料と出来高が明確ならmedium以上に残す。",
        "- `borrow_check_required` は消えない。JPX貸借でも当日の売り禁・逆日歩・在庫は別確認する。",
        "- T+20 pending の候補は、短期検証だけでルール化しすぎない。",
        "",
        "## Next Checks",
        "- High Readiness候補の当時の日足チャートを個別確認する。",
        "- 逆日歩/売り禁を取れるソースがあれば追加する。",
        "- daily表示では、High/Mediumだけをショート候補として出し、低流動性や売られすぎは買い回避へ分ける。",
    ])
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {output_json.relative_to(ROOT)} rows={len(high)}")
    print(f"wrote {output_md.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
