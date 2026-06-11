import unittest

from scripts.notify.sync_scenario_replies_bot import ack_text, hold_window_from_entry


class SyncScenarioRepliesBotTests(unittest.TestCase):
    def _sc(self, direction: str = "long") -> dict:
        return {
            "direction": direction,
            "ticker": "1111",
            "company": "Test Corp",
            "scenario_tier": "trade",
            "scenario_date": "2026-06-11",
        }

    def test_hold_window_is_direction_sensitive(self) -> None:
        self.assertEqual(hold_window_from_entry(800, "long"), "1〜3営業日程度")
        self.assertEqual(hold_window_from_entry(800, "short"), "1〜2営業日程度")

    def test_entry_ack_for_long_includes_tp_sl_and_hold_window(self) -> None:
        msg = ack_text("entry", self._sc("long"), {"price": 1000, "lots": 100}, "trade-1")
        self.assertIn("ロング（買い）", msg)
        self.assertIn("保有目安:", msg)
        self.assertIn("TP目安:", msg)
        self.assertIn("利確条件:", msg)
        self.assertIn("損切条件:", msg)
        self.assertIn("exitコマンド:", msg)

    def test_entry_ack_for_short_includes_tp_sl_and_hold_window(self) -> None:
        msg = ack_text("entry", self._sc("short"), {"price": 1000, "lots": 100}, "trade-1")
        self.assertIn("ショート（売り）", msg)
        self.assertIn("保有目安:", msg)
        self.assertIn("TP目安:", msg)
        self.assertIn("利確条件:", msg)
        self.assertIn("損切条件:", msg)
        self.assertIn("exitコマンド:", msg)


if __name__ == "__main__":
    unittest.main()
