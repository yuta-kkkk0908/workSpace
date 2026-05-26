#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"
JST = timezone(timedelta(hours=9))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Report daily signal pipeline KPI and alerts")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--weekly-lookback-days", type=int, default=7)
    p.add_argument("--conversion-drop-threshold-pct", type=float, default=20.0)
    p.add_argument("--price-missing-threshold-pct", type=float, default=1.0)
    p.add_argument("--output-md", type=Path, default=None)
    return p.parse_args()


def _count(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int((row[0] if row else 0) or 0)


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100.0, 3)


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"db not found: {args.db}")
    d0 = datetime.strptime(args.date, "%Y-%m-%d").date()
    week_start = (d0 - timedelta(days=max(1, args.weekly_lookback_days))).isoformat()
    prev_week_end = (d0 - timedelta(days=1)).isoformat()

    conn = sqlite3.connect(args.db)
    try:
        raw_events_count = _count(conn, "SELECT COUNT(*) FROM raw_events WHERE ingest_date=?", (args.date,))
        tdnet_count = _count(conn, "SELECT COUNT(*) FROM tdnet_disclosures WHERE date=?", (args.date,))
        signals_count = _count(conn, "SELECT COUNT(*) FROM signals WHERE date=?", (args.date,))
        entry_candidates_count = _count(conn, "SELECT COUNT(*) FROM entry_candidates WHERE date=?", (args.date,))
        opening_scenarios_count = _count(conn, "SELECT COUNT(*) FROM opening_scenarios WHERE scenario_date=?", (args.date,))

        signals_from_tdnet = _ratio(signals_count, tdnet_count)
        pipeline_signals_to_candidates = _ratio(entry_candidates_count, signals_count)
        pipeline_candidates_to_scenarios = _ratio(opening_scenarios_count, entry_candidates_count)

        prev_tdnet_sum = _count(
            conn,
            "SELECT COUNT(*) FROM tdnet_disclosures WHERE date BETWEEN ? AND ?",
            (week_start, prev_week_end),
        )
        prev_signals_sum = _count(
            conn,
            "SELECT COUNT(*) FROM signals WHERE date BETWEEN ? AND ?",
            (week_start, prev_week_end),
        )
        prev_signals_from_tdnet = _ratio(prev_signals_sum, prev_tdnet_sum)

        conversion_drop_pct = round(prev_signals_from_tdnet - signals_from_tdnet, 3)
        conversion_alert = conversion_drop_pct >= float(args.conversion_drop_threshold_pct)

        # Price missing rate on today's active universe (signals + tdnet tickers).
        universe_rows = conn.execute(
            """
            SELECT DISTINCT ticker FROM (
              SELECT ticker FROM signals WHERE date=? AND COALESCE(ticker,'')<>''
              UNION
              SELECT ticker FROM tdnet_disclosures WHERE date=? AND COALESCE(ticker,'')<>''
            )
            """,
            (args.date, args.date),
        ).fetchall()
        universe = [str(r[0]) for r in universe_rows if r and r[0]]
        missing = 0
        for t in universe:
            has_price = _count(conn, "SELECT COUNT(*) FROM facts_price_daily WHERE date=? AND ticker=?", (args.date, t)) > 0
            if not has_price:
                missing += 1
        missing_rate_pct = _ratio(missing, len(universe))
        missing_alert = missing_rate_pct > float(args.price_missing_threshold_pct)

        # Type-wise conversion monitoring (early detection of classification leaks).
        type_rows = conn.execute(
            """
            SELECT signal_type, COUNT(*) AS c
            FROM signals
            WHERE date=? AND COALESCE(signal_type,'')<>''
            GROUP BY signal_type
            """,
            (args.date,),
        ).fetchall()
        sig_by_type = {str(r[0]): int(r[1] or 0) for r in type_rows}
        tdnet_type_rows = conn.execute(
            """
            SELECT category, COUNT(*) AS c
            FROM tdnet_disclosures
            WHERE date=? AND COALESCE(category,'')<>''
            GROUP BY category
            """,
            (args.date,),
        ).fetchall()
        tdnet_by_type = {str(r[0]): int(r[1] or 0) for r in tdnet_type_rows}
        material_types = sorted(set(sig_by_type.keys()) | set(tdnet_by_type.keys()))
        rates_by_type: dict[str, dict[str, float | int | bool]] = {}
        type_alerts: list[str] = []
        for t in material_types:
            s_cnt = int(sig_by_type.get(t, 0))
            d_cnt = int(tdnet_by_type.get(t, 0))
            rate = _ratio(s_cnt, d_cnt)
            prev_d = _count(
                conn,
                "SELECT COUNT(*) FROM tdnet_disclosures WHERE date BETWEEN ? AND ? AND COALESCE(category,'')=?",
                (week_start, prev_week_end, t),
            )
            prev_s = _count(
                conn,
                "SELECT COUNT(*) FROM signals WHERE date BETWEEN ? AND ? AND COALESCE(signal_type,'')=?",
                (week_start, prev_week_end, t),
            )
            prev_rate = _ratio(prev_s, prev_d)
            drop = round(prev_rate - rate, 3)
            fired = (d_cnt >= 3) and (drop >= float(args.conversion_drop_threshold_pct))
            rates_by_type[t] = {
                "tdnet_count": d_cnt,
                "signal_count": s_cnt,
                "rate_pct": rate,
                "prev_rate_pct": prev_rate,
                "drop_pct": drop,
                "alert_fired": fired,
            }
            if fired:
                type_alerts.append(f"{t}: drop={drop:.3f}% (today={rate:.3f} prev={prev_rate:.3f})")

        payload = {
            "date": args.date,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "kpi": {
                "funnel": {
                    "raw_events": raw_events_count,
                    "tdnet_disclosures": tdnet_count,
                    "signals": signals_count,
                    "entry_candidates": entry_candidates_count,
                    "opening_scenarios": opening_scenarios_count,
                },
                "rates_pct": {
                    "signals_from_tdnet": signals_from_tdnet,
                    "signals_to_entry_candidates": pipeline_signals_to_candidates,
                    "entry_candidates_to_opening_scenarios": pipeline_candidates_to_scenarios,
                    "price_missing_rate_active_universe": missing_rate_pct,
                },
                "baseline": {
                    "weekly_lookback_days": int(args.weekly_lookback_days),
                    "signals_from_tdnet_prev_window": prev_signals_from_tdnet,
                    "signals_from_tdnet_drop_pct": conversion_drop_pct,
                },
                "rates_by_type": rates_by_type,
            },
            "alerts": {
                "conversion_drop": {
                    "fired": conversion_alert,
                    "threshold_pct": float(args.conversion_drop_threshold_pct),
                },
                "price_missing_rate": {
                    "fired": missing_alert,
                    "threshold_pct": float(args.price_missing_threshold_pct),
                    "missing_tickers": missing,
                    "active_universe_tickers": len(universe),
                },
                "conversion_drop_by_type": {
                    "fired": len(type_alerts) > 0,
                    "items": type_alerts,
                    "threshold_pct": float(args.conversion_drop_threshold_pct),
                },
            },
        }

        conn.execute(
            """
            INSERT INTO collection_artifacts(artifact_key,artifact_date,artifact_type,payload_json,updated_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(artifact_key,artifact_date) DO UPDATE SET
              artifact_type=excluded.artifact_type,
              payload_json=excluded.payload_json,
              updated_at=excluded.updated_at
            """,
            (
                "signal_pipeline_kpi",
                args.date,
                "pipeline_kpi",
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                payload["generated_at"],
            ),
        )
        conn.commit()
    finally:
        conn.close()

    output_md = args.output_md or (ROOT / "topics" / "investment-research" / "inbox" / f"{args.date}-signal-pipeline-kpi.md")
    lines = [
        f"# {args.date} Signal Pipeline KPI",
        "",
        "## Funnel",
        f"- raw_events: {payload['kpi']['funnel']['raw_events']}",
        f"- tdnet_disclosures: {payload['kpi']['funnel']['tdnet_disclosures']}",
        f"- signals: {payload['kpi']['funnel']['signals']}",
        f"- entry_candidates: {payload['kpi']['funnel']['entry_candidates']}",
        f"- opening_scenarios: {payload['kpi']['funnel']['opening_scenarios']}",
        "",
        "## Rates (%)",
        f"- signals_from_tdnet: {payload['kpi']['rates_pct']['signals_from_tdnet']:.3f}",
        f"- signals_to_entry_candidates: {payload['kpi']['rates_pct']['signals_to_entry_candidates']:.3f}",
        f"- entry_candidates_to_opening_scenarios: {payload['kpi']['rates_pct']['entry_candidates_to_opening_scenarios']:.3f}",
        f"- price_missing_rate_active_universe: {payload['kpi']['rates_pct']['price_missing_rate_active_universe']:.3f}",
        "",
        "## Alerts",
        f"- conversion_drop: {'ALERT' if payload['alerts']['conversion_drop']['fired'] else 'OK'} "
        f"(drop={payload['kpi']['baseline']['signals_from_tdnet_drop_pct']:.3f} / threshold={payload['alerts']['conversion_drop']['threshold_pct']:.3f})",
        f"- price_missing_rate: {'ALERT' if payload['alerts']['price_missing_rate']['fired'] else 'OK'} "
        f"(missing={payload['alerts']['price_missing_rate']['missing_tickers']}/{payload['alerts']['price_missing_rate']['active_universe_tickers']} "
        f"threshold={payload['alerts']['price_missing_rate']['threshold_pct']:.3f}%)",
    ]
    if type_alerts:
        lines.extend(["", "## Type Alerts"])
        lines.extend([f"- {x}" for x in type_alerts[:12]])
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"signal_pipeline_kpi date={args.date} wrote={output_md.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
