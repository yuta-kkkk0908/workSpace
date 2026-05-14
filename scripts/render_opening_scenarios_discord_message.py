#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "topics" / "investment-research" / "inbox"
OUT_DIR = ROOT / "prompts"


def direction_ja(v: str) -> str:
    return {
        "long": "ロング",
        "short": "ショート",
        "up": "上昇",
        "down": "下落",
    }.get((v or "").strip(), v or "")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render opening scenarios into Discord-ready message text")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--fallback-days", type=int, default=3)
    return p.parse_args()


def find_scenario_json(date_str: str, fallback_days: int) -> tuple[Path, str]:
    d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
    for i in range(0, max(0, fallback_days) + 1):
        d = (d0 - timedelta(days=i)).isoformat()
        p = INBOX / f"{d}-opening-scenarios.json"
        if p.exists():
            return p, d
    raise SystemExit(f"opening-scenarios not found for {date_str} (fallback_days={fallback_days})")


def build_message(data: dict) -> str:
    date = data.get("date", "")
    source_date = data.get("sourceDate", "")
    rows = data.get("scenarios", []) or []
    lines = [
        f"寄り付きシナリオ {date}",
        f"- 参照日: {source_date}",
        f"- ルール参照日: {data.get('ruleDashboardDate','')}",
        f"- 1トレード想定リスク: {data.get('riskPerTradeJpy','')} 円",
        f"- 件数: {len(rows)}",
        "",
    ]
    if not rows:
        lines.append("- 変化なし（N/C）")
        return "\n".join(lines)

    for i, r in enumerate(rows, 1):
        skips = r.get("skipConditions", []) or []
        lines.extend(
            [
                f"{i}. {r.get('ticker','')} {r.get('company','')} [{direction_ja(r.get('direction',''))}]",
                f"  トリガー: {r.get('trigger','')}",
                f"  再現性: {r.get('ruleReproducibility','')}",
                f"  勝率目安: {r.get('estimatedWinRate','')} / 推奨ホールド={r.get('suggestedHorizon','')}",
                f"  行動設計: entry={r.get('entryLimitRule','')} / take={r.get('takeProfitRule','')} / stop={r.get('stopLossRule','')} / hold={r.get('holdHorizon','')}",
                f"  見送り条件: {' / '.join(skips) if skips else r.get('invalidationCondition','')}",
                f"  補足: {' / '.join(r.get('rationale', []))}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    src, _ = find_scenario_json(args.date, args.fallback_days)
    data = json.loads(src.read_text(encoding="utf-8"))
    message = build_message(data)

    out_txt = OUT_DIR / "opening-scenarios-discord-message.txt"
    out_md = OUT_DIR / "opening-scenarios-discord-message.md"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_txt.write_text(message, encoding="utf-8")
    out_md.write_text("```text\n" + message + "```\n", encoding="utf-8")
    print(f"wrote {out_txt.relative_to(ROOT)}")
    print(f"wrote {out_md.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
