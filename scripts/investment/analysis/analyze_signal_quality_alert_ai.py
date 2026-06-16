#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.platform_core_bootstrap import ensure_platform_core_importable

ensure_platform_core_importable()
from utils.investment_db_path import resolve_investment_db
from platform_core.model_router import resolve_model
from platform_core.openai_client import call_openai_text

DEFAULT_DB = resolve_investment_db()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AI triage for signal quality alerts")
    p.add_argument("--date", required=True)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--model-route", default="signal_quality_alert_analysis")
    return p.parse_args()


def load_metrics(date_s: str) -> dict:
    p = ROOT / "prompts" / "signal-quality-metrics.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if str(data.get("date", "")) != date_s:
        return {}
    return data if isinstance(data, dict) else {}


def save_artifact(db: Path, date_s: str, payload: dict) -> None:
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """
            INSERT INTO collection_artifacts(artifact_key,artifact_date,artifact_type,payload_json,updated_at)
            VALUES(?,?,?,?,datetime('now'))
            ON CONFLICT(artifact_key,artifact_date) DO UPDATE SET
              payload_json=excluded.payload_json,
              updated_at=excluded.updated_at
            """,
            ("signal_quality_ai_triage", date_s, "ai_analysis", json.dumps(payload, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    args = parse_args()
    m = load_metrics(args.date)
    if not m or str(m.get("status", "OK")).upper() != "ALERT":
        print("skip: signal quality alert not active")
        return 0
    if not os.getenv("OPENAI_API_KEY", "").strip():
        print("skip: OPENAI_API_KEY is empty")
        return 0
    provider, model = resolve_model(args.model_route)
    if provider != "openai":
        print(f"skip: provider unsupported {provider}")
        return 0
    prompt = json.dumps(
        {
            "date": args.date,
            "alerts": m.get("alerts", []),
            "reasonCodes": m.get("qualityReasonCodes", []),
            "counts": {
                "signalCount": m.get("signalCount"),
                "upCount": m.get("upCount"),
                "downCount": m.get("downCount"),
                "gatePassCount": m.get("gatePassCount"),
                "gateHoldCount": m.get("gateHoldCount"),
            },
        },
        ensure_ascii=False,
        indent=2,
    )
    try:
        text, raw = call_openai_text(
            model=model,
            system_text="あなたは投資シグナル運用のSRE兼アナリストです。売買助言はしません。",
            user_text=(
                "次のアラートを運用目線で triage してください。"
                "1) root cause 2) 直近の対処 3) 翌営業日の再発防止 を短く箇条書きで。"
                f"\n\n{prompt}"
            ),
        )
    except Exception as exc:
        print(f"skip: OpenAI triage unavailable: {exc}")
        return 0
    payload = {"date": args.date, "provider": provider, "model": model, "analysis": text, "raw": raw}
    try:
        save_artifact(args.db, args.date, payload)
    except Exception as exc:
        print(f"skip: failed to save triage artifact: {exc}")
        return 0
    print(f"saved: collection_artifacts signal_quality_ai_triage {args.date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
