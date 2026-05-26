#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"
OUT = ROOT / "topics" / "investment-research" / "inbox"

MATERIAL_TYPES = [
    "upward_revision_highest_profit",
    "highest_profit_guidance_dividend_revision",
    "downward_revision_to_loss",
    "downward_revision_dividend_cut",
    "weak_earnings_or_guidance",
    "offering_or_dilution",
]
MATERIAL_COUNT_SOURCE = {
    # offering系は outcomes経路が薄いため、TDNET分類母数を採用
    "offering_or_dilution": "tdnet_disclosures",
}

SIGNAL_TYPE_ALIASES = {
    "dividend_cut": "downward_revision_dividend_cut",
    "downward_revision / dividend_revision": "downward_revision_dividend_cut",
    "earnings_revision_down / dividend_revision": "downward_revision_dividend_cut",
    "downward_revision": "weak_earnings_or_guidance",
    "earnings_negative": "weak_earnings_or_guidance",
}


def normalize_signal_type_name(v: str) -> str:
    s = (v or "").strip()
    if not s:
        return "(empty)"
    key = s.lower()
    return SIGNAL_TYPE_ALIASES.get(key, s)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Report signal_type coverage for sample-growth operations")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--window-days", type=int, default=30)
    p.add_argument("--min-material-count", type=int, default=20)
    p.add_argument(
        "--shortage-ratio",
        type=float,
        default=0.95,
        help="mark shortage only when count < min_material_count * ratio (default: 0.95)",
    )
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=False, help="write md/json audit artifacts")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    shortage_threshold = max(1, int(round(max(0.1, min(args.shortage_ratio, 1.0)) * max(1, args.min_material_count))))
    conn = sqlite3.connect(args.db)
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM backtest_outcomes WHERE signal_date>=date(?, ?)",
            (args.date, f"-{max(1, args.window_days)} day"),
        ).fetchone()[0]
        rows = conn.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(signal_type),''),'(empty)') AS signal_type, COUNT(*) AS n
            FROM backtest_outcomes
            WHERE signal_date>=date(?, ?)
            GROUP BY signal_type
            ORDER BY n DESC, signal_type
            """,
            (args.date, f"-{max(1, args.window_days)} day"),
        ).fetchall()
        counts_raw: dict[str, int] = {}
        for t, n in rows:
            st = normalize_signal_type_name(str(t))
            counts_raw[st] = counts_raw.get(st, 0) + int(n)
        counts = counts_raw
        rows_signals = conn.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(signal_type),''),'(empty)') AS signal_type, COUNT(*) AS n
            FROM signals
            WHERE date>=date(?, ?)
            GROUP BY signal_type
            """,
            (args.date, f"-{max(1, args.window_days)} day"),
        ).fetchall()
        signal_counts: dict[str, int] = {}
        for t, n in rows_signals:
            st = normalize_signal_type_name(str(t))
            signal_counts[st] = signal_counts.get(st, 0) + int(n)
        rows_tdnet = conn.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(category),''),'(empty)') AS signal_type, COUNT(*) AS n
            FROM tdnet_disclosures
            WHERE date>=date(?, ?)
            GROUP BY signal_type
            """,
            (args.date, f"-{max(1, args.window_days)} day"),
        ).fetchall()
        tdnet_counts: dict[str, int] = {}
        for t, n in rows_tdnet:
            st = normalize_signal_type_name(str(t))
            tdnet_counts[st] = tdnet_counts.get(st, 0) + int(n)
        for t in MATERIAL_TYPES:
            src = MATERIAL_COUNT_SOURCE.get(t)
            if src == "signals":
                counts[t] = int(signal_counts.get(t, 0))
            elif src == "tdnet_disclosures":
                counts[t] = int(tdnet_counts.get(t, 0))
            else:
                counts.setdefault(t, 0)
        items = [{"signal_type": t, "count": n} for t, n in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_type_coverage_rows (
              date TEXT NOT NULL,
              window_days INTEGER NOT NULL,
              signal_type TEXT NOT NULL,
              signal_count INTEGER NOT NULL,
              is_material INTEGER NOT NULL DEFAULT 0,
              is_shortage INTEGER NOT NULL DEFAULT 0,
              min_material_count INTEGER NOT NULL DEFAULT 0,
              source_path TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY(date, window_days, signal_type)
            )
            """
        )
        conn.execute(
            "DELETE FROM signal_type_coverage_rows WHERE date=? AND window_days=?",
            (args.date, int(args.window_days)),
        )
        for x in items:
            st = x["signal_type"]
            n = int(x["count"])
            is_mat = 1 if st in MATERIAL_TYPES else 0
            is_short = 1 if (is_mat and n < shortage_threshold) else 0
            conn.execute(
                """
                INSERT INTO signal_type_coverage_rows(
                  date, window_days, signal_type, signal_count, is_material, is_shortage, min_material_count, source_path, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,datetime('now'))
                """,
                (
                    args.date,
                    int(args.window_days),
                    st,
                    n,
                    is_mat,
                    is_short,
                    int(args.min_material_count),
                    (
                        "db:signals"
                        if MATERIAL_COUNT_SOURCE.get(st) == "signals"
                        else "db:tdnet_disclosures"
                        if MATERIAL_COUNT_SOURCE.get(st) == "tdnet_disclosures"
                        else "db:backtest_outcomes"
                    ),
                ),
            )
        conn.commit()
    finally:
        conn.close()

    m = {x["signal_type"]: x["count"] for x in items}
    material = [{"signal_type": t, "count": int(m.get(t, 0))} for t in MATERIAL_TYPES]
    shortages = [x for x in material if x["count"] < shortage_threshold]
    near_shortages = [
        x for x in material if shortage_threshold <= x["count"] < max(1, args.min_material_count)
    ]

    payload = {
        "date": args.date,
        "windowDays": args.window_days,
        "totalSignals": int(total or 0),
        "uniqueSignalTypes": len(items),
        "minMaterialCount": args.min_material_count,
        "shortageRatio": args.shortage_ratio,
        "shortageThresholdCount": shortage_threshold,
        "materialCoverage": material,
        "materialShortages": shortages,
        "materialNearShortages": near_shortages,
        "topTypes": items[:20],
    }

    if args.write_files:
        out_json = OUT / f"{args.date}-signal-type-coverage.json"
        out_md = OUT / f"{args.date}-signal-type-coverage.md"
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        lines = [
            f"# {args.date} Signal Type Coverage",
            "",
            f"- windowDays: {args.window_days}",
            f"- totalSignals: {payload['totalSignals']}",
            f"- uniqueSignalTypes: {payload['uniqueSignalTypes']}",
            f"- materialMinCount: {args.min_material_count}",
            "",
            "## Material Coverage",
        ]
        for x in material:
            mark = "不足" if x["count"] < args.min_material_count else "OK"
            lines.append(f"- {x['signal_type']}: {x['count']} ({mark})")
        lines.extend(["", "## Top Types"])
        for x in payload["topTypes"]:
            lines.append(f"- {x['signal_type']}: {x['count']}")
        out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {out_md.relative_to(ROOT)}")
        print(f"wrote {out_json.relative_to(ROOT)}")

    print(
        "coverage_db_updated date={0} window={1} total={2} unique={3} shortages={4}".format(
            args.date,
            args.window_days,
            payload["totalSignals"],
            payload["uniqueSignalTypes"],
            len(shortages),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
