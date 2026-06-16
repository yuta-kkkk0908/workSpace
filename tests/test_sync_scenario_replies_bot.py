import json
import sqlite3
import unittest

from scripts.notify.sync_scenario_replies_bot import ack_text, hold_window_from_entry, parse_command, update_skip_reply


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

    def test_skip_command_parses_reason_text(self) -> None:
        cmd, payload = parse_command("見送り 材料が古い")
        self.assertEqual(cmd, "skip")
        self.assertEqual(payload["reason"], "材料が古い")

    def test_skip_ack_lists_candidate_reasons(self) -> None:
        msg = ack_text("skip", self._sc("long"), {"reason": "材料が古い"}, None)
        self.assertIn("見送り候補:", msg)
        self.assertIn("メモ: 材料が古い", msg)
        self.assertIn("材料が古い / 利益確定売りが強い / 上値が重い / 押し目が浅い / 地合い・値動きが弱い", msg)
        self.assertIn("DB記録済み", msg)

    def test_skip_ack_uses_short_specific_candidates(self) -> None:
        msg = ack_text("skip", self._sc("short"), {}, None)
        self.assertIn("見送り候補:", msg)
        self.assertIn("材料が古い / 下げ止まりが強い / 売り材料が弱い / 踏み上げ警戒 / 地合い・値動きが弱い", msg)
        self.assertIn("DB記録済み", msg)

    def test_skip_update_overwrites_previous_skip_reason(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(
                """
                CREATE TABLE scenario_reply_events (
                  reply_message_id TEXT PRIMARY KEY,
                  channel_id TEXT NOT NULL,
                  parent_message_id TEXT NOT NULL,
                  author_id TEXT NOT NULL,
                  command TEXT NOT NULL,
                  raw_content TEXT NOT NULL,
                  parsed_json TEXT,
                  processed_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO scenario_reply_events(
                  reply_message_id, channel_id, parent_message_id, author_id, command, raw_content, parsed_json, processed_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                ("skip-1", "chan", "parent-1", "user-1", "skip", "見送り", json.dumps({"reason": ""}, ensure_ascii=False), "2026-06-13T00:00:00Z"),
            )
            update_skip_reply(
                conn,
                target_reply_message_id="skip-1",
                reply_message_id="skip-2",
                channel_id="chan",
                parent_message_id="parent-1",
                author_id="user-1",
                sc=self._sc("long"),
                new_reason="材料が古い",
                raw_content="材料が古い",
            )
            updated = conn.execute("SELECT raw_content, parsed_json FROM scenario_reply_events WHERE reply_message_id='skip-1'").fetchone()
            self.assertEqual(updated["raw_content"], "材料が古い")
            parsed = json.loads(updated["parsed_json"])
            self.assertEqual(parsed["reason"], "材料が古い")
            self.assertIn("skip_reason_candidates", parsed)
            inserted = conn.execute("SELECT command, raw_content, parsed_json FROM scenario_reply_events WHERE reply_message_id='skip-2'").fetchone()
            self.assertEqual(inserted["command"], "skip_update")
            self.assertEqual(inserted["raw_content"], "材料が古い")
            inserted_parsed = json.loads(inserted["parsed_json"])
            self.assertEqual(inserted_parsed["updated_target_reply_message_id"], "skip-1")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
