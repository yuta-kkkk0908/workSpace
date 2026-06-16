import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.investment.analysis import report_paper_trade_only_kpi as paper_kpi
from scripts.investment.backtest import generate_trade_watch_weekly_review as weekly_review


class T3PropagationTests(unittest.TestCase):
    def test_paper_trade_only_kpi_emits_t3_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox = root / "topics" / "investment-research" / "inbox"
            inbox.mkdir(parents=True, exist_ok=True)

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
                  t5_judge TEXT,
                  t1_return_pct REAL,
                  t5_return_pct REAL,
                  t20_return_pct REAL,
                  price_path_json TEXT,
                  signal_id TEXT
                );
                CREATE TABLE opening_scenarios (
                  scenario_date TEXT NOT NULL,
                  ticker TEXT NOT NULL,
                  direction TEXT NOT NULL,
                  signal_id TEXT,
                  scenario_tier TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "INSERT INTO opening_scenarios VALUES(?,?,?,?,?)",
                ("2026-06-05", "1111", "long", "sig-1", "paper_trade_only"),
            )
            conn.execute(
                """
                INSERT INTO paper_trades(
                  trade_id, mode, entry_date, ticker, side,
                  t1_return_pct, t5_return_pct, t20_return_pct,
                  price_path_json, signal_id
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "trade-1",
                    "watch",
                    "2026-06-05",
                    "1111",
                    "long",
                    1.0,
                    2.0,
                    3.0,
                    json.dumps(
                        {
                            "base_close": 100.0,
                            "bars": [
                                {"close": 100.0},
                                {"close": 101.0},
                                {"close": 102.0},
                                {"close": 104.0},
                                {"close": 105.0},
                                {"close": 106.0},
                                {"close": 107.0},
                                {"close": 108.0},
                                {"close": 109.0},
                                {"close": 110.0},
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    "sig-1",
                ),
            )
            conn.commit()
            conn.close()

            argv = ["report_paper_trade_only_kpi.py", "--date", "2026-06-05", "--db", str(db_path), "--window-days", "30"]
            with (
                patch.object(paper_kpi, "ROOT", root),
                patch.object(paper_kpi, "OUT", inbox),
                patch.object(paper_kpi, "write_pipeline_event"),
                patch.object(sys, "argv", argv),
            ):
                rc = paper_kpi.main()

            self.assertEqual(rc, 0)
            md = (inbox / "2026-06-05-paper-trade-only-kpi.md").read_text(encoding="utf-8")
            js = json.loads((inbox / "2026-06-05-paper-trade-only-kpi.json").read_text(encoding="utf-8"))
            self.assertIn("judgedT3", md)
            self.assertIn("expectedValueT3Pct", md)
            self.assertIn("maxDrawdownT3Pct", md)
            self.assertEqual(js["kpi"]["judgedT3"], 1)
            self.assertIn("winRateT3Pct", js["kpi"])

    def test_weekly_review_mentions_t3_in_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox = root / "topics" / "investment-research" / "inbox"
            inbox.mkdir(parents=True, exist_ok=True)

            db_path = root / "investment.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            conn.executescript(
                """
                CREATE TABLE paper_trades (
                  trade_id TEXT PRIMARY KEY,
                  mode TEXT NOT NULL,
                  entry_date TEXT NOT NULL,
                  ticker TEXT NOT NULL,
                  company TEXT NOT NULL DEFAULT '',
                  side TEXT NOT NULL,
                  t5_judge TEXT,
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
                  parsed_json TEXT,
                  processed_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                INSERT INTO paper_trades(
                  trade_id, mode, entry_date, ticker, company, side,
                  t1_return_pct, t5_return_pct, t20_return_pct, price_path_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "trade-1",
                    "live",
                    "2026-06-01",
                    "1111",
                    "Test Live",
                    "long",
                    1.0,
                    2.0,
                    3.0,
                    json.dumps(
                        {
                            "base_close": 100.0,
                            "bars": [
                                {"close": 100.0},
                                {"close": 101.0},
                                {"close": 102.0},
                                {"close": 103.0},
                                {"close": 104.0},
                                {"close": 105.0},
                                {"close": 106.0},
                                {"close": 107.0},
                                {"close": 108.0},
                                {"close": 109.0},
                                {"close": 110.0},
                            ],
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            conn.execute(
                "INSERT INTO scenario_messages VALUES(?,?,?,?)",
                ("msg-1", "2026-06-01", "trade", None),
            )
            conn.execute(
                "INSERT INTO scenario_reply_events VALUES(?,?,?,?,?)",
                ("reply-1", "msg-1", "entry", json.dumps({"trade_id": "trade-1"}), "2026-06-01T00:00:00Z"),
            )
            conn.commit()
            conn.close()

            argv = [
                "generate_trade_watch_weekly_review.py",
                "--db",
                str(db_path),
                "--out-date",
                "2026-06-05",
                "--start-date",
                "2026-06-01",
                "--end-date",
                "2026-06-05",
            ]
            with (
                patch.object(weekly_review, "ROOT", root),
                patch.object(weekly_review, "OUT", inbox),
                patch.object(sys, "argv", argv),
            ):
                rc = weekly_review.main()

            self.assertEqual(rc, 0)
            md = (inbox / "2026-06-05-weekly-trade-watch-review.md").read_text(encoding="utf-8")
            self.assertIn("Mode Summary (T+5中心)", md)
            self.assertIn("trade T+3(ref)", md)
            self.assertIn("watch T+3(ref)", md)
            self.assertIn("T+1/T+3/T+5/T+20", md)
            self.assertIn("T+3は短期の前倒し判断を見る補助窓として扱う", md)


if __name__ == "__main__":
    unittest.main()
