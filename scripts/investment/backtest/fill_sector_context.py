#!/usr/bin/env python3
"""Create rough sector/profile metadata for investment outcome rows.

This first layer is intentionally static. It does not claim sector index
performance; it makes cross-factor analysis possible by grouping tickers into
business/market-sensitivity buckets.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
JST = timezone(timedelta(hours=9))
DEFAULT_OUTPUT = ROOT / "topics/investment-research/inbox/{date}-sector-context-data.json"
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db
from utils.sector_inference import infer_sector_context

DEFAULT_DB = resolve_investment_db()

sys.path.insert(0, str(ROOT / "scripts/investment/analysis"))
import analyze_market_outcomes as outcomes  # noqa: E402


SECTOR_BY_TICKER = {
    "1941": ("construction_infrastructure", "domestic_defensive_order_sensitive"),
    "1944": ("construction_infrastructure", "domestic_defensive_order_sensitive"),
    "2183": ("healthcare_services", "defensive_growth_sensitive"),
    "2413": ("healthcare_services", "defensive_growth_sensitive"),
    "2503": ("food_beverage", "domestic_defensive"),
    "2801": ("food_beverage", "domestic_defensive"),
    "2892": ("food_beverage", "domestic_defensive"),
    "2901": ("food_beverage", "domestic_defensive"),
    "2975": ("real_estate", "rate_sensitive"),
    "2998": ("real_estate", "rate_sensitive"),
    "3086": ("retail_consumer", "domestic_consumption_sensitive"),
    "3087": ("retail_consumer", "domestic_consumption_sensitive"),
    "3131": ("electronics_trading", "semiconductor_cycle_sensitive"),
    "3475": ("real_estate", "rate_sensitive"),
    "3480": ("real_estate", "rate_sensitive"),
    "3491": ("real_estate", "rate_sensitive"),
    "3547": ("retail_consumer", "domestic_consumption_sensitive"),
    "3549": ("drugstore_retail", "domestic_consumption_sensitive"),
    "3656": ("internet_media_game", "growth_sensitive"),
    "3694": ("software_it", "growth_sensitive"),
    "3773": ("software_it", "growth_sensitive"),
    "3825": ("crypto_fintech", "risk_appetite_sensitive"),
    "3856": ("renewable_energy", "policy_rate_sensitive"),
    "3923": ("software_it", "growth_sensitive"),
    "3928": ("internet_media_game", "growth_sensitive"),
    "4043": ("materials_chemicals", "cyclical_input_cost_sensitive"),
    "4182": ("materials_chemicals", "cyclical_input_cost_sensitive"),
    "4187": ("materials_chemicals", "cyclical_input_cost_sensitive"),
    "4246": ("auto_parts", "export_fx_cyclical"),
    "4258": ("cybersecurity_it", "growth_sensitive"),
    "4299": ("software_it", "growth_sensitive"),
    "4307": ("software_it", "growth_sensitive"),
    "4356": ("engineering_it", "domestic_order_sensitive"),
    "4417": ("software_it", "growth_sensitive"),
    "4434": ("cloud_it_services", "growth_sensitive"),
    "4596": ("biotech", "binary_event_sensitive"),
    "4615": ("materials_chemicals", "cyclical_input_cost_sensitive"),
    "4658": ("facility_services", "domestic_defensive_order_sensitive"),
    "4666": ("parking_mobility", "domestic_consumption_sensitive"),
    "4676": ("internet_media_ad", "ad_cycle_sensitive"),
    "4751": ("internet_media_ad", "ad_cycle_sensitive"),
    "4762": ("software_it", "growth_sensitive"),
    "4922": ("consumer_goods", "domestic_consumption_sensitive"),
    "5121": ("rubber_industrial", "cyclical_input_cost_sensitive"),
    "5136": ("software_it", "growth_sensitive"),
    "5218": ("materials_chemicals", "cyclical_input_cost_sensitive"),
    "5243": ("software_it", "growth_sensitive"),
    "5250": ("software_it", "growth_sensitive"),
    "5254": ("software_it", "growth_sensitive"),
    "5576": ("software_it", "growth_sensitive"),
    "5943": ("housing_equipment", "domestic_consumption_sensitive"),
    "6071": ("matching_services", "domestic_service_cycle"),
    "6083": ("inspection_services", "domestic_defensive_order_sensitive"),
    "6103": ("machinery_capital_goods", "export_fx_cyclical"),
    "6135": ("machinery_capital_goods", "export_fx_cyclical"),
    "6258": ("machinery_capital_goods", "export_fx_cyclical"),
    "6292": ("machinery_capital_goods", "cyclical_input_cost_sensitive"),
    "6326": ("machinery_capital_goods", "export_fx_cyclical"),
    "6335": ("machinery_capital_goods", "domestic_order_sensitive"),
    "6492": ("machinery_capital_goods", "domestic_order_sensitive"),
    "6532": ("consulting_services", "growth_sensitive"),
    "6734": ("electronics_components", "export_fx_cyclical"),
    "6762": ("electronics_components", "export_fx_cyclical"),
    "6809": ("electronics_equipment", "domestic_order_sensitive"),
    "6862": ("semiconductor_equipment", "semiconductor_cycle_sensitive"),
    "6867": ("electronics_equipment", "export_fx_cyclical"),
    "6951": ("precision_electronics", "semiconductor_cycle_sensitive"),
    "6954": ("machinery_capital_goods", "export_fx_cyclical"),
    "6986": ("electronics_components", "export_fx_cyclical"),
    "7031": ("business_process_services", "domestic_service_cycle"),
    "7065": ("software_it", "growth_sensitive"),
    "7112": ("apparel_retail", "domestic_consumption_sensitive"),
    "7131": ("retail_consumer", "domestic_consumption_sensitive"),
    "7236": ("auto_parts", "export_fx_cyclical"),
    "7282": ("auto_parts", "export_fx_cyclical"),
    "7422": ("apparel_wholesale", "domestic_consumption_sensitive"),
    "7453": ("retail_consumer", "domestic_consumption_sensitive"),
    "7456": ("materials_trading", "cyclical_input_cost_sensitive"),
    "7545": ("retail_consumer", "domestic_consumption_sensitive"),
    "7564": ("retail_consumer", "domestic_consumption_sensitive"),
    "7725": ("semiconductor_equipment", "semiconductor_cycle_sensitive"),
    "7747": ("medical_devices", "defensive_growth_sensitive"),
    "7804": ("printing_ad_services", "domestic_service_cycle"),
    "7975": ("consumer_goods", "domestic_consumption_sensitive"),
    "7984": ("office_stationery", "domestic_consumption_sensitive"),
    "8107": ("apparel_retail", "domestic_consumption_sensitive"),
    "8129": ("healthcare_wholesale", "domestic_defensive"),
    "8267": ("retail_consumer", "domestic_consumption_sensitive"),
    "8630": ("insurance_financial", "rate_sensitive_financial"),
    "8704": ("securities_fintech", "market_volume_sensitive"),
    "8725": ("insurance_financial", "rate_sensitive_financial"),
    "8766": ("insurance_financial", "rate_sensitive_financial"),
    "8789": ("finance", "rate_sensitive_financial"),
    "9101": ("shipping_logistics", "global_trade_sensitive"),
    "9168": ("consumer_services", "domestic_service_cycle"),
    "9270": ("reuse_retail", "domestic_consumption_sensitive"),
    "9279": ("retail_consumer", "domestic_consumption_sensitive"),
    "9310": ("logistics", "global_trade_sensitive"),
    "9330": ("marketing_hr_services", "domestic_service_cycle"),
    "9366": ("logistics", "global_trade_sensitive"),
    "9678": ("rental_construction_equipment", "domestic_order_sensitive"),
    "9682": ("software_it", "growth_sensitive"),
    "9716": ("software_it", "growth_sensitive"),
    "9755": ("geology_infrastructure", "domestic_defensive_order_sensitive"),
}


def fallback(row: dict[str, str]) -> tuple[str, str, str]:
    return infer_sector_context(row.get("title", ""), row.get("category", ""), row.get("signalType", ""), row.get("company", ""))


def load_signal_rows(conn: sqlite3.Connection, date_s: str) -> list[dict[str, str]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT s.ticker,
               s.company,
               s.signal_type,
               s.source,
               COALESCE(
                 (
                   SELECT t.title
                   FROM tdnet_disclosures t
                   WHERE t.ticker=s.ticker
                     AND t.date<=?
                     AND COALESCE(NULLIF(TRIM(t.title),''),'')<>''
                   ORDER BY t.date DESC, t.disclosed_at DESC
                   LIMIT 1
                 ),
                 ''
               ) AS title
        FROM signals s
        WHERE s.date=?
          AND COALESCE(NULLIF(TRIM(s.ticker),''),'')<>''
        ORDER BY s.ticker, s.signal_id
        """,
        (date_s, date_s),
    ).fetchall()
    grouped: dict[str, dict[str, str]] = {}
    for r in rows:
        ticker = str(r["ticker"] or "").strip()
        if not ticker:
            continue
        bucket = grouped.setdefault(
            ticker,
            {
                "ticker": ticker,
                "company": "",
                "signalType": "",
                "title": "",
                "category": "",
            },
        )
        company = str(r["company"] or "").strip()
        if company and not bucket["company"]:
            bucket["company"] = company
        signal_type = str(r["signal_type"] or "").strip()
        if signal_type:
            cur = {x.strip() for x in bucket["signalType"].split(" / ") if x.strip()}
            if signal_type not in cur:
                bucket["signalType"] = " / ".join(sorted([*cur, signal_type])) if cur else signal_type
        title = str(r["title"] or "").strip()
        if title and not bucket["title"]:
            bucket["title"] = title
    return list(grouped.values())


