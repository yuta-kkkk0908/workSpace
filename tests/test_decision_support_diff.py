import sqlite3
import unittest

from scripts.investment.analysis.report_decision_support_diff import _daily_metrics


class DecisionSupportDiffTests(unittest.TestCase):
    def test_daily_metrics_basic(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE scenario_gate_diagnostics(
              scenario_date TEXT, signal_id TEXT, ticker TEXT, direction TEXT, gate_result TEXT, payload_json TEXT
            );
            CREATE TABLE backtest_outcomes(
              source_signal_id TEXT, ticker TEXT, t5_judge TEXT
            );
            CREATE TABLE paper_trades(
              entry_date TEXT, ticker TEXT, side TEXT, t5_return_pct REAL
            );
            """
        )
        conn.execute(
            "INSERT INTO scenario_gate_diagnostics VALUES(?,?,?,?,?,?)",
            ("2026-05-28", "sig-1", "1111", "long", "accepted", '{"scenarioTier":"trade"}'),
        )
        conn.execute(
            "INSERT INTO backtest_outcomes VALUES(?,?,?)",
            ("sig-1", "1111", "win"),
        )
        conn.execute(
            "INSERT INTO paper_trades VALUES(?,?,?,?)",
            ("2026-05-28", "1111", "long", 1.5),
        )
        m = _daily_metrics(conn, "2026-05-28", 30)
        self.assertEqual(m["acceptedCount"], 1)
        self.assertEqual(m["passT5Evaluated"], 1)
        self.assertGreaterEqual(float(m["passT5WinRatePct"]), 99.0)
        conn.close()


if __name__ == "__main__":
    unittest.main()

