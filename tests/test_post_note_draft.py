from __future__ import annotations

import tempfile
from pathlib import Path
import unittest
import sqlite3

from scripts.notify.post_note_draft import (
    load_markdown_from_db,
    markdown_to_note_html,
    parse_markdown,
    save_note_post_audit,
    update_note_post_audit,
)


class NoteDraftTests(unittest.TestCase):
    def test_parse_markdown_splits_title_and_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "note.md"
            path.write_text(
                "\n".join(
                    [
                        "日次の下書き",
                        "",
                        "## 見出し",
                        "- 項目1",
                        "- 項目2",
                    ]
                ),
                encoding="utf-8",
            )
            title, body = parse_markdown(path)
            self.assertEqual(title, "日次の下書き")
            self.assertIn("## 見出し", body)
            self.assertIn("- 項目1", body)

    def test_markdown_to_note_html_handles_headings_lists_and_links(self) -> None:
        html = markdown_to_note_html(
            "\n".join(
                [
                    "# タイトル",
                    "",
                    "## 章",
                    "- https://example.com",
                ]
            )
        )
        self.assertIn("<h1>", html)
        self.assertIn("<h2>", html)
        self.assertIn("<ul>", html)
        self.assertIn("<a href=\"https://example.com\">https://example.com</a>", html)

    def test_load_markdown_from_db_reads_daily_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "digest.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "create table daily_digest(topic text not null, date text not null, path text not null, summary text, updated_at text not null, primary key(topic, date))"
                )
                conn.execute(
                    "insert into daily_digest(topic,date,path,summary,updated_at) values(?,?,?,?,datetime('now'))",
                    ("disclosure-digest-note", "2026-06-11", "db:daily_digest:disclosure-digest-note", "適時開示ダイジェスト 2026-06-11\n\n## 朝のシグナル\n- なし\n"),
                )
                conn.commit()
            finally:
                conn.close()
            text, source_kind, source_label = load_markdown_from_db(db_path, "2026-06-11", "disclosure-digest-note")
            self.assertIn("朝のシグナル", text)
            self.assertEqual(source_kind, "daily_digest:disclosure-digest-note")
            self.assertEqual(source_label, "db:daily_digest:disclosure-digest-note")

    def test_load_markdown_from_db_falls_back_to_collection_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "digest.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "create table collection_artifacts(artifact_key text not null, artifact_date text not null, artifact_type text not null, payload_json text not null, updated_at text not null, primary key(artifact_key, artifact_date))"
                )
                conn.execute(
                    "insert into collection_artifacts(artifact_key,artifact_date,artifact_type,payload_json,updated_at) values(?,?,?,?,datetime('now'))",
                    (
                        "disclosure_digest",
                        "2026-06-11",
                        "daily_digest",
                        '{"note_markdown":"適時開示ダイジェスト 2026-06-11\\n\\n## 朝のシグナル\\n- 強気寄り\\n"}',
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            text, source_kind, source_label = load_markdown_from_db(db_path, "2026-06-11", "disclosure-digest-note")
            self.assertIn("強気寄り", text)
            self.assertEqual(source_kind, "collection_artifacts:disclosure_digest")
            self.assertEqual(source_label, "")

    def test_save_note_post_audit_persists_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "digest.db"
            row_id = save_note_post_audit(
                db_path,
                {
                    "target_date": "2026-06-11",
                    "digest_topic": "disclosure-digest-note",
                    "title": "適時開示ダイジェスト 2026-06-11",
                    "markdown_source": "topics/investment-research/inbox/2026-06-11-note-ready.md",
                    "markdown_source_kind": "markdown_path",
                    "note_config_path": "configs/note.local.json",
                    "mode": "body_only",
                    "status": "ok",
                    "error": None,
                    "screenshot_path": "logs/disclosure-note-post-2026-06-11.png",
                    "started_at": "2026-06-11T09:00:00",
                    "saved_at": "2026-06-11T09:00:05",
                },
            )
            self.assertIsNotNone(row_id)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "select target_date,digest_topic,status,mode,screenshot_path,payload_json from note_draft_posts"
                ).fetchone()
            finally:
                conn.close()
            self.assertIsNotNone(row)
            self.assertEqual(row["target_date"], "2026-06-11")
            self.assertEqual(row["digest_topic"], "disclosure-digest-note")
            self.assertEqual(row["status"], "ok")
            self.assertEqual(row["mode"], "body_only")
            self.assertTrue(str(row["screenshot_path"]).endswith("2026-06-11.png"))
            self.assertIn("markdown_source_kind", row["payload_json"])

    def test_update_note_post_audit_updates_status_and_finished_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "digest.db"
            row_id = save_note_post_audit(
                db_path,
                {
                    "target_date": "2026-06-11",
                    "digest_topic": "disclosure-digest-note",
                    "title": "",
                    "markdown_source": "pending",
                    "markdown_source_kind": "pending",
                    "note_config_path": "configs/note.local.json",
                    "mode": None,
                    "status": "started",
                    "error": None,
                    "screenshot_path": None,
                    "started_at": "2026-06-11T09:00:00",
                    "saved_at": None,
                    "finished_at": None,
                },
            )
            update_note_post_audit(
                db_path,
                row_id,
                {
                    "target_date": "2026-06-11",
                    "digest_topic": "disclosure-digest-note",
                    "title": "適時開示ダイジェスト 2026-06-11",
                    "markdown_source": "topics/investment-research/inbox/2026-06-11-note-ready.md",
                    "markdown_source_kind": "markdown_path",
                    "note_config_path": "configs/note.local.json",
                    "mode": "title_and_body",
                    "status": "error",
                    "error": "save control not found",
                    "screenshot_path": "logs/disclosure-note-post-2026-06-11.png",
                    "started_at": "2026-06-11T09:00:00",
                    "saved_at": None,
                    "finished_at": "2026-06-11T09:00:10",
                },
            )
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "select status,error,finished_at,mode,title from note_draft_posts where id=?",
                    (row_id,),
                ).fetchone()
            finally:
                conn.close()
            self.assertIsNotNone(row)
            self.assertEqual(row["status"], "error")
            self.assertEqual(row["error"], "save control not found")
            self.assertEqual(row["finished_at"], "2026-06-11T09:00:10")
            self.assertEqual(row["mode"], "title_and_body")
            self.assertEqual(row["title"], "適時開示ダイジェスト 2026-06-11")


if __name__ == "__main__":
    unittest.main()
