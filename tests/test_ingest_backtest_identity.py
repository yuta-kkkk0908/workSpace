import importlib.util
import sqlite3
import unittest
import uuid
from pathlib import Path


def load_ingest_module():
    p = Path('scripts/data/ingest_investment_db.py').resolve()
    spec = importlib.util.spec_from_file_location('ingest_investment_db', p)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        '''
        CREATE TABLE backtest_outcomes (
          outcome_id TEXT NOT NULL,
          date TEXT NOT NULL,
          source_signal_id TEXT,
          ticker TEXT,
          signal_date TEXT,
          disclosure_category TEXT,
          disclosure_category_label_ja TEXT,
          signal_type TEXT,
          signal_type_label_ja TEXT,
          expected_direction TEXT,
          expected_direction_label_ja TEXT,
          long_rank TEXT,
          short_rank TEXT,
          long_rank_label_ja TEXT,
          short_rank_label_ja TEXT,
          t1_judge TEXT,
          t5_judge TEXT,
          t20_judge TEXT,
          outcome_type TEXT,
          source_path TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(outcome_id, date)
        )
        '''
    )
    conn.execute(
        'CREATE TABLE ingest_log (id INTEGER PRIMARY KEY AUTOINCREMENT, run_at TEXT NOT NULL, kind TEXT NOT NULL, source_path TEXT NOT NULL, rows INTEGER NOT NULL)'
    )


class BacktestIngestTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_ingest_module()

    def _write_file(self, body: str, name: str | None = None) -> Path:
        inbox = Path('topics/investment-research/inbox')
        inbox.mkdir(parents=True, exist_ok=True)
        if name is None:
            name = f"2026-05-19-rough-backtest-outcomes-test-{uuid.uuid4().hex}.md"
        p = (inbox / name).resolve()
        p.write_text(body, encoding='utf-8')
        return p

    def test_skip_when_identity_fields_missing(self):
        path = self._write_file("""### outcome_a: 1301 Foo\n- sourceSignalId: sig-1\n- signalDate: 2026-05-10\n- signalType:\n""")
        try:
            conn = sqlite3.connect(':memory:')
            create_schema(conn)
            self.mod.upsert_backtest(conn, path)
            c = conn.execute('SELECT COUNT(*) FROM backtest_outcomes').fetchone()[0]
            self.assertEqual(c, 0)
        finally:
            path.unlink(missing_ok=True)

    def test_upsert_single_row_for_same_identity(self):
        path = self._write_file("""### outcome_a: 1301 Foo\n- sourceSignalId: sig-1\n- signalDate: 2026-05-10\n- signalType: buyback\n- T+1Judge: win\n\n### outcome_b: 1301 Foo v2\n- sourceSignalId: sig-1\n- signalDate: 2026-05-10\n- signalType: buyback\n- T+1Judge: loss\n""")
        try:
            conn = sqlite3.connect(':memory:')
            create_schema(conn)
            self.mod.upsert_backtest(conn, path)
            c = conn.execute('SELECT COUNT(*) FROM backtest_outcomes').fetchone()[0]
            self.assertEqual(c, 1)
            t1 = conn.execute('SELECT t1_judge FROM backtest_outcomes').fetchone()[0]
            self.assertEqual(t1, 'loss')
        finally:
            path.unlink(missing_ok=True)

    def test_signal_type_normalized_in_outcome_id(self):
        path = self._write_file("""### outcome_a: 1301 Foo\n- sourceSignalId: sig-1\n- signalDate: 2026-05-10\n- signalType: buyback / tob\n""")
        try:
            conn = sqlite3.connect(':memory:')
            create_schema(conn)
            self.mod.upsert_backtest(conn, path)
            oid = conn.execute('SELECT outcome_id FROM backtest_outcomes').fetchone()[0]
            self.assertEqual(oid, 'outcome_sig-1_2026-05-10_buyback_tob')
        finally:
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
