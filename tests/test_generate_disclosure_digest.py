from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GenerateDisclosureDigestTests(unittest.TestCase):
    def test_empty_db_still_renders_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db_path = tmp / "empty.db"
            output_dir = tmp / "inbox"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "create table daily_digest(topic text not null, date text not null, path text not null, summary text, updated_at text not null, primary key(topic, date))"
                )
                conn.execute(
                    "create table collection_artifacts(artifact_key text not null, artifact_date text not null, artifact_type text not null, payload_json text not null, updated_at text not null, primary key(artifact_key, artifact_date))"
                )
                conn.commit()
            finally:
                conn.close()
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/investment/analysis/generate_disclosure_digest.py"),
                    "--date",
                    "2026-06-11",
                    "--db",
                    str(db_path),
                    "--output-dir",
                    str(output_dir),
                    "--lookback-days",
                    "30",
                    "--limit",
                    "5",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                article = conn.execute(
                    "SELECT summary, path FROM daily_digest WHERE topic='disclosure-digest-article' AND date=?",
                    ("2026-06-11",),
                ).fetchone()
                note = conn.execute(
                    "SELECT summary, path FROM daily_digest WHERE topic='disclosure-digest-note' AND date=?",
                    ("2026-06-11",),
                ).fetchone()
                artifact = conn.execute(
                    "SELECT payload_json FROM collection_artifacts WHERE artifact_key='disclosure_digest' AND artifact_date=?",
                    ("2026-06-11",),
                ).fetchone()
            finally:
                conn.close()
            self.assertIsNotNone(article)
            self.assertIsNotNone(note)
            self.assertIsNotNone(artifact)
            article_path = output_dir / "2026-06-11-daily-disclosure-digest.md"
            note_path = output_dir / "2026-06-11-note-ready.md"
            self.assertTrue(article_path.exists())
            self.assertTrue(note_path.exists())
            self.assertIn("適時開示ダイジェスト 2026-06-11", article_path.read_text(encoding="utf-8"))
            self.assertIn("適時開示ダイジェスト 2026-06-11", note_path.read_text(encoding="utf-8"))
            self.assertIn("適時開示ダイジェスト 2026-06-11", article["summary"])
            self.assertIn("対象開示が見つかりませんでした", article["summary"])
            self.assertNotIn("朝のシグナル", note["summary"])
            payload = json.loads(artifact["payload_json"])
            self.assertEqual(payload["payload"]["date"], "2026-06-11")
            self.assertEqual(payload["payload"]["items"], [])
            self.assertTrue(str(article["path"]).endswith("2026-06-11-daily-disclosure-digest.md"))
            self.assertTrue(str(note["path"]).endswith("2026-06-11-note-ready.md"))

    def test_groups_multiple_disclosures_per_ticker_and_includes_price_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db_path = tmp / "digest.db"
            output_dir = tmp / "inbox"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "create table daily_digest(topic text not null, date text not null, path text not null, summary text, updated_at text not null, primary key(topic, date))"
                )
                conn.execute(
                    "create table collection_artifacts(artifact_key text not null, artifact_date text not null, artifact_type text not null, payload_json text not null, updated_at text not null, primary key(artifact_key, artifact_date))"
                )
                conn.execute(
                    "create table tdnet_disclosures(date text not null, disclosed_at text, ticker text not null, company text, title text, category text, tdnet_url text, source_kind text, source_path text not null)"
                )
                conn.execute(
                    "create table facts_price_daily(date text not null, ticker text not null, open real, high real, low real, close real, volume integer, source_kind text not null, source_url text, fetched_at text not null, updated_at text not null, primary key(date, ticker))"
                )
                conn.execute(
                    "create table market_signal_snapshots(date text not null, ticker text not null, slot text not null, snapshot_time text not null, price real, vwap real, vwap_gap_pct real, return_pct real, volume integer, volume_ratio real, source_kind text, source_ref text, payload_json text, updated_at text not null, primary key(date, ticker, slot, snapshot_time))"
                )
                conn.executemany(
                    "insert into tdnet_disclosures(date,disclosed_at,ticker,company,title,category,tdnet_url,source_kind,source_path) values(?,?,?,?,?,?,?,?,?)",
                    [
                        (
                            "2026-06-11",
                            "2026-06-11T08:00:00+09:00",
                            "1234",
                            "テスト社",
                            "2026年3月期 決算短信",
                            "upward_revision",
                            "https://example.com/a",
                            "tdnet_web",
                            "db:tdnet:1",
                        ),
                        (
                            "2026-06-11",
                            "2026-06-11T08:05:00+09:00",
                            "1234",
                            "テスト社",
                            "決算説明資料",
                            "upward_revision",
                            "https://example.com/b",
                            "tdnet_web",
                            "db:tdnet:2",
                        ),
                    ],
                )
                conn.executemany(
                    "insert into facts_price_daily(date,ticker,open,high,low,close,volume,source_kind,source_url,fetched_at,updated_at) values(?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        ("2026-06-09", "1234", 100, 104, 99, 100, 1000, "test", "", "now", "now"),
                        ("2026-06-10", "1234", 101, 106, 100, 105, 1000, "test", "", "now", "now"),
                        ("2026-06-11", "1234", 106, 112, 105, 110, 1000, "test", "", "now", "now"),
                        ("2026-06-12", "1234", 111, 115, 109, 114, 1000, "test", "", "now", "now"),
                    ],
                )
                conn.commit()
            finally:
                conn.close()
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/investment/analysis/generate_disclosure_digest.py"),
                    "--date",
                    "2026-06-11",
                    "--db",
                    str(db_path),
                    "--output-dir",
                    str(output_dir),
                    "--lookback-days",
                    "30",
                    "--limit",
                    "20",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            note_text = (output_dir / "2026-06-11-note-ready.md").read_text(encoding="utf-8")
            self.assertEqual(note_text.count("### テスト社 (1234)"), 1)
            self.assertIn("同銘柄で2件の開示", note_text)
            self.assertIn("価格反応: 当日終値 110.00", note_text)
            self.assertIn("前営業日比 +4.8%", note_text)
            self.assertIn("2026年3月期 決算短信", note_text)
            self.assertIn("決算説明資料", note_text)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                artifact = conn.execute(
                    "SELECT payload_json FROM collection_artifacts WHERE artifact_key='disclosure_digest' AND artifact_date=?",
                    ("2026-06-11",),
                ).fetchone()
            finally:
                conn.close()
            payload = json.loads(artifact["payload_json"])
            self.assertEqual(len(payload["payload"]["items"]), 1)
            self.assertEqual(len(payload["payload"]["items"][0]["disclosures"]), 2)

    def test_prefers_signal_price_snapshot_over_latest_fact_price(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db_path = tmp / "digest.db"
            output_dir = tmp / "inbox"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "create table daily_digest(topic text not null, date text not null, path text not null, summary text, updated_at text not null, primary key(topic, date))"
                )
                conn.execute(
                    "create table collection_artifacts(artifact_key text not null, artifact_date text not null, artifact_type text not null, payload_json text not null, updated_at text not null, primary key(artifact_key, artifact_date))"
                )
                conn.execute(
                    "create table tdnet_disclosures(date text not null, disclosed_at text, ticker text not null, company text, title text, category text, tdnet_url text, source_kind text, source_path text not null)"
                )
                conn.execute(
                    "create table facts_price_daily(date text not null, ticker text not null, open real, high real, low real, close real, volume integer, source_kind text not null, source_url text, fetched_at text not null, updated_at text not null, primary key(date, ticker))"
                )
                conn.execute(
                    "create table market_signal_snapshots(date text not null, ticker text not null, slot text not null, snapshot_time text not null, price real, vwap real, vwap_gap_pct real, return_pct real, volume integer, volume_ratio real, source_kind text, source_ref text, payload_json text, updated_at text not null, primary key(date, ticker, slot, snapshot_time))"
                )
                conn.execute(
                    "insert into tdnet_disclosures(date,disclosed_at,ticker,company,title,category,tdnet_url,source_kind,source_path) values(?,?,?,?,?,?,?,?,?)",
                    (
                        "2026-06-11",
                        "2026-06-11T08:00:00+09:00",
                        "1234",
                        "テスト社",
                        "決算短信",
                        "upward_revision",
                        "https://example.com/a",
                        "tdnet_web",
                        "db:tdnet:1",
                    ),
                )
                conn.executemany(
                    "insert into facts_price_daily(date,ticker,open,high,low,close,volume,source_kind,source_url,fetched_at,updated_at) values(?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        ("2026-06-09", "1234", 100, 104, 99, 100, 1000, "test", "", "now", "now"),
                        ("2026-06-10", "1234", 101, 106, 100, 105, 1000, "test", "", "now", "now"),
                        ("2026-06-11", "1234", 106, 112, 105, 110, 1000, "test", "", "now", "now"),
                    ],
                )
                conn.execute(
                    "insert into market_signal_snapshots(date,ticker,slot,snapshot_time,price,vwap,vwap_gap_pct,return_pct,volume,volume_ratio,source_kind,source_ref,payload_json,updated_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        "2026-06-11",
                        "1234",
                        "inv-evening-preclose",
                        "2026-06-11 06:00:00",
                        105,
                        105,
                        0.0,
                        5.0,
                        1000,
                        None,
                        "facts_price_daily_latest_close",
                        "facts_price_daily:2026-06-10",
                        json.dumps(
                            {
                                "source_date": "2026-06-10",
                                "prev_close_date": "2026-06-09",
                                "snapshot_kind": "signal_close",
                            },
                            ensure_ascii=False,
                        ),
                        "now",
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/investment/analysis/generate_disclosure_digest.py"),
                    "--date",
                    "2026-06-11",
                    "--db",
                    str(db_path),
                    "--output-dir",
                    str(output_dir),
                    "--lookback-days",
                    "30",
                    "--limit",
                    "20",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            note_text = (output_dir / "2026-06-11-note-ready.md").read_text(encoding="utf-8")
            self.assertIn("価格反応: 前営業日終値 2026-06-10 105.00", note_text)
            self.assertNotIn("当日終値 110.00", note_text)
            self.assertNotIn("直近終値 2026-06-11 110.00", note_text)

    def test_snapshot_script_writes_next_day_snapshot_from_signals_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db_path = tmp / "snapshot.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "create table signals(date text not null, ticker text not null, signal_id text, signal_type text, expected_direction text, long_rank integer, short_rank integer, gate_status text, source text, url text)"
                )
                conn.execute(
                    "create table facts_price_daily(date text not null, ticker text not null, open real, high real, low real, close real, volume integer, source_kind text not null, source_url text, fetched_at text not null, updated_at text not null, primary key(date, ticker))"
                )
                conn.execute(
                    "create table market_signal_snapshots(date text not null, ticker text not null, slot text not null, snapshot_time text not null, price real, vwap real, vwap_gap_pct real, return_pct real, volume integer, volume_ratio real, source_kind text, source_ref text, payload_json text, updated_at text not null, primary key(date, ticker, slot, snapshot_time))"
                )
                conn.executemany(
                    "insert into signals(date,ticker,signal_id,signal_type,expected_direction,long_rank,short_rank,gate_status,source,url) values(?,?,?,?,?,?,?,?,?,?)",
                    [
                        ("2026-06-10", "1234", "s1", "long", "up", 1, None, "pass", "test", ""),
                        ("2026-06-10", "5678", "s2", "short", "down", None, 1, "pass", "test", ""),
                    ],
                )
                conn.executemany(
                    "insert into facts_price_daily(date,ticker,open,high,low,close,volume,source_kind,source_url,fetched_at,updated_at) values(?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        ("2026-06-09", "1234", 100, 104, 99, 100, 1000, "test", "", "now", "now"),
                        ("2026-06-10", "1234", 101, 106, 100, 105, 1000, "test", "", "now", "now"),
                        ("2026-06-09", "5678", 200, 202, 198, 200, 1000, "test", "", "now", "now"),
                        ("2026-06-10", "5678", 201, 205, 199, 204, 1000, "test", "", "now", "now"),
                    ],
                )
                conn.commit()
            finally:
                conn.close()
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/investment/collect/snapshot_signal_prices.py"),
                    "--date",
                    "2026-06-10",
                    "--snapshot-date",
                    "2026-06-11",
                    "--db",
                    str(db_path),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT date,ticker,slot,price,source_ref,payload_json FROM market_signal_snapshots ORDER BY ticker"
                ).fetchall()
            finally:
                conn.close()
            self.assertEqual([r["date"] for r in rows], ["2026-06-11", "2026-06-11"])
            self.assertEqual([r["slot"] for r in rows], ["inv-evening-preclose", "inv-evening-preclose"])
            self.assertEqual([r["price"] for r in rows], [105.0, 204.0])
            self.assertTrue(all(str(r["source_ref"]).startswith("facts_price_daily:2026-06-10") for r in rows))

    def test_note_includes_signal_connection_and_recent_past_reaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db_path = tmp / "digest.db"
            output_dir = tmp / "inbox"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "create table daily_digest(topic text not null, date text not null, path text not null, summary text, updated_at text not null, primary key(topic, date))"
                )
                conn.execute(
                    "create table collection_artifacts(artifact_key text not null, artifact_date text not null, artifact_type text not null, payload_json text not null, updated_at text not null, primary key(artifact_key, artifact_date))"
                )
                conn.execute(
                    "create table tdnet_disclosures(date text not null, disclosed_at text, ticker text not null, company text, title text, category text, tdnet_url text, source_kind text, source_path text not null)"
                )
                conn.execute(
                    "create table facts_price_daily(date text not null, ticker text not null, open real, high real, low real, close real, volume integer, source_kind text not null, source_url text, fetched_at text not null, updated_at text not null, primary key(date, ticker))"
                )
                conn.execute(
                    "create table market_signal_snapshots(date text not null, ticker text not null, slot text not null, snapshot_time text not null, price real, vwap real, vwap_gap_pct real, return_pct real, volume integer, volume_ratio real, source_kind text, source_ref text, payload_json text, updated_at text not null, primary key(date, ticker, slot, snapshot_time))"
                )
                conn.execute(
                    "create table signals(date text not null, signal_id text not null, ticker text, company text, signal_type text, signal_type_label_ja text, expected_direction text, expected_direction_label_ja text, long_rank text, short_rank text, long_rank_label_ja text, short_rank_label_ja text, t1 text, t5 text, t20 text, gate_status text, gate_status_label_ja text, url text, source text, session text, material_signal_checked text, external_context_checked text, technical_signal_checked text, credit_status text, credit_buy_status text, credit_sell_status text, credit_source_kind text, credit_source_date text, credit_freshness_hours integer, payload_json text, source_path text, updated_at text, primary key(signal_id, date))"
                )
                conn.execute(
                    "create table entry_candidates(date text not null, side text not null, candidate_type text not null, signal_id text not null, ticker text, company text, rank text, long_rank text, short_rank text, expected_direction text, trade_use text, gate_status text, score real, url text, source_path text not null, updated_at text not null)"
                )
                conn.executemany(
                    "insert into tdnet_disclosures(date,disclosed_at,ticker,company,title,category,tdnet_url,source_kind,source_path) values(?,?,?,?,?,?,?,?,?)",
                    [
                        (
                            "2026-06-11",
                            "2026-06-11T08:00:00+09:00",
                            "4321",
                            "テスト社",
                            "決算短信",
                            "upward_revision",
                            "https://example.com/current",
                            "tdnet_web",
                            "db:tdnet:current",
                        ),
                        (
                            "2026-06-08",
                            "2026-06-08T08:00:00+09:00",
                            "4321",
                            "テスト社",
                            "前回の上方修正",
                            "upward_revision",
                            "https://example.com/past1",
                            "tdnet_web",
                            "db:tdnet:past1",
                        ),
                        (
                            "2026-06-05",
                            "2026-06-05T08:00:00+09:00",
                            "4321",
                            "テスト社",
                            "さらに前の上方修正",
                            "upward_revision",
                            "https://example.com/past2",
                            "tdnet_web",
                            "db:tdnet:past2",
                        ),
                    ],
                )
                conn.executemany(
                    "insert into facts_price_daily(date,ticker,open,high,low,close,volume,source_kind,source_url,fetched_at,updated_at) values(?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        ("2026-06-05", "4321", 100, 101, 99, 100, 1000, "test", "", "now", "now"),
                        ("2026-06-06", "4321", 101, 104, 100, 103, 1000, "test", "", "now", "now"),
                        ("2026-06-07", "4321", 103, 105, 102, 104, 1000, "test", "", "now", "now"),
                        ("2026-06-08", "4321", 104, 111, 103, 110, 1000, "test", "", "now", "now"),
                        ("2026-06-09", "4321", 111, 113, 110, 112, 1000, "test", "", "now", "now"),
                        ("2026-06-10", "4321", 112, 117, 111, 113, 1000, "test", "", "now", "now"),
                        ("2026-06-11", "4321", 113, 118, 112, 114, 1000, "test", "", "now", "now"),
                        ("2026-06-12", "4321", 114, 119, 113, 115, 1000, "test", "", "now", "now"),
                        ("2026-06-13", "4321", 115, 121, 114, 118, 1000, "test", "", "now", "now"),
                    ],
                )
                conn.executemany(
                    "insert into signals(date,signal_id,ticker,company,signal_type,signal_type_label_ja,expected_direction,expected_direction_label_ja,long_rank,short_rank,long_rank_label_ja,short_rank_label_ja,t1,t5,t20,gate_status,gate_status_label_ja,url,source,session,material_signal_checked,external_context_checked,technical_signal_checked,credit_status,credit_buy_status,credit_sell_status,credit_source_kind,credit_source_date,credit_freshness_hours,payload_json,source_path,updated_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        (
                            "2026-06-11",
                            "sig-1",
                            "4321",
                            "テスト社",
                            "upward_revision",
                            "上方修正",
                            "up",
                            "上昇",
                            "A",
                            "",
                            "A",
                            "",
                            "",
                            "",
                            "",
                            "pass",
                            "pass",
                            "https://example.com/s1",
                            "test",
                            "morning",
                            "yes",
                            "yes",
                            "yes",
                            "",
                            "",
                            "",
                            "",
                            "",
                            None,
                            "{}",
                            "db:signals",
                            "now",
                        ),
                        (
                            "2026-06-11",
                            "sig-2",
                            "4321",
                            "テスト社",
                            "upward_revision",
                            "上方修正",
                            "up",
                            "上昇",
                            "B",
                            "",
                            "B",
                            "",
                            "",
                            "",
                            "",
                            "pass",
                            "pass",
                            "https://example.com/s2",
                            "test",
                            "morning",
                            "yes",
                            "yes",
                            "yes",
                            "",
                            "",
                            "",
                            "",
                            "",
                            None,
                            "{}",
                            "db:signals",
                            "now",
                        ),
                    ],
                )
                conn.executemany(
                    "insert into entry_candidates(date,side,candidate_type,signal_id,ticker,company,rank,long_rank,short_rank,expected_direction,trade_use,gate_status,score,url,source_path,updated_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        (
                            "2026-06-11",
                            "long",
                            "primary",
                            "sig-1",
                            "4321",
                            "テスト社",
                            "1",
                            "A",
                            "",
                            "up",
                            "trade",
                            "pass",
                            88.0,
                            "https://example.com/e1",
                            "db:entry_candidates",
                            "now",
                        ),
                    ],
                )
                conn.execute(
                    "insert into market_signal_snapshots(date,ticker,slot,snapshot_time,price,vwap,vwap_gap_pct,return_pct,volume,volume_ratio,source_kind,source_ref,payload_json,updated_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        "2026-06-11",
                        "4321",
                        "inv-evening-preclose",
                        "2026-06-11 06:00:00",
                        116,
                        116,
                        0.0,
                        5.5,
                        1000,
                        None,
                        "facts_price_daily_latest_close",
                        "facts_price_daily:2026-06-10",
                        json.dumps(
                            {
                                "source_date": "2026-06-10",
                                "prev_close_date": "2026-06-09",
                                "snapshot_kind": "signal_close",
                            },
                            ensure_ascii=False,
                        ),
                        "now",
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/investment/analysis/generate_disclosure_digest.py"),
                    "--date",
                    "2026-06-11",
                    "--db",
                    str(db_path),
                    "--output-dir",
                    str(output_dir),
                    "--lookback-days",
                    "30",
                    "--limit",
                    "20",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            note_text = (output_dir / "2026-06-11-note-ready.md").read_text(encoding="utf-8")
            self.assertNotIn("シグナル接続:", note_text)
            self.assertIn("直近事例:", note_text)
            self.assertIn("2026-06-08 T+1 +1.8% / T+5 +7.3%", note_text)
            self.assertIn("2026-06-05 T+1 +3.0% / T+5 +13.0%", note_text)
            self.assertIn("価格反応: 前営業日終値 2026-06-10 116.00", note_text)

    def test_note_includes_us_market_overview_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db_path = tmp / "digest.db"
            output_dir = tmp / "inbox"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "create table daily_digest(topic text not null, date text not null, path text not null, summary text, updated_at text not null, primary key(topic, date))"
                )
                conn.execute(
                    "create table collection_artifacts(artifact_key text not null, artifact_date text not null, artifact_type text not null, payload_json text not null, updated_at text not null, primary key(artifact_key, artifact_date))"
                )
                conn.execute(
                    "create table tdnet_disclosures(date text not null, disclosed_at text, ticker text not null, company text, title text, category text, tdnet_url text, source_kind text, source_path text not null)"
                )
                conn.execute(
                    "insert into collection_artifacts(artifact_key,artifact_date,artifact_type,payload_json,updated_at) values(?,?,?,?,datetime('now'))",
                    (
                        "us_market_overview",
                        "2026-06-11",
                        "market_overview",
                        json.dumps(
                            {
                                "date": "2026-06-11",
                                "summary": "S&P500 -0.3% / Nasdaq -1.0% / Dow +0.2% / VIX +3.6% / USDJPY 160.54 (+0.10%)",
                                "sectorImpact": "半導体・グロースは注意 / 高PER・リスク資産は注意",
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/investment/analysis/generate_disclosure_digest.py"),
                    "--date",
                    "2026-06-11",
                    "--db",
                    str(db_path),
                    "--output-dir",
                    str(output_dir),
                    "--lookback-days",
                    "30",
                    "--limit",
                    "20",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            note_text = (output_dir / "2026-06-11-note-ready.md").read_text(encoding="utf-8")
            self.assertIn("## 朝の地合い", note_text)
            self.assertIn("米市場概況: S&P500 -0.3%", note_text)
            self.assertIn("日本セクター影響: 半導体・グロースは注意", note_text)


if __name__ == "__main__":
    unittest.main()
