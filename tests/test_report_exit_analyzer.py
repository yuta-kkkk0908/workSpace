import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.investment.analysis import report_exit_analyzer as mod


class ReportExitAnalyzerTests(unittest.TestCase):
    def test_report_emits_bottleneck_sections_and_discord_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox = root / "topics" / "investment-research" / "inbox"
            prompts = root / "prompts"
            inbox.mkdir(parents=True, exist_ok=True)
            prompts.mkdir(parents=True, exist_ok=True)

            db_path = root / "investment.db"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE paper_trades (
                  trade_id TEXT PRIMARY KEY,
                  mode TEXT NOT NULL,
                  entry_date TEXT NOT NULL,
                  ticker TEXT NOT NULL,
                  side TEXT NOT NULL,
                  status TEXT NOT NULL,
                  exit_reason TEXT,
                  t1_return_pct REAL,
                  t5_return_pct REAL,
                  t20_return_pct REAL,
                  price_path_json TEXT
                );
                CREATE TABLE scenario_messages (
                  message_id TEXT PRIMARY KEY,
                  scenario_date TEXT NOT NULL,
                  scenario_tier TEXT NOT NULL,
                  watch_ladder TEXT
                );
                CREATE TABLE scenario_reply_events (
                  reply_message_id TEXT PRIMARY KEY,
                  parent_message_id TEXT NOT NULL,
                  command TEXT NOT NULL,
                  processed_at TEXT NOT NULL
                );
                """
            )
            conn.executemany(
                """
                INSERT INTO paper_trades(
                  trade_id, mode, entry_date, ticker, side, status, exit_reason,
                  t1_return_pct, t5_return_pct, t20_return_pct, price_path_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        "open_1",
                        "live",
                        "2026-06-02",
                        "1111",
                        "long",
                        "open_pending_outcome",
                        None,
                        None,
                        None,
                        None,
                        None,
                    ),
                    (
                        "closed_1",
                        "watch",
                        "2026-06-04",
                        "2222",
                        "long",
                        "closed_t20_ready",
                        "tp",
                        1.0,
                        2.0,
                        3.0,
                        json.dumps(
                            {
                                "base_close": 100.0,
                                "bars": [{"close": 100.0}, {"close": 101.0}, {"close": 102.0}, {"close": 103.0}, {"close": 104.0}, {"close": 105.0}, {"close": 106.0}, {"close": 107.0}, {"close": 108.0}, {"close": 109.0}, {"close": 110.0}],
                            },
                            ensure_ascii=False,
                        ),
                    ),
                ],
            )
            conn.execute(
                "INSERT INTO scenario_messages VALUES(?,?,?,?)",
                ("msg-1", "2026-06-04", "trade", None),
            )
            conn.execute(
                "INSERT INTO scenario_reply_events VALUES(?,?,?,?)",
                ("reply-1", "msg-1", "exit", "2026-06-05T00:00:00Z"),
            )
            conn.commit()
            conn.close()

            argv = ["report_exit_analyzer.py", "--date", "2026-06-05", "--db", str(db_path), "--window-days", "30"]
            with (
                patch.object(mod, "INBOX", inbox),
                patch.object(mod, "PROMPTS", prompts),
                patch.object(mod, "write_pipeline_event"),
                patch.object(sys, "argv", argv),
            ):
                rc = mod.main()

            self.assertEqual(rc, 0)
            md = (inbox / "2026-06-05-exit-analyzer.md").read_text(encoding="utf-8")
            js = json.loads((inbox / "2026-06-05-exit-analyzer.json").read_text(encoding="utf-8"))
            txt = (prompts / "exit-analyzer-discord-message.txt").read_text(encoding="utf-8")
            self.assertIn("## 収集", md)
            self.assertIn("## Ticker Breakdown", md)
            self.assertIn("## Side Breakdown", md)
            self.assertIn("T+3(ref)", md)
            self.assertIn("T+10(ref)", md)
            self.assertIn("## Mode Breakdown", md)
            self.assertIn("## Mode x Age Breakdown", md)
            self.assertIn("## Mode x Age x Exit Reason Breakdown (closed only)", md)
            self.assertIn("## Mode x Age x Status Breakdown", md)
            self.assertIn("## Exit Reason Breakdown", md)
            self.assertIn("## Age Breakdown", md)
            self.assertIn("## Age x Status Breakdown", md)
            self.assertIn("## Stuck Breakdown", md)
            self.assertIn("level", js)
            self.assertEqual(js["level"], "ALERT")
            self.assertGreaterEqual(js["collection"]["openTradeCount"], 1)
            self.assertIn("tickerBreakdown", js)
            self.assertIn("sideBreakdown", js)
            self.assertIn("modeBreakdown", js)
            self.assertIn("modeAgeBreakdown", js)
            self.assertIn("modeAgeExitReasonBreakdown", js)
            self.assertIn("modeAgeStatusBreakdown", js)
            self.assertIn("ageStatusBreakdown", js)
            self.assertIn("exitReasonBreakdown", js)
            self.assertIn("ageBreakdown", js)
            self.assertIn("stuckBreakdown", js)
            self.assertIn("ExitAnalyzer 2026-06-05", txt)
            self.assertIn("T+3(ref)", txt)
            self.assertIn("T+10(ref)", txt)


if __name__ == "__main__":
    unittest.main()
