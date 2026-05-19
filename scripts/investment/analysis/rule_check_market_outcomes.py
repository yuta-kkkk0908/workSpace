#!/usr/bin/env python3
"""Summarize rough market outcomes into rule-check candidates.

The output is a research aid for refining `topics/investment-research/signal-rules.md`.
It is not trading advice. The script intentionally keeps the calculations simple
and transparent so the generated memo can be reviewed by hand.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[3]
JST = timezone(timedelta(hours=9))
DEFAULT_MD_OUTPUT = ROOT / "topics/investment-research/inbox/{date}-rule-check-summary.md"
DEFAULT_JSON_OUTPUT = ROOT / "topics/investment-research/inbox/{date}-rule-check-data.json"
DEFAULT_OUTCOME = ROOT / "topics/investment-research/inbox/{date}-rough-backtest-outcomes-batch-1.md"
WINDOWS = ("t1", "t5", "t20")
DEFAULT_DB = ROOT / "data" / "investment.db"

sys.path.insert(0, str(ROOT / "scripts/investment/analysis"))
import analyze_market_outcomes as outcomes  # noqa: E402


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


RULE_SPECS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("category", ("category",)),
    ("signal_type", ("signalType",)),
    ("category_x_signal_type", ("category", "signalType")),
    ("category_x_session", ("category", "session")),
    ("category_x_market", ("category", "marketContext")),
    ("category_x_sector_market", ("category", "sectorMarketContext")),
    ("category_x_margin", ("category", "marginBucket")),
    ("category_x_volume", ("category", "volumeRatioBucket")),
    ("category_x_candle", ("category", "t1Candle")),
    ("volume_x_candle", ("volumeRatioBucket", "t1Candle")),
    ("volume_x_candle_x_margin", ("volumeRatioBucket", "t1Candle", "marginBucket")),
    ("market_x_sector_market", ("marketContext", "sectorMarketContext")),
    ("session_x_candle", ("session", "t1Candle")),
    ("technical_pattern", ("technicalPattern",)),
    ("category_x_technical", ("category", "technicalPattern")),
    ("technical_x_candle", ("technicalPattern", "t1Candle")),
    ("technical_x_volume", ("technicalPattern", "volumeRatioBucket")),
    ("ma_x_macd", ("maTrend", "macdBucket")),
    ("rsi_x_candle", ("rsi14Bucket", "t1Candle")),
    ("bollinger_x_candle", ("bollingerBucket", "t1Candle")),
    ("breakout_x_candle", ("breakout20", "t1Candle")),
    ("long_rank_x_category", ("longRank", "category")),
    ("short_rank_x_category", ("shortRank", "category")),
)


def counter_win_rate(counter: Counter[str]) -> float | None:
    judged = counter["win"] + counter["loss"] + counter["flat"]
    if judged == 0:
        return None
    return counter["win"] / judged * 100


def support(counter: Counter[str]) -> int:
    return counter["win"] + counter["loss"] + counter["flat"]


def direction(rows: list[dict[str, str]]) -> str:
    expected = Counter(row.get("expected", "unknown") for row in rows)
    up = sum(v for k, v in expected.items() if "up" in k.lower())
    down = sum(v for k, v in expected.items() if "down" in k.lower())
    neutral = sum(v for k, v in expected.items() if "neutral" in k.lower() or "unclear" in k.lower())
    if up > down and up >= neutral:
        return "long_bias"
    if down > up and down >= neutral:
        return "short_bias"
    return "mixed_or_neutral"


def judgement(counters: dict[str, Counter[str]], min_count: int) -> str:
    t1 = counters["t1"]
    t5 = counters["t5"]
    t20 = counters["t20"]
    t1_n = support(t1)
    t5_n = support(t5)
    t20_n = support(t20)
    t1_wr = counter_win_rate(t1)
    t5_wr = counter_win_rate(t5)
    t20_wr = counter_win_rate(t20)
    if min(t1_n, t5_n) < min_count:
        return "hypothesis_only"
    if t1_wr is not None and t5_wr is not None and t1_wr >= 65 and t5_wr >= 60 and (t20_n < min_count or (t20_wr or 0) >= 50):
        return "promote_candidate"
    if t1_wr is not None and t5_wr is not None and t1_wr <= 40 and t5_wr <= 45:
        return "downgrade_or_avoid_candidate"
    if t20_n >= min_count and t20_wr is not None and t1_wr is not None and t1_wr >= 55 and t20_wr <= 45:
        return "short_term_only_candidate"
    if t1_wr is not None and t5_wr is not None and abs(t1_wr - t5_wr) >= 25:
        return "timeframe_sensitive"
    return "watch_more"


def window_stats(counters: dict[str, Counter[str]]) -> dict[str, dict[str, float | int | None]]:
    out: dict[str, dict[str, float | int | None]] = {}
    for w in WINDOWS:
        c = counters[w]
        out[w] = {
            "win": c["win"],
            "loss": c["loss"],
            "flat": c["flat"],
            "excluded": c["excluded_event_or_context"],
            "unjudged": c["unjudged"],
            "support": support(c),
            "winRate": round(counter_win_rate(c), 1) if counter_win_rate(c) is not None else None,
        }
    return out


def occurrence_stats(rows: list[dict[str, str]]) -> dict:
    dates = sorted(row.get("signalDate", "") for row in rows if row.get("signalDate"))
    return {
        "count": len(rows),
        "firstSignalDate": dates[0] if dates else "",
        "lastSignalDate": dates[-1] if dates else "",
        "categories": dict(Counter(row.get("category", "unknown") for row in rows)),
        "signalTypes": dict(Counter(row.get("signalType", "unknown") for row in rows)),
        "sessions": dict(Counter(row.get("session", "unknown") for row in rows)),
        "marketContexts": dict(Counter(row.get("marketContext", "unknown") for row in rows)),
    }


def compact_key(row: dict[str, str], keys: Iterable[str]) -> tuple[str, ...]:
    return tuple((row.get(k) or "unknown") for k in keys)


def group_rules(rows: list[dict[str, str]], min_count: int) -> list[dict]:
    results: list[dict] = []
    for rule_group, keys in RULE_SPECS:
        grouped: dict[tuple[str, ...], dict[str, Counter[str]]] = defaultdict(lambda: {w: Counter() for w in WINDOWS})
        examples: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
        grouped_rows: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            key = compact_key(row, keys)
            grouped_rows[key].append(row)
            for w in WINDOWS:
                grouped[key][w][row.get(w, "unknown")] += 1
            if len(examples[key]) < 5:
                examples[key].append(row)
        for key, counters in grouped.items():
            max_support = max(support(counters[w]) for w in WINDOWS)
            if max_support < min_count:
                continue
            item = {
                "ruleGroup": rule_group,
                "dimensions": list(keys),
                "key": list(key),
                "label": " × ".join(key),
                "rowCount": len(grouped_rows[key]),
                "direction": direction(grouped_rows[key]),
                "judgement": judgement(counters, min_count),
                "windows": window_stats(counters),
                "occurrence": occurrence_stats(grouped_rows[key]),
                "examples": [
                    {
                        "ticker": r.get("ticker"),
                        "signalDate": r.get("signalDate"),
                        "category": r.get("category"),
                        "signalType": r.get("signalType"),
                        "expected": r.get("expected"),
                        "t1": r.get("t1"),
                        "t5": r.get("t5"),
                        "t20": r.get("t20"),
                    }
                    for r in examples[key]
                ],
            }
            results.append(item)
    order = {
        "promote_candidate": 0,
        "downgrade_or_avoid_candidate": 1,
        "short_term_only_candidate": 2,
        "timeframe_sensitive": 3,
        "watch_more": 4,
        "hypothesis_only": 5,
    }
    return sorted(
        results,
        key=lambda x: (
            order.get(x["judgement"], 9),
            -max(x["windows"][w]["support"] or 0 for w in WINDOWS),
            x["ruleGroup"],
            x["label"],
        ),
    )


def line_for(item: dict) -> str:
    parts = []
    for w in WINDOWS:
        s = item["windows"][w]
        wr = "n/a" if s["winRate"] is None else f"{s['winRate']:.1f}%"
        parts.append(f"{w.upper()} {s['win']}/{s['loss']}/{s['flat']} n={s['support']} wr={wr}")
    return f"- {item['ruleGroup']}: `{item['label']}` -> {item['judgement']} / {item['direction']} / " + " / ".join(parts)


def examples_lines(item: dict, limit: int = 3) -> list[str]:
    lines = []
    for ex in item["examples"][:limit]:
        lines.append(
            f"  - {ex['ticker']} {ex['signalDate']} {ex['category']} {ex['signalType']} expected={ex['expected']} T1/T5/T20={ex['t1']}/{ex['t5']}/{ex['t20']}"
        )
    return lines


def build_markdown(rows: list[dict[str, str]], items: list[dict], min_count: int, date: str, source_log: str) -> str:
    judged = [i for i in items if i["judgement"] != "hypothesis_only"]
    by_judgement = Counter(i["judgement"] for i in items)
    lines = [
        f"# {date} Rule Check Summary",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {date}",
        "- mode: rule-check-auto-aggregation",
        f"- sourceLog: {source_log}",
        f"- minCount: {min_count}",
        "- caution: 粗いバックテストの自動集計。発表時刻、流動性、制度信用、イベント裁定は未補正を含む。売買助言ではない。",
        "",
        "## Summary",
        f"- parsedOutcomeRows: {len(rows)}",
        f"- emittedRuleCandidates: {len(items)}",
        f"- reviewableRuleCandidates: {len(judged)}",
    ]
    for key, count in by_judgement.most_common():
        lines.append(f"- {key}: {count}")

    sections = [
        ("Promote Candidates", "promote_candidate"),
        ("Downgrade Or Avoid Candidates", "downgrade_or_avoid_candidate"),
        ("Short Term Only Candidates", "short_term_only_candidate"),
        ("Timeframe Sensitive", "timeframe_sensitive"),
        ("Watch More", "watch_more"),
        ("Hypothesis Only", "hypothesis_only"),
    ]
    for title, key in sections:
        selected = [i for i in items if i["judgement"] == key]
        lines.extend(["", f"## {title}"])
        if not selected:
            lines.append("- none")
            continue
        limit = 20 if key != "hypothesis_only" else 12
        for item in selected[:limit]:
            lines.append(line_for(item))
            lines.extend(examples_lines(item))

    lines.extend([
        "",
        "## How To Use",
        "- `promote_candidate` は暫定ルールへの昇格候補。ただしn<20はまだ仮説寄りで扱う。",
        "- `downgrade_or_avoid_candidate` は買いランクを下げる、またはショート/回避観点へ回す候補。",
        "- `short_term_only_candidate` はT+1/T+5では使えるがT+20で崩れやすい候補。利確/監視期限を短くする。",
        "- `timeframe_sensitive` はデイトレ/スイング/中期で読み方が変わる候補。",
        "- 次回のdailyでは、該当したルール名を `ruleHits` と `rankAdjustmentReason` に残す。",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate rough outcomes into rule-check candidates.")
    parser.add_argument("--min-count", type=int, default=4, help="minimum judged rows required per candidate")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"), help="output date prefix")
    parser.add_argument("--outcome", type=Path, default=None)
    parser.add_argument("--seed-config", type=Path, default=outcomes.DEFAULT_CONFIG)
    parser.add_argument("--seed-list", default=None)
    parser.add_argument("--margin-data", type=Path, default=None)
    parser.add_argument("--session-data", type=Path, default=None)
    parser.add_argument("--market-context-data", type=Path, default=None)
    parser.add_argument("--sector-context-data", type=Path, default=None)
    parser.add_argument("--sector-market-context-data", type=Path, default=None)
    parser.add_argument("--technical-context-data", type=Path, default=None)
    parser.add_argument("--md-output", type=Path, default=None)
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--db-only", action="store_true")
    args = parser.parse_args()

    outcomes.OUTCOME = args.outcome or Path(str(DEFAULT_OUTCOME).format(date=args.date))
    outcomes.BATCH_FILES = outcomes.load_seed_paths(args.seed_config, args.seed_list)
    outcomes.MARGIN_DATA = args.margin_data or Path(str(outcomes.DEFAULT_MARGIN_DATA).format(date=args.date))
    outcomes.SESSION_DATA = args.session_data or Path(str(outcomes.DEFAULT_SESSION_DATA).format(date=args.date))
    outcomes.MARKET_CONTEXT_DATA = args.market_context_data or Path(str(outcomes.DEFAULT_MARKET_CONTEXT_DATA).format(date=args.date))
    outcomes.SECTOR_CONTEXT_DATA = args.sector_context_data or Path(str(outcomes.DEFAULT_SECTOR_CONTEXT_DATA).format(date=args.date))
    outcomes.SECTOR_MARKET_CONTEXT_DATA = args.sector_market_context_data or Path(str(outcomes.DEFAULT_SECTOR_MARKET_CONTEXT_DATA).format(date=args.date))
    outcomes.TECHNICAL_CONTEXT_DATA = args.technical_context_data or Path(str(outcomes.DEFAULT_TECHNICAL_CONTEXT_DATA).format(date=args.date))
    source_log = outcomes.OUTCOME.relative_to(ROOT / "topics/investment-research").as_posix()

    if args.db_only:
        rows = outcomes.parse_outcomes_from_db(args.db, args.date)
    else:
        rows = outcomes.parse_outcomes()
    items = group_rules(rows, args.min_count)
    md_output = args.md_output or Path(str(DEFAULT_MD_OUTPUT).format(date=args.date))
    json_output = args.json_output or Path(str(DEFAULT_JSON_OUTPUT).format(date=args.date))
    md_output.write_text(build_markdown(rows, items, args.min_count, args.date, source_log), encoding="utf-8")
    json_output.write_text(
        json.dumps(
            {
                "date": args.date,
                "mode": "rule-check-auto-aggregation",
                "sourceLog": f"topics/investment-research/{source_log}",
                "minCount": args.min_count,
                "parsedOutcomeRows": len(rows),
                "ruleCandidates": items,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {display_path(md_output)}")
    print(f"wrote {display_path(json_output)}")
    print(f"rows={len(rows)} candidates={len(items)} min_count={args.min_count}")

    conn = sqlite3.connect(args.db)
    try:
        conn.execute("DELETE FROM rule_check_candidates WHERE date=? AND min_count=?", (args.date, args.min_count))
        for idx, item in enumerate(items, 1):
            conn.execute(
                """
                INSERT INTO rule_check_candidates(
                  date,min_count,candidate_index,rule_group,label,judgement,direction,row_count,payload_json,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,datetime('now'))
                """,
                (
                    args.date,
                    args.min_count,
                    idx,
                    item.get("ruleGroup", ""),
                    item.get("label", ""),
                    item.get("judgement", ""),
                    item.get("direction", ""),
                    int(item.get("rowCount") or 0),
                    json.dumps(item, ensure_ascii=False),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
