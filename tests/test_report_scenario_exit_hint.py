import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.investment.analysis import report_scenario_exit_hint as mod


class ReportScenarioExitHintTests(unittest.TestCase):
    def test_report_emits_light_hint_for_one_scenario(self) -> None:
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
                CREATE TABLE scenario_messages (
                  scenario_date TEXT NOT NULL,
                  scenario_index INTEGER NOT NULL,
                  channel_id TEXT NOT NULL,
                  thread_id TEXT,
                  anchor_message_id TEXT,
                  message_id TEXT NOT NULL PRIMARY KEY,
                  ticker TEXT,
                  company TEXT,
                  direction TEXT,
                  scenario_tier TEXT NOT NULL DEFAULT 'trade',
                  watch_ladder TEXT,
                  signal_id TEXT,
                  source_path TEXT NOT NULL,
                  posted_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE TABLE scenario_reply_events (
                  reply_message_id TEXT PRIMARY KEY,
                  channel_id TEXT NOT NULL,
                  parent_message_id TEXT NOT NULL,
                  author_id TEXT NOT NULL,
                  command TEXT NOT NULL,
                  raw_content TEXT NOT NULL,
                  parsed_json TEXT,
                  processed_at TEXT NOT NULL
                );
                CREATE TABLE paper_trades (
                  trade_id TEXT PRIMARY KEY,
                  mode TEXT NOT NULL DEFAULT 'live',
                  entry_date TEXT NOT NULL,
                  ticker TEXT NOT NULL,
                  company TEXT,
                  side TEXT NOT NULL,
                  lots INTEGER NOT NULL,
                  entry_style TEXT NOT NULL,
                  planned_entry_price REAL,
                  exit_price REAL,
                  exit_reason TEXT,
                  status TEXT NOT NULL,
                  signal_id TEXT,
                  source_path TEXT NOT NULL,
                  price_path_json TEXT,
                  t1_return_pct REAL,
                  t5_return_pct REAL,
                  t20_return_pct REAL,
                  t1_pnl_jpy REAL,
                  t5_pnl_jpy REAL,
                  t20_pnl_jpy REAL,
                  t1_judge TEXT,
                  t5_judge TEXT,
                  t20_judge TEXT,
                  updated_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                INSERT INTO scenario_messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "2026-06-05",
                    1,
                    "chan-1",
                    "thread-1",
                    "anchor-1",
                    "msg-1",
                    "1111",
                    "Test Corp",
                    "long",
                    "trade",
                    "balanced",
                    "sig-1",
                    "db:opening_scenarios",
                    "2026-06-05T00:00:00Z",
                    "2026-06-05T00:00:00Z",
                ),
            )
            conn.executemany(
                """
                INSERT INTO scenario_reply_events VALUES(?,?,?,?,?,?,?,?)
                """,
                [
                    ("r1", "thread-1", "msg-1", "bot", "entry", "entry 1000", '{"price":1000}', "2026-06-05T01:00:00Z"),
                    ("r2", "thread-1", "msg-1", "bot", "exit", "exit tp 1100", '{"price":1100}', "2026-06-05T03:00:00Z"),
                ],
            )
            conn.execute(
                """
                INSERT INTO paper_trades(
                  trade_id, mode, entry_date, ticker, company, side, lots, entry_style,
                  planned_entry_price, exit_price, exit_reason, status, signal_id, source_path,
                  price_path_json, t1_return_pct, t5_return_pct, t20_return_pct,
                  t1_pnl_jpy, t5_pnl_jpy, t20_pnl_jpy, t1_judge, t5_judge, t20_judge, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "paper_auto_20260605_1111_long_01",
                    "paper",
                    "2026-06-05",
                    "1111",
                    "Test Corp",
                    "long",
                    1,
                    "auto_scenario",
                    1000.0,
                    1100.0,
                    "tp",
                    "closed_t20_ready",
                    "sig-1",
                    "db:opening_scenarios",
                    json.dumps(
                        {
                            "base_close": 1000.0,
                            "bars": [{"close": 1000.0}, {"close": 1010.0}, {"close": 1020.0}, {"close": 1030.0}, {"close": 1040.0}, {"close": 1050.0}, {"close": 1060.0}, {"close": 1070.0}, {"close": 1080.0}, {"close": 1090.0}, {"close": 1100.0}],
                        },
                        ensure_ascii=False,
                    ),
                    1.0,
                    2.0,
                    3.0,
                    None,
                    None,
                    None,
                    "win",
                    "win",
                    "win",
                    "2026-06-05T04:00:00Z",
                ),
            )
            conn.commit()
            conn.close()

            argv = ["report_scenario_exit_hint.py", "--date", "2026-06-05", "--index", "1", "--db", str(db_path)]
            with (
                patch.object(mod, "INBOX", inbox),
                patch.object(mod, "PROMPTS", prompts),
                patch.object(mod, "write_pipeline_event"),
                patch.object(sys, "argv", argv),
            ):
                rc = mod.main()

            self.assertEqual(rc, 0)
            md = (inbox / "2026-06-05-scenario-01-exit-hint.md").read_text(encoding="utf-8")
            js = json.loads((inbox / "2026-06-05-scenario-01-exit-hint.json").read_text(encoding="utf-8"))
            txt = (prompts / "scenario-01-exit-hint-discord-message.txt").read_text(encoding="utf-8")
            self.assertIn("## 目安", md)
            self.assertIn("T+1/T+3/T+5/T+20", md)
            self.assertIn("T+3は", md)
            self.assertIn("replies: 2", md)
            self.assertIn("linked trades: 1", md)
            self.assertIn("Scenario Exit Hint 2026-06-05 #1", txt)
            self.assertIn("hint:", txt)
            self.assertIn("T+3 wr=", txt)
            self.assertIn("trade: open=0 closed=1", txt)
            self.assertEqual(js["scenario"]["messageId"], "msg-1")
            self.assertEqual(js["replies"]["replyCount"], 2)
            self.assertEqual(js["trade"]["linkedTradeCount"], 1)


if __name__ == "__main__":
    unittest.main()