def sector_confidence_rank(v: str) -> int:
    s = str(v or "").strip().lower()
    if s == "manual_static_map":
        return 3
    if s.startswith("keyword_") or s.startswith("fallback_"):
        return 2
    if s and s != "unknown":
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Create rough sector/profile metadata.")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    parser.add_argument("--outcome", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    output = args.output or Path(str(DEFAULT_OUTPUT).format(date=args.date))
    outcomes.OUTCOME = args.outcome or Path(str(outcomes.DEFAULT_OUTPUT).format(date=args.date))

    rows = outcomes.parse_outcomes_from_db(args.db, args.date)
    source_label = "backtest_outcomes"
    if not rows:
        conn = sqlite3.connect(args.db)
        try:
            rows = load_signal_rows(conn, args.date)
            source_label = "signals"
        finally:
            conn.close()
    seen: dict[str, dict[str, str]] = {}
    for row in rows:
        ticker = row["ticker"]
        if ticker in SECTOR_BY_TICKER:
            sector_group, profile = SECTOR_BY_TICKER[ticker]
            confidence = "manual_static_map"
        else:
            sector_group, profile, confidence = fallback(row)
        cur = {
            "ticker": ticker,
            "sectorGroup": sector_group,
            "sectorProfile": profile,
            "confidence": confidence,
        }
        seen[ticker] = cur

    signal_rows: list[dict[str, str]] = []
    conn = sqlite3.connect(args.db)
    try:
        signal_rows = load_signal_rows(conn, args.date)
    finally:
        conn.close()
    for row in signal_rows:
        ticker = row["ticker"]
        if ticker in SECTOR_BY_TICKER:
            sector_group, profile = SECTOR_BY_TICKER[ticker]
            confidence = "manual_static_map"
        else:
            sector_group, profile, confidence = fallback(row)
        cur = {
            "ticker": ticker,
            "sectorGroup": sector_group,
            "sectorProfile": profile,
            "confidence": confidence,
        }
        prev = seen.get(ticker)
        if prev is None or sector_confidence_rank(confidence) >= sector_confidence_rank(prev.get("confidence", "")):
            seen[ticker] = cur
    out_rows = list(seen.values())
    output.write_text(json.dumps({
        "date": args.date,
        "source": f"manual static sector map for rough backtest grouping ({source_label}+signals)",
        "caution": "セクター指数の実績ではなく、銘柄属性/地合い感応度の粗分類。売買助言ではない。",
        "rows": sorted(out_rows, key=lambda r: r["ticker"]),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    conn = sqlite3.connect(args.db)
    try:
        conn.execute("DELETE FROM sector_context_rows WHERE date=?", (args.date,))
        for r in out_rows:
            conn.execute(
                """
                INSERT INTO sector_context_rows(
                  date,ticker,sector_group,sector_profile,confidence,source_path,updated_at
                ) VALUES(?,?,?,?,?,?,datetime('now'))
                """,
                (
                    args.date,
                    r.get("ticker", ""),
                    r.get("sectorGroup", ""),
                    r.get("sectorProfile", ""),
                    r.get("confidence", ""),
                    str(output.relative_to(ROOT)),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    print(f"wrote {output.relative_to(ROOT)} rows={len(out_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
