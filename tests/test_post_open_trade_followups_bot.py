import unittest

from scripts.notify.post_open_trade_followups_bot import post_followup_content


class PostOpenTradeFollowupsBotTests(unittest.TestCase):
    def _row(self) -> dict:
        return {
            "ticker": "5801",
            "company": "Test Corp",
            "direction": "long",
            "scenario_tier": "watch",
            "watch_ladder": "balanced",
            "scenario_date": "2026-06-11",
            "scenario_index": 1,
            "entry_price": None,
        }

    def test_followup_message_mentions_open_status_and_hold_window(self) -> None:
        msg = post_followup_content(self._row(), 2)
        self.assertIn("追記: エントリー済み・未 exit", msg)
        self.assertIn("未 exit 建玉: 2件", msg)
        self.assertIn("保有目安:", msg)
        self.assertIn("TP/SL目安: entry価格が未指定", msg)
        self.assertIn("監視強度: balanced", msg)

    def test_followup_message_with_price_includes_exit_guidance(self) -> None:
        row = self._row()
        row["entry_price"] = 1000
        msg = post_followup_content(row, 1)
        self.assertIn("entry価格: 1000円", msg)
        self.assertIn("TP目安:", msg)
        self.assertIn("SL目安:", msg)


if __name__ == "__main__":
    unittest.main()
