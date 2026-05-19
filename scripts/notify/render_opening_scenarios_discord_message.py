#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INBOX = ROOT / "topics" / "investment-research" / "inbox"
OUT_DIR = ROOT / "prompts"


def direction_ja(v: str) -> str:
    return {
        "long": "ロング",
        "short": "ショート",
        "up": "上昇",
        "down": "下落",
    }.get((v or "").strip(), v or "")


def hold_days_ja(v: str) -> str:
    x = (v or "").strip().upper()
    if x == "T+1":
        return "1営業日程度"
    if x == "T+5":
        return "3-5営業日程度"
    if x == "T+20":
        return "10-20営業日程度"
    return "未定（短期監視）"


def invalidation_ja(row: dict) -> str:
    skips = row.get("skipConditions", []) or []
    if skips:
        return str(skips[0])
    return str(row.get("invalidationCondition", "") or "前提が崩れた場合は見送り/撤退")


def rationale_ja(row: dict) -> str:
    trigger = str(row.get("trigger", "") or "")
    repro = str(row.get("ruleReproducibility", "") or "")
    wr = str(row.get("estimatedWinRate", "") or "")
    status = str(row.get("ruleStatus", "") or "")
    parts = [p for p in [trigger, repro, f"ruleStatus={status}" if status else "", wr] if p]
    return " / ".join(parts) if parts else "根拠情報不足"


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
        f"- モード: {data.get('planMode','trade')}",
        f"- 件数内訳: long={((data.get('counts') or {}).get('long','?'))} / short={((data.get('counts') or {}).get('short','?'))}",
        f"- 件数: {len(rows)}",
        "",
    ]
    for n in (data.get("planNotes") or []):
        lines.append(f"- 注意: {n}")
    if data.get("planNotes"):
        lines.append("")
    if not rows:
        lines.append("- 変化なし（N/C）")
        return "\n".join(lines)

    for i, r in enumerate(rows, 1):
        hold_code = str(r.get("suggestedHorizon", "") or "")
        lines.extend(
            [
                f"{i}. {r.get('ticker','')} {r.get('company','')} [{direction_ja(r.get('direction',''))}]",
                f"  方向: {direction_ja(r.get('direction',''))}",
                f"  品質: score={r.get('scenarioScore',0)} / ruleHits={r.get('ruleHitCount',0)} / {r.get('estimatedWinRate','')}",
                f"  根拠: {rationale_ja(r)}",
                f"  エントリー: {r.get('entryLimitRule','')}",
                f"  利確: {r.get('takeProfitRule','')}",
                f"  損切: {r.get('stopLossRule','')}",
                f"  想定保有日数: {hold_days_ja(hold_code)}（{hold_code or 'N/A'}）",
                f"  無効化条件: {invalidation_ja(r)}",
                f"  補足: 種別={r.get('candidateSource','primary')}",
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
