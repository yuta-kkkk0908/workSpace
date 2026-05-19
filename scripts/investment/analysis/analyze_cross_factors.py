#!/usr/bin/env python3
"""Create a readable cross-factor memo for rough investment backtest rows."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
JST = timezone(timedelta(hours=9))
DEFAULT_OUTPUT = ROOT / "topics/investment-research/inbox/{date}-cross-factor-read.md"

sys.path.insert(0, str(ROOT / "scripts/investment/analysis"))
import analyze_market_outcomes as outcomes  # noqa: E402

WINDOWS = ("t1", "t5", "t20")


def win_rate(counter: Counter) -> float | None:
    judged = counter["win"] + counter["loss"] + counter["flat"]
    if judged == 0:
        return None
    return counter["win"] / judged * 100


def summarize(rows: list[dict[str, str]], keys: tuple[str, ...], min_count: int = 3) -> list[dict]:
    grouped: dict[tuple[str, ...], dict[str, Counter]] = defaultdict(lambda: {w: Counter() for w in WINDOWS})
    examples: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = tuple(row.get(k, "unknown") for k in keys)
        for w in WINDOWS:
            grouped[key][w][row[w]] += 1
        if len(examples[key]) < 4:
            examples[key].append(row)
    out = []
    for key, counters in grouped.items():
        total = sum(counters["t1"].values())
        if total < min_count:
            continue
        out.append({
            "key": key,
            "total": total,
            "counters": counters,
            "examples": examples[key],
            "t1wr": win_rate(counters["t1"]),
            "t5wr": win_rate(counters["t5"]),
            "t20wr": win_rate(counters["t20"]),
        })
    return sorted(out, key=lambda x: (x["total"], x["t20wr"] or -1), reverse=True)


def line_for(item: dict) -> str:
    parts = []
    for w in WINDOWS:
        c = item["counters"][w]
        wr = win_rate(c)
        wr_s = f"{wr:.1f}%" if wr is not None else "n/a"
        parts.append(f"{w.upper()} {c['win']}/{c['loss']}/{c['flat']} wr={wr_s}")
    return f"- {' × '.join(item['key'])} ({item['total']}): " + " / ".join(parts)


def examples_lines(item: dict) -> list[str]:
    lines = []
    for row in item["examples"][:3]:
        lines.append(f"  - {row['ticker']} {row['signalDate']} {row['category']} {row['signalType']} T1/T5/T20={row['t1']}/{row['t5']}/{row['t20']}")
    return lines


def top_bottom(items: list[dict], window: str, min_count: int = 4) -> tuple[list[dict], list[dict]]:
    eligible = [i for i in items if i["total"] >= min_count and win_rate(i["counters"][window]) is not None]
    top = sorted(eligible, key=lambda i: win_rate(i["counters"][window]), reverse=True)[:8]
    bottom = sorted(eligible, key=lambda i: win_rate(i["counters"][window]))[:8]
    return top, bottom


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a readable cross-factor memo.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    parser.add_argument("--outcome", type=Path, default=None)
    parser.add_argument("--seed-config", type=Path, default=outcomes.DEFAULT_CONFIG)
    parser.add_argument("--seed-list", default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--margin-data", type=Path, default=None)
    parser.add_argument("--session-data", type=Path, default=None)
    parser.add_argument("--market-context-data", type=Path, default=None)
    parser.add_argument("--sector-context-data", type=Path, default=None)
    parser.add_argument("--sector-market-context-data", type=Path, default=None)
    parser.add_argument("--technical-context-data", type=Path, default=None)
    args = parser.parse_args()

    output = args.output or Path(str(DEFAULT_OUTPUT).format(date=args.date))
    outcomes.OUTCOME = args.outcome or Path(str(outcomes.DEFAULT_OUTCOME).format(date=args.date))
    outcomes.BATCH_FILES = outcomes.load_seed_paths(args.seed_config, args.seed_list)
    outcomes.MARGIN_DATA = args.margin_data or Path(str(outcomes.DEFAULT_MARGIN_DATA).format(date=args.date))
    outcomes.SESSION_DATA = args.session_data or Path(str(outcomes.DEFAULT_SESSION_DATA).format(date=args.date))
    outcomes.MARKET_CONTEXT_DATA = args.market_context_data or Path(str(outcomes.DEFAULT_MARKET_CONTEXT_DATA).format(date=args.date))
    outcomes.SECTOR_CONTEXT_DATA = args.sector_context_data or Path(str(outcomes.DEFAULT_SECTOR_CONTEXT_DATA).format(date=args.date))
    outcomes.SECTOR_MARKET_CONTEXT_DATA = args.sector_market_context_data or Path(str(outcomes.DEFAULT_SECTOR_MARKET_CONTEXT_DATA).format(date=args.date))
    outcomes.TECHNICAL_CONTEXT_DATA = args.technical_context_data or Path(str(outcomes.DEFAULT_TECHNICAL_CONTEXT_DATA).format(date=args.date))

    rows = outcomes.parse_outcomes()
    actionable = [r for r in rows if not r["t1"].startswith("excluded")]
    dims = {
        "Margin x Market": ("marginBucket", "marketContext"),
        "Category x Market": ("category", "marketContext"),
        "Category x Margin": ("category", "marginBucket"),
        "Session x Market": ("session", "marketContext"),
        "Long Rank x Market": ("longRank", "marketContext"),
        "Short Rank x Market": ("shortRank", "marketContext"),
        "Volume x Margin": ("volumeRatioBucket", "marginBucket"),
        "Volume x Candle": ("volumeRatioBucket", "t1Candle"),
        "Candle x Market": ("t1Candle", "marketContext"),
        "Sector Profile x Market": ("sectorProfile", "marketContext"),
        "Sector Profile x Sector Proxy": ("sectorProfile", "sectorMarketContext"),
        "Category x Sector Proxy": ("category", "sectorMarketContext"),
        "Sector Profile x Margin": ("sectorProfile", "marginBucket"),
    }

    lines = [
        f"# {args.date} Cross Factor Read",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {args.date}",
        "- mode: cross-factor-read",
        f"- sourceLog: inbox/{args.date}-rough-backtest-stratified-analysis.md",
        "- caution: 粗いバックテストの層別読み。サンプル数が少なく、指数ベースのmarketContext推定を含む。売買助言ではない。",
        "",
        "## Summary",
        f"- analyzedRows: {len(rows)}",
        f"- actionableRows: {len(actionable)}",
        f"- excludedRows: {len(rows) - len(actionable)}",
        "- readingPolicy: n<4 は原則として仮説止まり。T+1/T+5/T+20の方向が揃う組み合わせだけルール候補にする。",
        "",
        "## High Signal Reads",
        "- `sell_heavy_or_squeeze_risk` はサンプルが増えても短期が強め。悪材料ショートでは踏み上げ/買い戻しリスクとして強く減点する。",
        "- `buy_only_heavy` はT+20が弱め。好材料でも中期継続は疑い、初動後の失速確認を優先する。",
        "- `tailwind_or_positive` 単体は万能ではない。地合い追い風でも材料/需給が弱いと普通に負ける。",
        "- `headwind_or_negative` で勝つ銘柄は、材料強度がかなり強いか、悪材料の売り方向が機能した可能性がある。",
        "- `intraday` はT+1が弱い。場中材料は初動を見てから入るより、引け形状/出来高吸収を待つ方が安全そう。",
        "- `T+1ローソク足 × 出来高倍率` は、同じUP材料でも初動が吸収されたのか、上ヒゲで売られたのかを分けるための新しい主軸にする。",
        "- `sectorMarketContext` はETF/指数proxyによる粗いセクター地合い。市場全体の追い風/逆風と分けて、セクターに勝っているかを読む。",
        "",
    ]

    for title, keys in dims.items():
        items = summarize(actionable, keys, min_count=3)
        lines.extend([f"## {title}", ""])
        for item in items[:18]:
            lines.append(line_for(item))
        top, bottom = top_bottom(items, "t20", min_count=4)
        lines.extend(["", f"### {title} T+20 Top Candidates"])
        for item in top[:5]:
            lines.append(line_for(item))
            lines.extend(examples_lines(item))
        lines.extend(["", f"### {title} T+20 Weak Candidates"])
        for item in bottom[:5]:
            lines.append(line_for(item))
            lines.extend(examples_lines(item))
        lines.append("")

    lines.extend([
        "## Rule Candidate Notes",
        "- Long加点候補: `earnings_positive × balanced/balanced_to_buy_leaning` で、かつ `after_close` の翌日反応が強いもの。",
        "- Long注意候補: `earnings_positive × buy_only_heavy` は初動が良くてもT+20失速を警戒する。",
        "- Short/回避候補: `capital_policy × buy_only_heavy` は希薄化・売出し系で買い方の逃げ遅れを疑う。",
        "- Short減点候補: `capital_policy × sell_heavy_or_squeeze_risk` は悪材料でも売りが溜まりすぎて逆行しやすい。",
        "- 地合い補正: `tailwind_or_positive` は無条件加点ではなく、材料強度/需給が揃ったときだけ小加点。",
        "- 地合い補正: `headwind_or_negative` で上がった好材料は相対強度ありとして翌日以降の継続監視候補。",
        "",
        "## Next Fill Targets",
        "- marketContextは指数粗判定なので、次はセクター地合いを追加する。保険、半導体、グロース、不動産、機械、小売の6分類から始める。",
        "- sectorContextは静的分類に加え、業種別ETF/指数proxyで反応日のセクター追い風/逆風を補完済み。次はproxy精度と対象セクターを増やす。",
        "- volumeContextはT+1出来高倍率とローソク足を併用し、`volumeRatioBucket × t1Candle × marginBucket` をルールへ落とす。",
        "- まだmarginBucket unknownの通常ランク銘柄が残るため、母数を100件規模へ広げるなら次の一括補完対象にする。",
    ])

    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
