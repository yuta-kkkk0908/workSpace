#!/usr/bin/env python3
"""Analyze rough market outcome logs by available dimensions."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from investment_seed_config import DEFAULT_CONFIG, load_seed_paths

ROOT = Path(__file__).resolve().parents[3]
JST = timezone(timedelta(hours=9))
DEFAULT_OUTCOME = ROOT / "topics/investment-research/inbox/{date}-rough-backtest-outcomes-batch-1.md"
OUTCOME = Path(str(DEFAULT_OUTCOME).format(date="2026-05-10"))
BATCH_FILES = load_seed_paths()
DEFAULT_OUTPUT = ROOT / "topics/investment-research/inbox/{date}-rough-backtest-stratified-analysis.md"
DEFAULT_MARGIN_DATA = ROOT / "topics/investment-research/inbox/{date}-margin-context-data.json"
DEFAULT_SESSION_DATA = ROOT / "topics/investment-research/inbox/{date}-session-context-data.json"
DEFAULT_MARKET_CONTEXT_DATA = ROOT / "topics/investment-research/inbox/{date}-market-context-data.json"
DEFAULT_SECTOR_CONTEXT_DATA = ROOT / "topics/investment-research/inbox/{date}-sector-context-data.json"
DEFAULT_SECTOR_MARKET_CONTEXT_DATA = ROOT / "topics/investment-research/inbox/{date}-sector-market-context-data.json"
DEFAULT_TECHNICAL_CONTEXT_DATA = ROOT / "topics/investment-research/inbox/{date}-technical-context-data.json"
OUTPUT = Path(str(DEFAULT_OUTPUT).format(date="2026-05-10"))
MARGIN_DATA = Path(str(DEFAULT_MARGIN_DATA).format(date="2026-05-10"))
SESSION_DATA = Path(str(DEFAULT_SESSION_DATA).format(date="2026-05-10"))
MARKET_CONTEXT_DATA = Path(str(DEFAULT_MARKET_CONTEXT_DATA).format(date="2026-05-10"))
SECTOR_CONTEXT_DATA = Path(str(DEFAULT_SECTOR_CONTEXT_DATA).format(date="2026-05-10"))
SECTOR_MARKET_CONTEXT_DATA = Path(str(DEFAULT_SECTOR_MARKET_CONTEXT_DATA).format(date="2026-05-10"))
TECHNICAL_CONTEXT_DATA = Path(str(DEFAULT_TECHNICAL_CONTEXT_DATA).format(date="2026-05-11"))


def parse_sections(path: Path) -> list[tuple[str, str, str]]:
    text = path.read_text(encoding="utf-8")
    matches = list(re.finditer(r"^###\s+([^:]+):\s+(.+)$", text, re.M))
    sections = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((m.group(1).strip(), m.group(2).strip(), text[start:end]))
    return sections


def field(body: str, name: str) -> str:
    m = re.search(rf"^\s*- {re.escape(name)}:\s*(.+)$", body, re.M)
    return m.group(1).strip() if m else ""


def volume_bucket(value: str) -> str:
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if ratio >= 5:
        return "spike_5x_plus"
    if ratio >= 2:
        return "spike_2x_5x"
    if ratio >= 1:
        return "normal_1x_2x"
    return "below_avg"


def pct_bucket(value: str) -> str:
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if pct >= 5:
        return "gap_or_move_up_5pct_plus"
    if pct >= 2:
        return "up_2pct_5pct"
    if pct > -2:
        return "flat_minus2_to_plus2"
    if pct > -5:
        return "down_2pct_5pct"
    return "gap_or_move_down_5pct_plus"


def build_source_index() -> dict[tuple[str, str], dict[str, str]]:
    index: dict[tuple[str, str], dict[str, str]] = {}
    for path in BATCH_FILES:
        for signal_id, title, body in parse_sections(path):
            ticker = field(body, "ticker")
            if not ticker:
                m = re.match(r"([0-9]{4}|[0-9]{3}[A-Z])\s+", title)
                ticker = m.group(1) if m else ""
            signal_date = field(body, "signalDate") or field(body, "publishedAt") or signal_id
            dm = re.search(r"(20\d{2}-\d{2}-\d{2})", signal_date)
            signal_date = dm.group(1) if dm else ""
            if not ticker or not signal_date:
                continue
            session = field(body, "session")
            if not session:
                raw = field(body, "signalDate") or field(body, "publishedAt")
                raw_l = raw.lower()
                if "after close" in raw_l:
                    session = "after_close"
                elif "intraday" in raw_l:
                    session = "intraday"
                elif re.search(r"t(15|16|17|18|19|20|21|22|23):", raw_l):
                    session = "after_close"
                elif re.search(r"t(09|10|11|12|13|14):", raw_l):
                    session = "intraday"
                elif "before" in raw_l or "watch" in raw_l:
                    session = "before_open_or_watch"
                else:
                    session = "unknown"
            market_context = "unknown"
            body_l = body.lower()
            if "強い地合い" in body or "tailwind" in body_l or "追い風" in body:
                market_context = "tailwind_or_positive"
            elif "弱い地合い" in body or "headwind" in body_l or "逆風" in body or "大幅続落" in body:
                market_context = "headwind_or_negative"
            elif "marketContext" in body or "市場" in body:
                market_context = "mentioned_unclear"
            volume = "mentioned" if "出来高" in body else "unknown"
            margin = "mentioned" if "信用" in body or "貸借" in body else "unknown"
            index[(ticker, signal_date)] = {
                "session": session,
                "marketContext": market_context,
                "volumeContext": volume,
                "marginContext": margin,
            }
    return index


def parse_outcomes() -> list[dict[str, str]]:
    rows = []
    src_index = build_source_index()
    margin_index = load_margin_index()
    session_index = load_session_index()
    market_index = load_market_context_index()
    sector_index = load_sector_context_index()
    sector_market_index = load_sector_market_context_index()
    technical_index = load_technical_context_index()
    for _, title, body in parse_sections(OUTCOME):
        if field(body, "outcomeStatus") != "ok":
            continue
        ticker_match = re.match(r"([0-9]{4}|[0-9]{3}[A-Z])\s+", title)
        ticker = ticker_match.group(1) if ticker_match else ""
        signal_date = field(body, "signalDate")
        meta = src_index.get((ticker, signal_date), {})
        margin = margin_index.get(ticker, {})
        session_override = session_index.get((ticker, signal_date), {})
        session = meta.get("session", "unknown")
        session_confidence = "explicit" if session != "unknown" else "unknown"
        if session_override and session == "unknown":
            session = session_override.get("session", "unknown")
            session_confidence = session_override.get("confidence", "inferred")
        market_context = meta.get("marketContext", "unknown")
        market_context_source = "source_log" if market_context != "unknown" else "unknown"
        market_override = market_index.get((ticker, signal_date), {})
        if market_context == "unknown" and market_override:
            market_context = market_override.get("marketContext", "unknown")
            market_context_source = market_override.get("contextSource", "rough_index_based")
        sector = sector_index.get(ticker, {})
        sector_market = sector_market_index.get((ticker, signal_date), {})
        technical = technical_index.get((ticker, signal_date), {})
        candle = field(body, "T+1Candle") or "unknown"
        gap_bucket = pct_bucket(field(body, "T+1OpenVsBasePct"))
        rows.append({
            "ticker": ticker,
            "title": title,
            "sourceSignalId": field(body, "sourceSignalId"),
            "signalDate": signal_date,
            "category": field(body, "disclosureCategory") or "unknown",
            "signalType": field(body, "signalType") or "unknown",
            "expected": field(body, "expectedDirection") or "unknown",
            "longRank": field(body, "longSignalRank") or "unknown",
            "shortRank": field(body, "shortSignalRank") or "unknown",
            "outcomeType": field(body, "roughOutcomeType") or "unknown",
            "t1": field(body, "T+1Judge") or "unknown",
            "t5": field(body, "T+5Judge") or "unknown",
            "t20": field(body, "T+20Judge") or "unknown",
            "session": session,
            "sessionConfidence": session_confidence,
            "marketContext": market_context,
            "marketContextSource": market_context_source,
            "volumeContext": meta.get("volumeContext", "unknown"),
            "volumeRatioBucket": volume_bucket(field(body, "T+1VolumeRatio25") or field(body, "T+1VolumeRatio5")),
            "t1Candle": candle,
            "t1OpenVsBaseBucket": gap_bucket,
            "t1CloseLocation": field(body, "T+1CloseLocation") or "unknown",
            "marginContext": "filled" if margin else meta.get("marginContext", "unknown"),
            "marginBucket": margin.get("marginBucket", "unknown"),
            "sectorGroup": sector.get("sectorGroup", "unknown"),
            "sectorProfile": sector.get("sectorProfile", "unknown"),
            "sectorMarketContext": sector_market.get("sectorMarketContext", "unknown"),
            "sectorProxy": sector_market.get("proxyName", "unknown"),
            "sectorRelativeToTopixPct": sector_market.get("relativeToTopixPct", "unknown"),
            "technicalStatus": technical.get("technicalStatus", "unknown"),
            "technicalPattern": technical.get("technicalPattern", "unknown"),
            "maTrend": technical.get("maTrend", "unknown"),
            "closeVsMA25Bucket": technical.get("closeVsMA25Bucket", "unknown"),
            "rsi14Bucket": technical.get("rsi14Bucket", "unknown"),
            "macdBucket": technical.get("macdBucket", "unknown"),
            "bollingerBucket": technical.get("bollingerBucket", "unknown"),
            "breakout20": technical.get("breakout20", "unknown"),
        })
    return rows


def load_margin_index() -> dict[str, dict[str, str]]:
    if not MARGIN_DATA.exists():
        return {}
    data = json.loads(MARGIN_DATA.read_text(encoding="utf-8"))
    return {str(row.get("ticker")): row for row in data.get("rows", []) if row.get("ticker")}


def load_session_index() -> dict[tuple[str, str], dict[str, str]]:
    if not SESSION_DATA.exists():
        return {}
    data = json.loads(SESSION_DATA.read_text(encoding="utf-8"))
    index = {}
    for row in data.get("rows", []):
        ticker = str(row.get("ticker") or "")
        signal_date = str(row.get("signalDate") or "")
        if ticker and signal_date:
            index[(ticker, signal_date)] = {
                "session": str(row.get("session") or "unknown"),
                "confidence": str(row.get("confidence") or "inferred"),
            }
    return index


def load_market_context_index() -> dict[tuple[str, str], dict[str, str]]:
    if not MARKET_CONTEXT_DATA.exists():
        return {}
    data = json.loads(MARKET_CONTEXT_DATA.read_text(encoding="utf-8"))
    index = {}
    for row in data.get("rows", []):
        ticker = str(row.get("ticker") or "")
        signal_date = str(row.get("signalDate") or "")
        if ticker and signal_date:
            index[(ticker, signal_date)] = {
                "marketContext": str(row.get("marketContext") or "unknown"),
                "contextSource": str(row.get("contextSource") or "rough_index_based"),
            }
    return index


def load_sector_context_index() -> dict[str, dict[str, str]]:
    if not SECTOR_CONTEXT_DATA.exists():
        return {}
    data = json.loads(SECTOR_CONTEXT_DATA.read_text(encoding="utf-8"))
    index = {}
    for row in data.get("rows", []):
        ticker = str(row.get("ticker") or "")
        if ticker:
            index[ticker] = {
                "sectorGroup": str(row.get("sectorGroup") or "unknown"),
                "sectorProfile": str(row.get("sectorProfile") or "unknown"),
            }
    return index


def load_sector_market_context_index() -> dict[tuple[str, str], dict[str, str]]:
    if not SECTOR_MARKET_CONTEXT_DATA.exists():
        return {}
    data = json.loads(SECTOR_MARKET_CONTEXT_DATA.read_text(encoding="utf-8"))
    index = {}
    for row in data.get("rows", []):
        ticker = str(row.get("ticker") or "")
        signal_date = str(row.get("signalDate") or "")
        if ticker and signal_date:
            index[(ticker, signal_date)] = {
                "sectorMarketContext": str(row.get("sectorMarketContext") or "unknown"),
                "proxyName": str(row.get("proxyName") or "unknown"),
                "relativeToTopixPct": str(row.get("relativeToTopixPct") or "unknown"),
            }
    return index


def load_technical_context_index() -> dict[tuple[str, str], dict[str, str]]:
    if not TECHNICAL_CONTEXT_DATA.exists():
        return {}
    data = json.loads(TECHNICAL_CONTEXT_DATA.read_text(encoding="utf-8"))
    index = {}
    for row in data.get("rows", []):
        ticker = str(row.get("ticker") or "")
        signal_date = str(row.get("signalDate") or "")
        if ticker and signal_date:
            index[(ticker, signal_date)] = {
                "technicalStatus": str(row.get("technicalStatus") or "unknown"),
                "technicalPattern": str(row.get("technicalPattern") or row.get("technicalStatus") or "unknown"),
                "maTrend": str(row.get("maTrend") or "unknown"),
                "closeVsMA25Bucket": str(row.get("closeVsMA25Bucket") or "unknown"),
                "rsi14Bucket": str(row.get("rsi14Bucket") or "unknown"),
                "macdBucket": str(row.get("macdBucket") or "unknown"),
                "bollingerBucket": str(row.get("bollingerBucket") or "unknown"),
                "breakout20": str(row.get("breakout20") or "unknown"),
            }
    return index


def summarize(rows: list[dict[str, str]], dimension: str, min_count: int = 1) -> list[str]:
    windows = ["t1", "t5", "t20"]
    grouped: dict[str, dict[str, Counter]] = defaultdict(lambda: {w: Counter() for w in windows})
    for row in rows:
        key = row.get(dimension) or "unknown"
        for w in windows:
            grouped[key][w][row[w]] += 1
    lines = []
    for key in sorted(grouped):
        total = sum(grouped[key]["t1"].values())
        if total < min_count:
            continue
        parts = []
        for w in windows:
            c = grouped[key][w]
            judged = c["win"] + c["loss"] + c["flat"]
            win_rate = c["win"] / judged * 100 if judged else 0
            parts.append(f"{w.upper()} win={c['win']} loss={c['loss']} flat={c['flat']} excl={c['excluded_event_or_context']} wr={win_rate:.1f}%")
        lines.append(f"- {key} ({total}): " + " / ".join(parts))
    return lines


def top_examples(rows: list[dict[str, str]], outcome: str, limit: int = 8) -> list[str]:
    selected = [r for r in rows if r["outcomeType"] == outcome]
    lines = []
    for r in selected[:limit]:
        lines.append(f"- {r['ticker']} {r['title']}: category={r['category']}, expected={r['expected']}, T+1={r['t1']}, T+5={r['t5']}, T+20={r['t20']}")
    return lines


def main() -> int:
    global OUTCOME, BATCH_FILES, OUTPUT, MARGIN_DATA, SESSION_DATA, MARKET_CONTEXT_DATA, SECTOR_CONTEXT_DATA, SECTOR_MARKET_CONTEXT_DATA, TECHNICAL_CONTEXT_DATA

    parser = argparse.ArgumentParser(description="Analyze rough market outcome logs by available dimensions.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    parser.add_argument("--outcome", type=Path, default=None)
    parser.add_argument("--seed-config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--seed-list", default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--margin-data", type=Path, default=None)
    parser.add_argument("--session-data", type=Path, default=None)
    parser.add_argument("--market-context-data", type=Path, default=None)
    parser.add_argument("--sector-context-data", type=Path, default=None)
    parser.add_argument("--sector-market-context-data", type=Path, default=None)
    parser.add_argument("--technical-context-data", type=Path, default=None)
    args = parser.parse_args()

    OUTCOME = args.outcome or Path(str(DEFAULT_OUTCOME).format(date=args.date))
    BATCH_FILES = load_seed_paths(args.seed_config, args.seed_list)
    OUTPUT = args.output or Path(str(DEFAULT_OUTPUT).format(date=args.date))
    MARGIN_DATA = args.margin_data or Path(str(DEFAULT_MARGIN_DATA).format(date=args.date))
    SESSION_DATA = args.session_data or Path(str(DEFAULT_SESSION_DATA).format(date=args.date))
    MARKET_CONTEXT_DATA = args.market_context_data or Path(str(DEFAULT_MARKET_CONTEXT_DATA).format(date=args.date))
    SECTOR_CONTEXT_DATA = args.sector_context_data or Path(str(DEFAULT_SECTOR_CONTEXT_DATA).format(date=args.date))
    SECTOR_MARKET_CONTEXT_DATA = args.sector_market_context_data or Path(str(DEFAULT_SECTOR_MARKET_CONTEXT_DATA).format(date=args.date))
    TECHNICAL_CONTEXT_DATA = args.technical_context_data or Path(str(DEFAULT_TECHNICAL_CONTEXT_DATA).format(date=args.date))

    rows = parse_outcomes()
    lines = [
        f"# {args.date} Rough Backtest Stratified Analysis",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {args.date}",
        "- mode: rough-stratified-analysis",
        f"- sourceLog: {OUTCOME.relative_to(ROOT / 'topics/investment-research')}",
        "- caution: Yahoo Finance日足終値と既存ログの粗メタ情報による層別。発表時刻、地合い、出来高、信用残は未取得/推定が混じる。売買助言ではない。",
        "",
        "## Summary",
        f"- analyzedRows: {len(rows)}",
        f"- sessionKnownRows: {sum(1 for r in rows if r['session'] != 'unknown')}",
        f"- marketContextMentionedRows: {sum(1 for r in rows if r['marketContext'] != 'unknown')}",
        f"- volumeMentionedRows: {sum(1 for r in rows if r['volumeContext'] != 'unknown')}",
        f"- marginMentionedRows: {sum(1 for r in rows if r['marginContext'] != 'unknown')}",
        f"- priceActionKnownRows: {sum(1 for r in rows if r['t1Candle'] != 'unknown')}",
        f"- sectorKnownRows: {sum(1 for r in rows if r['sectorGroup'] != 'unknown')}",
        f"- sectorMarketKnownRows: {sum(1 for r in rows if r['sectorMarketContext'] != 'unknown')}",
        "",
        "## By Disclosure Category",
    ]
    lines.extend(summarize(rows, "category", min_count=1))
    lines.extend(["", "## By Session"])
    lines.extend(summarize(rows, "session", min_count=1))
    lines.extend(["", "## By Session Confidence"])
    lines.extend(summarize(rows, "sessionConfidence", min_count=1))
    lines.extend(["", "## By Market Context Mention"])
    lines.extend(summarize(rows, "marketContext", min_count=1))
    lines.extend(["", "## By Market Context Source"])
    lines.extend(summarize(rows, "marketContextSource", min_count=1))
    lines.extend(["", "## By Volume Context Availability"])
    lines.extend(summarize(rows, "volumeContext", min_count=1))
    lines.extend(["", "## By T+1 Volume Ratio Bucket"])
    lines.extend(summarize(rows, "volumeRatioBucket", min_count=1))
    lines.extend(["", "## By T+1 Candle"])
    lines.extend(summarize(rows, "t1Candle", min_count=1))
    lines.extend(["", "## By T+1 Open Gap Bucket"])
    lines.extend(summarize(rows, "t1OpenVsBaseBucket", min_count=1))
    lines.extend(["", "## By Margin Context Availability"])
    lines.extend(summarize(rows, "marginContext", min_count=1))
    lines.extend(["", "## By Margin Bucket"])
    lines.extend(summarize(rows, "marginBucket", min_count=1))
    lines.extend(["", "## By Volume Ratio x Margin Bucket"])
    for row in rows:
        row["volumeMarginBucket"] = f"{row['volumeRatioBucket']}__{row['marginBucket']}"
    lines.extend(summarize(rows, "volumeMarginBucket", min_count=2))
    lines.extend(["", "## By Volume Ratio x T+1 Candle"])
    for row in rows:
        row["volumeCandleBucket"] = f"{row['volumeRatioBucket']}__{row['t1Candle']}"
    lines.extend(summarize(rows, "volumeCandleBucket", min_count=2))
    lines.extend(["", "## By Sector Group"])
    lines.extend(summarize(rows, "sectorGroup", min_count=1))
    lines.extend(["", "## By Sector Profile"])
    lines.extend(summarize(rows, "sectorProfile", min_count=1))
    lines.extend(["", "## By Sector Profile x Market Context"])
    for row in rows:
        row["sectorMarketBucket"] = f"{row['sectorProfile']}__{row['marketContext']}"
    lines.extend(summarize(rows, "sectorMarketBucket", min_count=2))
    lines.extend(["", "## By Sector Market Context"])
    lines.extend(summarize(rows, "sectorMarketContext", min_count=1))
    lines.extend(["", "## By Sector Profile x Sector Market Context"])
    for row in rows:
        row["sectorProfileMarketProxyBucket"] = f"{row['sectorProfile']}__{row['sectorMarketContext']}"
    lines.extend(summarize(rows, "sectorProfileMarketProxyBucket", min_count=2))
    lines.extend(["", "## By Long Rank"])
    lines.extend(summarize(rows, "longRank", min_count=2))
    lines.extend(["", "## By Short Rank"])
    lines.extend(summarize(rows, "shortRank", min_count=2))
    lines.extend(["", "## By Technical Pattern"])
    lines.extend(summarize(rows, "technicalPattern", min_count=2))
    lines.extend(["", "## By MA Trend"])
    lines.extend(summarize(rows, "maTrend", min_count=2))
    lines.extend(["", "## By RSI14 Bucket"])
    lines.extend(summarize(rows, "rsi14Bucket", min_count=2))
    lines.extend(["", "## By MACD Bucket"])
    lines.extend(summarize(rows, "macdBucket", min_count=2))
    lines.extend(["", "## By Bollinger Bucket"])
    lines.extend(summarize(rows, "bollingerBucket", min_count=2))
    lines.extend(["", "## By Breakout20"])
    lines.extend(summarize(rows, "breakout20", min_count=2))
    lines.extend(["", "## Trend Continuation Examples"])
    lines.extend(top_examples(rows, "trend_continuation"))
    lines.extend(["", "## Failed Or Downtrend Examples"])
    lines.extend(top_examples(rows, "failed_or_downtrend"))
    lines.extend([
        "",
        "## Practical Read",
        "- 発表時刻が取れている行はまだ少ない。今後のdailyでは `session` を必須にした方がよい。",
        "- T+1ローソク足、出来高倍率、信用残、セクター分類を追加したため、終値だけの評価よりも初動の質を読めるようになった。",
        "- `earnings_positive` は強いが、上方修正率・増配・最高益・外部地合いが混ざっているため、次は複合条件で分解する。",
        "- `capital_policy` と `large_holding` はT+20で弱くなりやすいため、長く持つより初動/需給イベントとして扱う仮説が立つ。",
        "- `risk_event` は件数不足ながら短期/中期ともshort方向に素直。悪材料サンプルを増やす価値が高い。",
        "",
        "## Next Layering Targets",
        "- session: after_close / intraday / before_open を完全補完する",
        "- marketContext: tailwind / headwind / neutral を各signalDateで補完する",
        "- volumeContext: `T+1出来高倍率 × T+1ローソク足` をルール候補に落とす",
        "- marginContext: 優先rankの信用残は補完済み。残りは母数拡張時に低優先で処理する",
        "- sectorContext: 静的分類に加えて、ETF/指数proxyで反応日のセクター追い風/逆風を粗補完した",
        "- entryReadiness: Rankと実際の監視準備度を分ける",
    ])
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)} rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
