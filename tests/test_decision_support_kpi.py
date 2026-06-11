import json
import sqlite3
import unittest

from scripts.investment.analysis.report_decision_support_kpi import _compute_kpi, _load_rows
from scripts.investment.signals.build_opening_scenarios import _reason_code


class DecisionSupportKpiTests(unittest.TestCase):
    def test_reason_code_mapping(self) -> None:
        self.assertEqual(_reason_code("ruleHits<4"), "RULE_HITS_LT")
        self.assertEqual(_reason_code("score<70"), "SCORE_LT")
        self.assertEqual(_reason_code("sampleCount<=2 -> paper_trade_only"), "SAMPLE_LOW_PAPER_ONLY")
        self.assertEqual(_reason_code("credit_unknown:base=unknown"), "CREDIT_UNKNOWN")
        self.assertEqual(_reason_code("AGGR_BALANCED"), "AGGRESSIVENESS")

    def test_compute_kpi_pass_hold(self) -> None:
        rows = [
            {
                "gate_result": "accepted",
                "payload_json": json.dumps({"scenarioTier": "trade"}),
                "t5_judge": "win",
                "t20_judge": "lose",
                "reject_reasons_json": "[]",
            },
            {
                "gate_result": "accepted",
                "payload_json": json.dumps({"scenarioTier": "watch"}),
                "t5_judge": "lose",
                "t20_judge": "pending",
                "reject_reasons_json": "[]",
            },
            {
                "gate_result": "accepted",
                "payload_json": json.dumps({"scenarioTier": "paper_trade_only"}),
                "t5_judge": "pending",
                "t20_judge": "win",
                "reject_reasons_json": "[]",
            },
        ]
        kpi, evaluated = _compute_kpi(rows)  # type: ignore[arg-type]
        self.assertEqual(evaluated, 3)
        self.assertEqual(kpi["legacy"]["t5"]["pass"]["win"], 1)
        self.assertEqual(kpi["legacy"]["t5"]["hold"]["lose"], 1)
        self.assertEqual(kpi["legacy"]["t20"]["pass"]["lose"], 1)
        self.assertEqual(kpi["legacy"]["t20"]["hold"]["win"], 1)

    def test_load_rows_uses_latest_outcome_per_signal_ticker(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE scenario_gate_diagnostics(
              scenario_date TEXT, signal_id TEXT, ticker TEXT, direction TEXT, gate_result TEXT, payload_json TEXT, reject_reasons_json TEXT
            );
            CREATE TABLE backtest_outcomes(
              date TEXT, source_signal_id TEXT, ticker TEXT, t5_judge TEXT, t20_judge TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO scenario_gate_diagnostics VALUES(?,?,?,?,?,?,?)",
            ("2026-05-28", "sig-1", "1111", "long", "accepted", json.dumps({"scenarioTier": "trade"}), "[]"),
        )
        conn.execute(
            "INSERT INTO backtest_outcomes VALUES(?,?,?,?,?)",
            ("2026-05-20", "sig-1", "1111", "lose", "lose"),
        )
        conn.execute(
            "INSERT INTO backtest_outcomes VALUES(?,?,?,?,?)",
            ("2026-05-27", "sig-1", "1111", "win", "win"),
        )
        rows = _load_rows(conn, "2026-05-01", "2026-05-28")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["t5_judge"], "win")
        self.assertEqual(rows[0]["t20_judge"], "win")
        conn.close()


if __name__ == "__main__":
    unittest.main()
