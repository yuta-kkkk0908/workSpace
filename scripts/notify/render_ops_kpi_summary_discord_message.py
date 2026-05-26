#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "investment.db"
DEFAULT_OUT = ROOT / "prompts" / "ops-kpi-summary-discord-message.txt"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render compact ops KPI summary for Discord")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return p.parse_args()


def load_artifact(conn: sqlite3.Connection, key: str, date_s: str) -> dict:
    row = conn.execute(
        """
        SELECT payload_json
        FROM collection_artifacts
        WHERE artifact_key=? AND artifact_date=?
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (key, date_s),
    ).fetchone()
    if not row or not row[0]:
        return {}
    try:
        return json.loads(str(row[0]))
    except Exception:
        return {}


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    try:
        kpi = load_artifact(conn, "signal_pipeline_kpi", args.date)
        weekly = load_artifact(conn, "weekly_tuning_review", args.date)
        decision = load_artifact(conn, "collection_intensity_decision", args.date)
    finally:
        conn.close()

    f = ((kpi.get("kpi") or {}).get("funnel") or {})
    r = ((kpi.get("kpi") or {}).get("rates_pct") or {})
    wk = weekly.get("kpi") or {}
    dec = decision or {}
    lines = [
        f"OPS KPI Summary ({args.date})",
        f"- Funnel: raw={int(f.get('raw_events', 0))} tdnet={int(f.get('tdnet_disclosures', 0))} signals={int(f.get('signals', 0))} entry={int(f.get('entry_candidates', 0))} scenario={int(f.get('opening_scenarios', 0))}",
        f"- Rates: sig/tdnet={float(r.get('signals_from_tdnet', 0.0)):.1f}% missPrice={float(r.get('price_missing_rate_active_universe', 0.0)):.1f}%",
        f"- Weekly: watch={float(wk.get('watch_ratio_pct', 0.0)):.1f}% lowSample={float(wk.get('low_sample_ratio_pct', 0.0)):.1f}% rejectTop={str(wk.get('dominant_reject_reason') or 'n/a')}",
        f"- Decision(3d): {str(dec.get('decision') or 'n/a')} / businessDay={bool(dec.get('is_business_day', True))}",
        f"- GeneratedAt: {datetime.now().strftime('%Y-%m-%d %H:%M JST')}",
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
