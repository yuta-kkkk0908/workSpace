from __future__ import annotations

import unittest

from scripts.investment.collect.collect_us_market_overview import build_overview


class CollectUsMarketOverviewTests(unittest.TestCase):
    def test_build_overview_summarizes_market_and_sector_impact(self) -> None:
        series = {
            "sp500": [{"date": "2026-06-09", "close": 5000}, {"date": "2026-06-10", "close": 5050}],
            "nasdaq": [{"date": "2026-06-09", "close": 17000}, {"date": "2026-06-10", "close": 17340}],
            "dow": [{"date": "2026-06-09", "close": 39000}, {"date": "2026-06-10", "close": 39234}],
            "vix": [{"date": "2026-06-09", "close": 14}, {"date": "2026-06-10", "close": 13}],
            "usdjpy": [{"date": "2026-06-09", "close": 157.0}, {"date": "2026-06-10", "close": 157.5}],
        }
        payload = build_overview("2026-06-11", series)
        self.assertIn("S&P500 +1.0%", payload["summary"])
        self.assertIn("Nasdaq +2.0%", payload["summary"])
        self.assertIn("Dow +0.6%", payload["summary"])
        self.assertIn("VIX -7.1%", payload["summary"])
        self.assertIn("USDJPY 157.50 (+0.32%)", payload["summary"])
        self.assertIn("半導体・グロースに追い風", payload["sectorImpact"])
        self.assertIn("輸出・機械・自動車に追い風", payload["sectorImpact"])


if __name__ == "__main__":
    unittest.main()
