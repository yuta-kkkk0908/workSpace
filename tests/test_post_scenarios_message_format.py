import unittest

from scripts.notify.post_scenarios_bot import to_message


class PostScenariosMessageFormatTests(unittest.TestCase):
    def _base_row(self) -> dict:
        return {
            "ticker": "1111",
            "company": "Test Corp",
            "direction": "long",
            "scenarioScore": 80,
            "ruleHitCount": 5,
            "estimatedWinRate": "T+5想定勝率=55.0%（50%超）",
            "candidateSource": "primary",
            "entryLimitRule": "1000円",
            "takeProfitRule": "1020円",
            "stopLossRule": "990円",
            "suggestedHorizon": "T+5",
            "watchLadder": "balanced",
        }

    def test_trade_message_has_proposal_notice(self) -> None:
        row = self._base_row()
        row["scenarioTier"] = "trade"
        msg = to_message("2026-05-28", 1, row)
        self.assertIn("提案/観測", msg)
        self.assertIn("自動発注は行いません", msg)
        self.assertIn("TRADE枠は執行候補の提案", msg)
        self.assertLessEqual(len(msg), 1900)

    def test_watch_message_has_ladder_reason_and_watch_notice(self) -> None:
        row = self._base_row()
        row["scenarioTier"] = "watch"
        msg = to_message("2026-05-28", 1, row)
        self.assertIn("優先度: Ladder=balanced", msg)
        self.assertIn("昇格根拠:", msg)
        self.assertIn("WATCH枠", msg)
        self.assertLessEqual(len(msg), 1900)

    def test_paper_message_has_ladder_reason_and_paper_notice(self) -> None:
        row = self._base_row()
        row["scenarioTier"] = "paper_trade_only"
        msg = to_message("2026-05-28", 1, row)
        self.assertIn("優先度: Ladder=balanced", msg)
        self.assertIn("昇格根拠:", msg)
        self.assertIn("PAPER枠", msg)
        self.assertLessEqual(len(msg), 1900)


if __name__ == "__main__":
    unittest.main()

