import importlib.util
import sqlite3
import unittest
from pathlib import Path


def load_ingest_module():
    path = Path("scripts/data/ingest_topics_db.py").resolve()
    spec = importlib.util.spec_from_file_location("ingest_topics_db", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE pokemon_watch_items (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          topic TEXT NOT NULL,
          date TEXT NOT NULL,
          source_path TEXT NOT NULL,
          file_kind TEXT NOT NULL,
          section TEXT NOT NULL,
          item_key TEXT NOT NULL,
          title TEXT NOT NULL,
          kind TEXT NOT NULL,
          status TEXT NOT NULL,
          source_name TEXT NOT NULL,
          media TEXT NOT NULL DEFAULT '',
          url TEXT NOT NULL DEFAULT '',
          product TEXT NOT NULL DEFAULT '',
          release_date TEXT NOT NULL DEFAULT '',
          start_text TEXT NOT NULL DEFAULT '',
          end_text TEXT NOT NULL DEFAULT '',
          deadline_text TEXT NOT NULL DEFAULT '',
          condition_text TEXT NOT NULL DEFAULT '',
          rank_text TEXT NOT NULL DEFAULT '',
          summary TEXT NOT NULL DEFAULT '',
          why_it_matters TEXT NOT NULL DEFAULT '',
          action_text TEXT NOT NULL DEFAULT '',
          notes TEXT NOT NULL DEFAULT '',
          raw_text TEXT NOT NULL DEFAULT '',
          collected_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(topic, date, source_path, file_kind, section, item_key, title, url)
        )
        """
    )


class TestPokemonWatchIngest(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = load_ingest_module()

    def test_parse_daily_file_into_structured_rows(self) -> None:
        text = Path("topics/pokemon-card-watch/inbox/2026-06-08-daily.md").read_text(encoding="utf-8")
        rows = self.mod.parse_pokemon_watch_rows(
            text=text,
            topic="pokemon-card-watch",
            date="2026-06-08",
            source_path="topics/pokemon-card-watch/inbox/2026-06-08-daily.md",
            file_kind="daily",
        )
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0]["section"], "直近1週間 優勝デッキピックアップ")
        self.assertEqual(rows[0]["status"], "N/C")
        self.assertEqual(rows[1]["kind"], "lottery")
        self.assertEqual(rows[1]["status"], "一般")
        self.assertTrue(rows[1]["url"].startswith("https://"))
        self.assertEqual(rows[-1]["section"], "Deck Environment Watch")
        self.assertEqual(rows[-1]["status"], "N/C")

    def test_source_plan_is_not_loaded_as_structured_items(self) -> None:
        text = Path("topics/pokemon-card-watch/inbox/2026-06-08-source-plan.md").read_text(encoding="utf-8")
        rows = self.mod.parse_pokemon_watch_rows(
            text=text,
            topic="pokemon-card-watch",
            date="2026-06-08",
            source_path="topics/pokemon-card-watch/inbox/2026-06-08-source-plan.md",
            file_kind="source-plan",
        )
        self.assertEqual(rows, [])

    def test_replace_pokemon_items_writes_rows(self) -> None:
        text = Path("topics/pokemon-card-watch/inbox/2026-06-08-daily.md").read_text(encoding="utf-8")
        rows = self.mod.parse_pokemon_watch_rows(
            text=text,
            topic="pokemon-card-watch",
            date="2026-06-08",
            source_path="topics/pokemon-card-watch/inbox/2026-06-08-daily.md",
            file_kind="daily",
        )
        conn = sqlite3.connect(":memory:")
        try:
            create_schema(conn)
            inserted = self.mod.replace_pokemon_items(
                conn,
                topic="pokemon-card-watch",
                date="2026-06-08",
                rel_path="topics/pokemon-card-watch/inbox/2026-06-08-daily.md",
                file_kind="daily",
                items=rows,
            )
            self.assertEqual(inserted, 6)
            count = conn.execute("select count(*) from pokemon_watch_items").fetchone()[0]
            self.assertEqual(count, 6)
            product = conn.execute(
                "select product from pokemon_watch_items where file_kind='daily' and kind='lottery' order by id limit 1"
            ).fetchone()[0]
            self.assertIn("ポケカ", product)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
