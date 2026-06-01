import unittest

from scripts.investment.signals.build_opening_scenarios import (
    _compute_execution_feasibility,
    scenario_for_row,
)


class ExecutionFeasibilityTests(unittest.TestCase):
    def test_unknown_when_no_sources(self) -> None:
        score, breakdown = _compute_execution_feasibility(None, None)
        self.assertIsNone(score)
        self.assertEqual(breakdown.get("status"), "unknown")

    def test_score_increases_on_tight_spread_and_volume(self) -> None:
        board = {"bestBid": 1000.0, "bestAsk": 1001.0, "indicativeOpen": 1000.5}
        snap = {"volumeRatio": 2.3, "returnPct": 0.6}
        score, breakdown = _compute_execution_feasibility(board, snap)
        self.assertIsInstance(score, int)
        assert isinstance(score, int)
        self.assertGreaterEqual(score, 70)
        self.assertEqual(breakdown.get("status"), "ok")

    def test_score_penalized_on_wide_spread_and_high_intraday_vol(self) -> None:
        board = {"bestBid": 1000.0, "bestAsk": 1020.0, "indicativeOpen": 1050.0}
        snap = {"volumeRatio": 0.4, "returnPct": 7.0}
        score, _ = _compute_execution_feasibility(board, snap)
        self.assertIsInstance(score, int)
        assert isinstance(score, int)
        self.assertLessEqual(score, 40)

    def test_scenario_for_row_keeps_existing_keys_and_adds_execution_keys(self) -> None:
        row = {
            "signalId": "sig-1",
            "ticker": "1111",
            "company": "Test",
            "expectedDirection": "up",
            "longSignalRank": "A",
            "shortSignalRank": "",
            "url": "https://example.com",
            "candidateSource": "primary",
            "sector": "x",
            "borrowStatus": "marginable",
        }
        signal_meta = {
            "signalType": "upward_revision_highest_profit",
            "source": "x",
            "session": "night",
            "gateStatus": "pass",
            "materialSignalChecked": "yes",
            "externalContextChecked": "yes",
            "technicalSignalChecked": "yes",
        }
        rule_ctx = {"summary": "ok", "status": "active_rule", "appearances": 5, "t5": "wr=55.0%"}
        out = scenario_for_row(
            row=row,
            side="long",
            risk_jpy=10000,
            rule_ctx=rule_ctx,
            signal_meta=signal_meta,
            board=None,
            market_snap=None,
            sample_hints=None,
        )
        # Existing keys should remain for backward compatibility.
        for k in ("entryLimitRule", "takeProfitRule", "stopLossRule", "ruleHitCount", "scenarioScore"):
            self.assertIn(k, out)
        # New keys for ds_003.
        self.assertIn("executionFeasibilityScore", out)
        self.assertIn("executionFeasibilityBreakdown", out)
        self.assertEqual(out["executionFeasibilityScore"], "unknown")


if __name__ == "__main__":
    unittest.main()

