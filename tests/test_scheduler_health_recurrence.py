import json
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from scripts import check_scheduler_health as health
from scripts.data import ingest_ops_logs as ingest
from scripts.investment.analysis import execute_improvement_work_items as exec_mod


class SchedulerHealthRecurrenceTests(unittest.TestCase):
    def test_health_uses_stored_source_key_and_separates_notifications(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir(parents=True, exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)
            now = health.datetime.now(health.JST)
            stamps = [
                (now - health.timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - health.timedelta(minutes=29)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - health.timedelta(minutes=28)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - health.timedelta(minutes=27)).strftime("%Y-%m-%d %H:%M:%S"),
                (now - health.timedelta(minutes=26)).strftime("%Y-%m-%d %H:%M:%S"),
            ]

            task_log = logs_dir / "task-scheduler.log"
            task_log.write_text(
                "\n".join(
                    [
                        f"[{stamps[0]}] [AIOS-DB-Backup-2230] [START] begin",
                        f"[{stamps[1]}] [AIOS-DB-Backup-2230] [ERROR] exit_code=1",
                        f"[{stamps[2]}] [AIOS-DB-Backup-2230] [OK] recovered",
                        f"[{stamps[3]}] [AIOS-DB-Backup-2230] [EXCEPTION] exit_code=1",
                        f"[{stamps[4]}] [AIOS-DB-Backup-2230] [ERROR] exit_code=1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            ops_db = data_dir / "ops.db"
            conn = sqlite3.connect(ops_db)
            try:
                conn.execute(
                    """
                    CREATE TABLE task_log_events (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      ts TEXT NOT NULL,
                      task_name TEXT NOT NULL,
                      source_key TEXT,
                      level TEXT NOT NULL,
                      message TEXT,
                      source_file TEXT NOT NULL,
                      raw_line TEXT NOT NULL,
                      ingested_at TEXT NOT NULL,
                      UNIQUE(ts, task_name, level, raw_line)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE discord_log_events (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      ts TEXT NOT NULL,
                      channel TEXT NOT NULL,
                      level TEXT NOT NULL,
                      message TEXT,
                      source_file TEXT NOT NULL,
                      raw_line TEXT NOT NULL,
                      ingested_at TEXT NOT NULL,
                      UNIQUE(ts, channel, level, raw_line)
                    )
                    """
                )
                ingest.ensure_task_source_key_schema(conn)
                ingest.ingest_task_log(conn, task_log)
                conn.commit()

                row = conn.execute(
                    "SELECT task_name, source_key FROM task_log_events ORDER BY id LIMIT 1"
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], "AIOS-DB-Backup-2230")
                self.assertEqual(row[1], "ops.task.aios-db-backup-2230")
            finally:
                conn.close()

            out_json = root / "tmp" / "prompts" / "scheduler-health.json"
            out_status = root / "tmp" / "prompts" / "scheduler-health.status.txt"

            with (
                patch.object(health, "ROOT", root),
                patch.object(health, "resolve_investment_db", return_value=root / "data" / "investment.db"),
                patch.object(
                    health,
                    "parse_args",
                    return_value=Namespace(
                        mode="daily",
                        hours=24,
                        tasks=["AIOS-DB-Backup-2230"],
                        task_log="logs/task-scheduler.log",
                        out_json="tmp/prompts/scheduler-health.json",
                        out_status="tmp/prompts/scheduler-health.status.txt",
                        ops_db="data/ops.db",
                    ),
                ),
            ):
                rc = health.main()

            self.assertEqual(rc, 2)
            payload = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "ALERT")
            self.assertEqual(payload["notificationThreshold"], 2)
            self.assertEqual(payload["recurringSourceKeys"]["ops.task.aios-db-backup-2230"]["error_count"], 2)
            self.assertEqual(
                payload["recurringSourceKeys"]["ops.task.aios-db-backup-2230"]["total_error_count"],
                3,
            )
            self.assertIn("ops.task.aios-db-backup-2230", payload["notifications"][0])
            self.assertIn("ops.task.aios-db-backup-2230", payload["notificationSourceKeys"])
            self.assertIn("通知対象", out_status.read_text(encoding="utf-8"))

    def test_work_item_state_transition_is_persisted_in_db(self) -> None:
        conn = exec_mod.sqlite3.connect(":memory:")
        try:
            conn.row_factory = exec_mod.sqlite3.Row
            conn.execute(
                """
                CREATE TABLE improvement_work_items (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  work_status TEXT,
                  review_status TEXT,
                  blocked_reason TEXT,
                  error_message TEXT,
                  branch_name TEXT,
                  commit_sha TEXT,
                  pr_url TEXT,
                  audit_log_ids_json TEXT NOT NULL DEFAULT '[]',
                  updated_at TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO improvement_work_items(id, work_status, review_status, audit_log_ids_json) VALUES(1, 'open', 'pending', '[]')"
            )
            exec_mod.ensure_audit_log_schema(conn)
            audit_id = exec_mod.insert_audit_log(
                conn,
                item={"id": 1, "proposal_id": 1, "candidate_date": "2026-06-13", "source_key": "ops.task.demo"},
                attempt_no=1,
                stage="final",
                round_no=1,
                event_type="stage",
                status="done",
                summary="ok",
                blocked_reason=None,
                input_payload={"prompt": "x"},
                output_payload={"result": "y"},
                validation_payload={"commands": []},
                review_payload={},
                branch_name="branch",
                commit_sha="sha",
                pr_url="url",
            )
            exec_mod.update_work_item(
                conn,
                work_id=1,
                fields={
                    "work_status": "done",
                    "review_status": "ready",
                    "audit_log_ids_json": json.dumps([audit_id]),
                    "branch_name": "branch",
                    "commit_sha": "sha",
                    "pr_url": "url",
                },
            )
            row = conn.execute("SELECT * FROM improvement_work_items WHERE id=1").fetchone()
            self.assertEqual(row["work_status"], "done")
            self.assertEqual(row["review_status"], "ready")
            self.assertEqual(row["audit_log_ids_json"], json.dumps([audit_id]))
            self.assertEqual(row["pr_url"], "url")
            audit_row = conn.execute("SELECT * FROM improvement_audit_log WHERE id=?", (audit_id,)).fetchone()
            self.assertIsNotNone(audit_row)
            self.assertEqual(audit_row["branch_name"], "branch")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
