from __future__ import annotations

import unittest

from scripts.notify.render_market_signals_discord_message import build_message


class RenderMarketSignalsDiscordMessageTests(unittest.TestCase):
    def test_inv_morning_prepends_us_market_overview(self) -> None:
        msg = build_message(
            "2026-06-11",
            [
                {
                    "ticker": "1234",
                    "company": "テスト社",
                    "expected_direction": "up",
                    "long_rank": "A",
                    "short_rank": "",
                    "signal_type": "earnings_positive",
                    "gate_status": "pass",
                    "material_signal_checked": "yes",
                    "external_context_checked": "yes",
                    "technical_signal_checked": "yes",
                    "url": "https://example.com",
                    "source": "tdnet_web",
                    "sector_group": "半導体",
                    "tdnet_title": "決算短信",
                }
            ],
            slot="inv-morning",
            morning_overview={
                "summary": "S&P500 +1.0% / Nasdaq +2.0% / Dow +0.6% / VIX -7.1% / USDJPY 157.50 (+0.32%)",
                "sectorImpact": "半導体・グロースに追い風 / 輸出・機械・自動車に追い風",
            },
        )
        self.assertIn("米市場概況: S&P500 +1.0%", msg)
        self.assertIn("日本セクター影響: 半導体・グロースに追い風", msg)
        self.assertIn("1234 テスト社", msg)


if __name__ == "__main__":
    unittest.main()
