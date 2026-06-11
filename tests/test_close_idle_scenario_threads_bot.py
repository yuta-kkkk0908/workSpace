import sqlite3
import unittest

from scripts.notify.close_idle_scenario_threads_bot import load_targets


class CloseIdleScenarioThreadsBotTests(unittest.TestCase):
    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE scenario_messages (
              thread_id TEXT,
              channel_id TEXT,
              anchor_message_id TEXT,
              message_id TEXT,
              scenario_date TEXT,
              scenario_index INTEGER,
              ticker TEXT,
              company TEXT,
              direction TEXT,
              scenario_tier TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE scenario_reply_events (
              parent_message_id TEXT,
              command TEXT
            )
            """
        )
        return conn

    def test_load_targets_skips_threads_with_entry_events(self) -> None:
        conn = self._conn()
        conn.execute(
            "INSERT INTO scenario_messages VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("th-open", "ch", "a-open", "m-open", "2026-06-15", 1, "1111", "Open", "long", "trade"),
        )
        conn.execute(
            "INSERT INTO scenario_messages VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("th-idle", "ch", "a-idle", "m-idle", "2026-06-15", 2, "2222", "Idle", "short", "watch"),
        )
        conn.execute(
            "INSERT INTO scenario_reply_events VALUES(?,?)",
            ("m-open", "entry"),
        )
        conn.commit()

        rows = load_targets(conn, "2026-06-15", 20)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["thread_id"], "th-idle")
        self.assertEqual(rows[0]["ticker"], "2222")


if __name__ == "__main__":
    unittest.main()
