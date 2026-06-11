import sqlite3
import unittest

from scripts.investment.analysis.materialize_signal_type_aggressiveness import _classify, _materialize


class SignalTypeAggressivenessTests(unittest.TestCase):
    def test_classify_thresholds(self) -> None:
        self.assertEqual(_classify(3, 60.0, 1.0, 0.5), ("avoid", 0, "sample_count<5"))
        self.assertEqual(_classify(6, 60.0, 0.1, 0.0), ("conservative", 1, "sample>=5,t5_wr>=50.0,t5_avg>=0.00"))
        self.assertEqual(_classify(12, 55.0, 0.3, 0.0), ("balanced", 2, "sample>=10,t5_wr>=54.0,t5_avg>=0.25,t20_avg>=0.00"))
        self.assertEqual(_classify(21, 59.0, 0.8, 0.4), ("aggressive", 3, "sample>=20,t5_wr>=58.0,t5_avg>=0.60,t20_avg>=0.30"))

    def test_materialize_direction_adjusted_returns(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE backtest_outcomes (
              signal_type TEXT,
              expected_direction TEXT,
              t1_judge TEXT,
              t5_judge TEXT,
              t20_judge TEXT,
              t1_close_vs_base_pct REAL,
              t5_close_vs_base_pct REAL,
              t20_close_vs_base_pct REAL
            );
            """
        )
        rows = [
            ("buyback", "up", "win", "win", "win", 1.0, 0.8, 0.5),
            ("buyback", "up", "win", "win", "win", 2.0, 1.0, 0.4),
            ("buyback", "up", "win", "win", "win", 1.5, 0.9, 0.3),
            ("buyback", "up", "win", "win", "win", 1.2, 0.7, 0.2),
            ("buyback", "up", "win", "win", "win", 1.1, 0.6, 0.1),
            ("buyback", "up", "win", "win", "win", 1.3, 0.7, 0.2),
        ]
        conn.executemany("INSERT INTO backtest_outcomes VALUES(?,?,?,?,?,?,?,?)", rows)
        results = _materialize(conn.execute("SELECT * FROM backtest_outcomes").fetchall(), "2026-06-11", 365)
        self.assertEqual(len(results), 1)
        row = results[0]
        self.assertEqual(row["signal_type"], "buyback")
        self.assertEqual(row["expected_direction"], "up")
        self.assertEqual(row["sample_count"], 6)
        self.assertEqual(row["aggressiveness_level"], "conservative")
        self.assertAlmostEqual(float(row["t5_dir_avg_return_pct"]), 0.7833, places=4)
        conn.close()


if __name__ == "__main__":
    unittest.main()
