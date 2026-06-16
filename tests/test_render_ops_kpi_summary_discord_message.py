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
                    "collection_kpi_target_200",
                    "2026-05-30",
                    "kpi_alert",
                    json.dumps(
                        {
                            "date": "2026-05-30",
                            "generated_at": "2026-05-30T12:00:00Z",
                            "kpi": {
                                "jpx_coverage_pct": 100.0,
                                "jpx_coverage_level": "OK",
                                "bars_coverage_pct": 55.0,
                                "bars_coverage_level": "WARN",
                                "tdnet_rows": 12,
                                "error_rate_pct": 12.0,
                                "error_rate_level": "WARN",
                                "target_bars": 200,
                                "ready_tickers": 11,
                                "tracked_tickers": 20,
                            },
                        }
                    ),
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

            inbox = Path(tmp) / "topics" / "investment-research" / "inbox"
            inbox.mkdir(parents=True, exist_ok=True)
            (inbox / "2026-05-30-sample-health-kpi.json").write_text(
                json.dumps(
                    {
                        "date": "2026-05-30",
                        "kpi": {
                            "outcomesTotal": 10,
                            "outcomesPendingAll": 4,
                            "outcomesJudgedAny": 6,
                            "pendingAllRatio": 0.4,
                            "judgedAnyRatio": 0.6,
                            "acceptedScenarios": 5,
                            "effectiveSampleThreshold": 3,
                            "effectiveSampleCount": 2,
                            "effectiveSampleRatio": 0.4,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (inbox / "2026-05-30-decision-support-diff.json").write_text(
                json.dumps(
                    {
                        "date": "2026-05-30",
                        "current": {
                            "acceptedCount": 9,
                        },
                        "previous": {
                            "acceptedCount": 12,
                        },
                        "diff": {
                            "winRateDeltaPp": -3.4,
                            "ddApproxDeltaPp": -1.2,
                            "acceptedDropRatio": 0.25,
                            "improved": False,
                        },
                        "warnings": ["accepted_drop", "winrate_drop"],
                        "status": "warning",
                    }
                ),
                encoding="utf-8",
            )

            argv = [
                "render_ops_kpi_summary_discord_message.py",
                "--date",
                "2026-05-30",
                "--db",
                str(db_path),
                "--out",
                str(out_path),
            ]
            with patch.object(sys, "argv", argv), patch.object(mod, "ROOT", Path(tmp)):
                rc = mod.main()
            self.assertEqual(rc, 0)
            text = out_path.read_text(encoding="utf-8")
            self.assertIn("夜間ボトルネック観測 (2026-05-30)", text)
            self.assertIn("総合: 収集=黄 分析=赤 処理=赤", text)
            self.assertIn("実行状況: done_with_error / 5m / 実行数=2 エラー数=1", text)
            self.assertIn("## 収集", text)
            self.assertIn("収集: raw=18 TDnet=12 signals=9 candidates=6 scenarios=3 / sig/tdnet=75.0% 価格欠損=2.5% 警告=price_missing", text)
            self.assertIn("収集 target200", text)
            self.assertIn("## 分析", text)
            self.assertIn("分析: pending=40.0% effective=40.0% accepted=5 threshold=3 [ALERT]", text)
            self.assertIn("分析: status=warning accepted=9 winΔ=-3.4pp ddΔ=-1.2pp warnings=2", text)
            self.assertIn("## 処理", text)
            self.assertIn("処理: pending_queue=0 files", text)
            self.assertIn("処理: ingest_topics_db.py 1000ms rc=2", text)
            self.assertIn("失敗: ingest_topics_db.py(rc=2, db_error)", text)


if __name__ == "__main__":
    unittest.main()
