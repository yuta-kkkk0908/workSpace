#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INBOX = ROOT / "topics" / "investment-research" / "inbox"
OUT_DIR = ROOT / "prompts"

HEAD_RE = re.compile(r"^###\s+([^:]+):\s*(.+)$")
FIELD_RE = re.compile(r"^-\s+([A-Za-z0-9+_-]+):\s*(.*)$")


def expected_direction_ja(v: str) -> str:
    return {
        "up": "上昇",
        "up_watch": "上昇監視",
        "down": "下落",
        "down_watch": "下落監視",
        "neutral": "中立",
        "unknown": "不明",
    }.get((v or "").strip(), v or "")


def rank_ja(v: str) -> str:
    s = (v or "").strip()
    if not s:
        return "不明"
    if s.lower() == "none":
        return "該当なし"
    if s.lower() == "unknown":
        return "不明"
    return s


def signal_type_ja(v: str) -> str:
    mapping = {
        "self_buyback": "自社株買い",
        "earnings_positive": "好決算",
        "earnings_negative": "悪決算",
        "technical_breakout": "テクニカル上放れ",
        "technical_breakdown": "テクニカル下放れ",
        "rebound_long_candidate": "押し目ロング候補",
        "rebound_short_candidate": "戻り売りショート候補",
        "news_material": "ニュース材料",
        "macro_policy": "マクロ政策",
        "fx": "為替要因",
        "relative_strength": "相対強度",
        "sell_the_news": "材料出尽くし売り",
        "momentum_breakout": "モメンタム上放れ",
        "momentum_breakdown": "モメンタム下放れ",
        "event_driven": "イベント駆動",
        "risk_off": "リスクオフ",
        "risk_on": "リスクオン",
        "sector_rotation": "セクターローテーション",
    }
    raw = (v or "").strip()
    if not raw:
        return ""
    parts = [p.strip() for p in re.split(r"\s*/\s*|\s*,\s*", raw) if p.strip()]
    if len(parts) <= 1:
        return mapping.get(raw, raw)
    return " / ".join(mapping.get(p, p) for p in parts)


def gate_ja(v: str) -> str:
    s = (v or "").lower()
    if "pass" in s:
        return "通過"
    if "fail" in s:
        return "非通過"
    if "watch" in s:
        return "監視"
    return v or ""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render market-signals into Discord-ready message text")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--fallback-days", type=int, default=3)
    return p.parse_args()


def find_signals_file(date_str: str, fallback_days: int) -> tuple[Path, str]:
    d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
    for i in range(0, max(0, fallback_days) + 1):
        d = (d0 - timedelta(days=i)).isoformat()
        p = INBOX / f"{d}-market-signals.md"
        if p.exists():
            return p, d
    raise SystemExit(f"market-signals not found for {date_str} (fallback_days={fallback_days})")


def parse_signals(text: str) -> list[dict[str, str]]:
    rows = []
    cur: dict[str, str] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        m = HEAD_RE.match(line)
        if m:
            if cur:
                rows.append(cur)
            cur = {"signalId": m.group(1).strip(), "title": m.group(2).strip()}
            continue
        if not cur:
            continue
        f = FIELD_RE.match(line)
        if f:
            cur[f.group(1)] = f.group(2)
    if cur:
        rows.append(cur)
    return rows


def build_message(date_str: str, source_date: str, rows: list[dict[str, str]]) -> str:
    lines = [
        f"シグナル速報 {date_str}",
        f"- 参照日: {source_date}",
        f"- 件数: {len(rows)}",
        "",
    ]
    if source_date != date_str:
        lines.insert(3, f"- 注意: 当日新規ではなく、{source_date} の繰越を含みます")
    if not rows:
        lines.append("- 変化なし（N/C）")
        return "\n".join(lines)
    for i, r in enumerate(rows, 1):
        ticker = r.get("ticker", "")
        company = r.get("company", "")
        exp = expected_direction_ja(r.get("expectedDirection", ""))
        lr = rank_ja(r.get("longSignalRank", ""))
        sr = rank_ja(r.get("shortSignalRank", ""))
        stype = signal_type_ja(r.get("signalType", ""))
        url = r.get("url", "")
        published = r.get("publishedAt", "")
        gate = gate_ja(r.get("gateStatus", ""))
        material = r.get("materialSignalChecked", "")
        external = r.get("externalContextChecked", "")
        technical = r.get("technicalSignalChecked", "")
        hit = 0
        if gate == "通過":
            hit += 1
        if (material or "").lower() == "yes":
            hit += 1
        if (external or "").lower() == "yes":
            hit += 1
        if (technical or "").lower() == "yes":
            hit += 1
        source_type = r.get("candidateType", "primary")
        lines.extend(
            [
                f"{i}. {ticker} {company} / {exp} / L:{lr} S:{sr}",
                f"  根拠: {stype} / ruleHits={hit} / 種別={source_type}",
                f"  材料日付: {published if published else '未記載'} / 出典: {url}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    src, src_date = find_signals_file(args.date, args.fallback_days)
    rows = parse_signals(src.read_text(encoding="utf-8"))
    msg = build_message(args.date, src_date, rows)

    out_txt = OUT_DIR / "market-signals-discord-message.txt"
    out_md = OUT_DIR / "market-signals-discord-message.md"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_txt.write_text(msg, encoding="utf-8")
    out_md.write_text("```text\n" + msg + "```\n", encoding="utf-8")
    print(f"wrote {out_txt.relative_to(ROOT)}")
    print(f"wrote {out_md.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
