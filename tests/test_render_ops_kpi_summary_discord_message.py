import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.notify import render_ops_kpi_summary_discord_message as mod


class RenderOpsKpiSummaryDiscordMessageTests(unittest.TestCase):
    def test_render_includes_runtime_failures_and_sample_trend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "investment.db"
            out_path = Path(tmp) / "message.txt"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE collection_artifacts (
                  artifact_key TEXT NOT NULL,
                  artifact_date TEXT NOT NULL,
                  artifact_type TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  PRIMARY KEY(artifact_key, artifact_date)
                );
                CREATE TABLE pipeline_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  event_time TEXT NOT NULL,
                  event_date TEXT NOT NULL,
                  pipeline TEXT NOT NULL,
                  slot TEXT,
                  stage TEXT,
                  level TEXT NOT NULL DEFAULT 'info',
                  status TEXT,
                  command TEXT,
                  return_code INTEGER,
                  duration_ms INTEGER,
                  payload_json TEXT,
                  source_path TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "INSERT INTO collection_artifacts VALUES(?,?,?,?,?)",
                (
                    "signal_pipeline_kpi",
                    "2026-05-29",
                    "pipeline_kpi",
                    json.dumps(
                        {
                            "kpi": {
                                "funnel": {
                                    "raw_events": 10,
                                    "tdnet_disclosures": 8,
                                    "signals": 4,
                                    "entry_candidates": 3,
                                    "opening_scenarios": 1,
                                },
                                "rates_pct": {
                                    "signals_from_tdnet": 50.0,
                                    "price_missing_rate_active_universe": 0.0,
                                },
                            },
                            "alerts": {
                                "conversion_drop": {"fired": False},
                                "price_missing_rate": {"fired": False},
                                "conversion_drop_by_type": {"fired": False},
                            },
                        }
                    ),
                    "2026-05-29T12:00:00Z",
                ),
            )
            conn.execute(
                "INSERT INTO collection_artifacts VALUES(?,?,?,?,?)",
                (
                    "signal_pipeline_kpi",
                    "2026-05-30",
                    "pipeline_kpi",
                    json.dumps(
                        {
                            "kpi": {
                                "funnel": {
                                    "raw_events": 18,
                                    "tdnet_disclosures": 12,
                                    "signals": 9,
                                    "entry_candidates": 6,
                                    "opening_scenarios": 3,
                                },
                                "rates_pct": {
                                    "signals_from_tdnet": 75.0,
                                    "price_missing_rate_active_universe": 2.5,
                                },
                            },
                            "alerts": {
                                "conversion_drop": {"fired": False},
                                "price_missing_rate": {"fired": True},
                                "conversion_drop_by_type": {"fired": False},
                            },
                        }
                    ),
                    "2026-05-30T12:00:00Z",
                ),
            )
            conn.execute(
                "INSERT INTO collection_artifacts VALUES(?,?,?,?,?)",
                (
                    "weekly_tuning_review",
                    "2026-05-30",
                    "weekly_review",
                    json.dumps({"kpi": {"watch_ratio_pct": 33.3, "low_sample_ratio_pct": 20.0, "dominant_reject_reason": "sample_low"}}),
                    "2026-05-30T12:00:00Z",
                ),
            )
            conn.execute(
                "INSERT INTO collection_artifacts VALUES(?,?,?,?,?)",
                (
                    "collection_intensity_decision",
                    "2026-05-30",
                    "decision",
                    json.dumps({"decision": "maintain", "is_business_day": True}),
                    "2026-05-30T12:00:00Z",
                ),
            )
            events = [
                (
                    "2026-05-30T10:00:00Z",
                    "2026-05-30",
                    "ops_scheduler",
                    "night",
                    "slot",
                    "info",
                    "start",
                    None,
                    0,
                    None,
                    json.dumps({"backtest": False}),
                    "scripts/run_ops_scheduler.py",
                    "2026-05-30T10:00:00Z",
                ),
                (
                    "2026-05-30T10:01:00Z",
                    "2026-05-30",
                    "ops_scheduler",
                    "night",
                    "collect_generic_daily_topics.py",
                    "info",
                    "ok",
                    "python collect",
                    0,
                    1000,
                    json.dumps({"error_category": "ok"}),
                    "scripts/run_ops_scheduler.py",
                    "2026-05-30T10:01:00Z",
                ),
                (
                    "2026-05-30T10:03:00Z",
                    "2026-05-30",
                    "ops_scheduler",
                    "night",
                    "ingest_topics_db.py",
                    "info",
                    "error",
                    "python ingest",
                    2,
                    1000,
                    json.dumps({"error_category": "db_error"}),
                    "scripts/run_ops_scheduler.py",
                    "2026-05-30T10:03:00Z",
                ),
                (
                    "2026-05-30T10:05:00Z",
                    "2026-05-30",
                    "ops_scheduler",
                    "night",
                    "slot",
                    "info",
                    "done_with_error",
                    None,
                    0,
                    None,
                    json.dumps({"final_rc": 2, "backtest": False}),
                    "scripts/run_ops_scheduler.py",
                    "2026-05-30T10:05:00Z",
                ),
                (
                    "2026-05-29T08:10:00Z",
                    "2026-05-29",
                    "investment_analysis",
                    "inv-scenario",
                    "report_samplecount_trade_trend",
                    "info",
                    "ok",
                    None,
                    0,
                    None,
                    json.dumps(
                        {
                            "summary": {
                                "firstHalfRatio": 0.2,
                                "secondHalfRatio": 0.4,
                                "trendDelta": 0.2,
                            }
                        }
                    ),
                    "scripts/investment/analysis/report_samplecount_trade_trend.py",
                    "2026-05-29T08:10:00Z",
                ),
            ]
            conn.executemany(
                """
                INSERT INTO pipeline_events(
                  event_time,event_date,pipeline,slot,stage,level,status,command,return_code,duration_ms,payload_json,source_path,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                events,
            )
            conn.commit()
            conn.close()

            argv = [
                "render_ops_kpi_summary_discord_message.py",
                "--date",
                "2026-05-30",
                "--db",
                str(db_path),
                "--out",
                str(out_path),
            ]
            with patch.object(sys, "argv", argv):
                rc = mod.main()
            self.assertEqual(rc, 0)
            text = out_path.read_text(encoding="utf-8")
            self.assertIn("OPS Night Watch (2026-05-30)", text)
            self.assertIn("Runtime: done_with_error / 5m / commands=2 error=1", text)
            self.assertIn("Trend: signals +5 / become +2", text)
            self.assertIn("alerts=price miss", text)
            self.assertIn("Sample: 20.0%->40.0% (+20.0pt) @2026-05-29", text)
            self.assertIn("Failures: ingest_topics_db.py(rc=2, db_error)", text)


if __name__ == "__main__":
    unittest.main()
