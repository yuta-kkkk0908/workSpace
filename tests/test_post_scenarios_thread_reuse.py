import sqlite3
import unittest

from scripts.notify.post_scenarios_bot import find_reusable_thread_id, prepare_post_rows, thread_reuse_key


class PostScenariosThreadReuseTests(unittest.TestCase):
    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE scenario_messages (
              scenario_date TEXT NOT NULL,
              scenario_index INTEGER NOT NULL,
              channel_id TEXT NOT NULL,
              thread_id TEXT,
              anchor_message_id TEXT,
              message_id TEXT NOT NULL PRIMARY KEY,
              ticker TEXT,
              company TEXT,
              direction TEXT,
              scenario_tier TEXT NOT NULL DEFAULT 'trade',
              watch_ladder TEXT,
              signal_id TEXT,
              source_path TEXT NOT NULL,
              posted_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        return conn

    def test_thread_reuse_key_includes_ladder_for_watch(self) -> None:
        row = {"ticker": "4022", "direction": "long", "scenarioTier": "watch", "watchLadder": "balanced"}
        self.assertEqual(thread_reuse_key(row), ("4022", "long", "watch", "balanced"))

    def test_thread_reuse_key_ignores_ladder_for_trade(self) -> None:
        row = {"ticker": "4022", "direction": "long", "scenarioTier": "trade", "watchLadder": "strict"}
        self.assertEqual(thread_reuse_key(row), ("4022", "long", "trade", ""))

    def test_find_reusable_thread_id_respects_ladder_and_period(self) -> None:
        conn = self._conn()
        conn.execute(
            """
            INSERT INTO scenario_messages(
              scenario_date, scenario_index, channel_id, thread_id, anchor_message_id, message_id,
              ticker, company, direction, scenario_tier, watch_ladder, signal_id, source_path, posted_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "2026-05-27",
                1,
                "ch",
                "th-1",
                "a-1",
                "m-1",
                "4022",
                "Test",
                "long",
                "watch",
                "balanced",
                "",
                "db:opening_scenarios",
                "2026-05-27T00:00:00Z",
                "2026-05-27T00:00:00Z",
            ),
        )
        matched = find_reusable_thread_id(
            conn,
            row={"ticker": "4022", "direction": "long", "scenarioTier": "watch", "watchLadder": "balanced"},
            reuse_days=30,
        )
        self.assertEqual(matched, "th-1")
        not_matched = find_reusable_thread_id(
            conn,
            row={"ticker": "4022", "direction": "long", "scenarioTier": "watch", "watchLadder": "strict"},
            reuse_days=30,
        )
        self.assertEqual(not_matched, "")

    def test_prepare_post_rows_keeps_watch_scenarios_even_without_trades(self) -> None:
        rows, trade_count, paper_count, watch_count, watch_cap = prepare_post_rows(
            [],
            [],
            [
                {
                    "ticker": "3083",
                    "direction": "long",
                    "scenarioTier": "watch",
                    "scenarioScore": 40,
                    "ruleHitCount": 1,
                    "estimatedWinRate": "T+20想定勝率=48.0%（50%未満）",
                    "scenarioDate": "2026-06-05",
                    "scenarioIndex": 1,
                }
            ],
            [
                {
                    "ticker": "9999",
                    "direction": "short",
                    "scenarioTier": "watch",
                    "scenarioScore": 70,
                    "ruleHitCount": 3,
                    "estimatedWinRate": "T+5想定勝率=52.0%（50%超）",
                    "scenarioDate": "2026-06-05",
                    "scenarioIndex": 2,
                }
            ],
            max_posts=12,
            watch_posts=4,
            min_trade_posts=3,
        )

        self.assertEqual(trade_count, 0)
        self.assertEqual(paper_count, 0)
        self.assertEqual(watch_count, 2)
        self.assertEqual(watch_cap, 7)
        self.assertEqual([r["ticker"] for r in rows], ["3083", "9999"])
        self.assertEqual(rows[0]["scenarioTier"], "watch")
        self.assertEqual(rows[0]["watchLadder"], "none")
        self.assertEqual(rows[1]["watchLadder"], "early")


if __name__ == "__main__":
    unittest.main()
