from __future__ import annotations

import importlib.util
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


def load_module():
    path = Path("scripts/investment/signals/build_market_signals_from_batches.py").resolve()
    spec = importlib.util.spec_from_file_location("build_market_signals_from_batches", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE backtest_outcomes (
          outcome_id TEXT,
          ticker TEXT,
          signal_date TEXT,
          signal_type TEXT,
          expected_direction TEXT,
          long_rank TEXT,
          short_rank TEXT,
          source_path TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE tdnet_disclosures (
          date TEXT,
          ticker TEXT,
          title TEXT,
          tdnet_url TEXT,
          source_kind TEXT,
          category TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE credit_status_rows (
          ticker TEXT,
          date TEXT,
          credit_status TEXT,
          buy_status TEXT,
          sell_status TEXT,
          source_kind TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE signals (
          signal_id TEXT NOT NULL,
          date TEXT NOT NULL,
          ticker TEXT,
          company TEXT,
          signal_type TEXT,
          expected_direction TEXT,
          long_rank TEXT,
          short_rank TEXT,
          gate_status TEXT,
          url TEXT,
          source TEXT,
          session TEXT,
          material_signal_checked TEXT,
          external_context_checked TEXT,
          technical_signal_checked TEXT,
          credit_status TEXT,
          credit_buy_status TEXT,
          credit_sell_status TEXT,
          credit_source_kind TEXT,
          credit_source_date TEXT,
          credit_freshness_hours INTEGER,
          source_path TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(signal_id, date)
        )
        """
    )


class BuildMarketSignalsFallbackTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def test_carries_over_previous_signals_when_backtest_rows_missing(self) -> None:
        fd, raw_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db_path = Path(raw_path)
        conn = sqlite3.connect(db_path)
        try:
            create_schema(conn)
            conn.execute(
                """
                INSERT INTO signals(
                  signal_id,date,ticker,company,signal_type,expected_direction,long_rank,short_rank,
                  gate_status,url,source,session,material_signal_checked,external_context_checked,technical_signal_checked,
                  credit_status,credit_buy_status,credit_sell_status,credit_source_kind,credit_source_date,credit_freshness_hours,
                  source_path,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "signal_20260614_001",
                    "2026-06-14",
                    "1234",
                    "テスト社",
                    "earnings_positive",
                    "up",
                    "A",
                    "B",
                    "pass",
                    "https://example.com",
                    "tdnet_web",
                    "after_close",
                    "yes",
                    "yes",
                    "yes",
                    "unknown",
                    "unknown",
                    "unknown",
                    "tdnet_web",
                    "2026-06-14",
                    0,
                    "db:seed",
                    "2026-06-14T00:00:00Z",
                ),
            )
            conn.commit()

            rows = self.mod.build_rows(
                SimpleNamespace(
                    date="2026-06-15",
                    lookback_days=2,
                    max_signals=12,
                    max_long=6,
                    max_short=6,
                    db=db_path,
                )
            )

            self.assertEqual(len(rows), 1)
            c = conn.execute("SELECT date,ticker,source_path FROM signals WHERE date='2026-06-15'").fetchone()
            self.assertIsNotNone(c)
            self.assertEqual(c[0], "2026-06-15")
            self.assertEqual(c[1], "1234")
            self.assertEqual(c[2], "db:carry-over")
        finally:
            conn.close()
            try:
                db_path.unlink(missing_ok=True)
            except PermissionError:
                pass


if __name__ == "__main__":
    unittest.main()
