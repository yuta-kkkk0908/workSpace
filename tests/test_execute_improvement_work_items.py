import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.investment.analysis import execute_improvement_work_items as mod


class ExecuteImprovementWorkItemsTests(unittest.TestCase):
    def test_slugify_branch_component_normalizes_and_truncates(self) -> None:
        value = mod.slugify_branch_component("AIOS / Alert Healthcheck!!!")
        self.assertEqual(value, "aios-alert-healthcheck")

    def test_make_branch_name_uses_item_id_and_source_key(self) -> None:
        item = {"id": 42, "source_key": "AIOS/Alert Healthcheck"}
        self.assertEqual(mod.make_branch_name(item), "improvement/item-42-aios-alert-healthcheck")

    def test_get_github_token_prefers_github_token_over_gh_token(self) -> None:
        with patch.dict(os.environ, {"GITHUB_TOKEN": "abc", "GH_TOKEN": "def"}, clear=True):
            self.assertEqual(mod.get_github_token(), "abc")

    def test_get_github_token_falls_back_to_gh_token(self) -> None:
        with patch.dict(os.environ, {"GH_TOKEN": "def"}, clear=True):
            self.assertEqual(mod.get_github_token(), "def")

    def test_create_worktree_branch_uses_branch_mode_when_branch_is_given(self) -> None:
        item = {"id": 7, "source_key": "test"}
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / ".codex-worktrees"
            with patch.object(mod, "clean_worktree_dir") as clean_mock, patch.object(mod.subprocess, "run") as run_mock:
                run_mock.return_value = mod.subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
                out = mod.create_worktree_branch(item, base, "improvement/item-7-test")
                self.assertTrue(out.exists() or out.parent.exists())
                clean_mock.assert_called_once()
                run_mock.assert_called_once()
                args, kwargs = run_mock.call_args
                self.assertIn("worktree", args[0])
                self.assertIn("-B", args[0])
                self.assertIn("improvement/item-7-test", args[0])
                self.assertEqual(kwargs["check"], True)

    def test_create_worktree_branch_uses_detach_mode_when_branch_is_missing(self) -> None:
        item = {"id": 8, "source_key": "test"}
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / ".codex-worktrees"
            with patch.object(mod, "clean_worktree_dir") as clean_mock, patch.object(mod.subprocess, "run") as run_mock:
                run_mock.return_value = mod.subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
                mod.create_worktree_branch(item, base, None)
                clean_mock.assert_called_once()
                run_mock.assert_called_once()
                args, kwargs = run_mock.call_args
                self.assertIn("worktree", args[0])
                self.assertIn("--detach", args[0])
                self.assertEqual(kwargs["check"], True)

    def test_run_validation_commands_handles_shell_syntax(self) -> None:
        cmds = ['python3 -c "import sys; sys.exit(2)"; test $? -eq 2']
        results = mod.run_validation_commands(Path("."), cmds)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["returncode"], 0)

    def test_build_prompt_with_feedback_embeds_feedback_block(self) -> None:
        item = {"id": 1, "source_key": "demo", "validation_commands_json": "[]"}
        context = {"resolved_target_files": [], "target_patterns": []}
        prompt = mod.build_prompt_with_feedback(item, context, "validate again")
        self.assertIn("validate again", prompt)
        self.assertIn('"source_key": "demo"', prompt)

    def test_parse_codex_json_result_returns_blocked_review_on_parse_failure(self) -> None:
        codex_run = {"command": ["codex"], "returncode": 0, "stdout": "", "stderr": ""}
        result = mod.parse_codex_json_result("", codex_run, stage="review")
        self.assertEqual(result["status"], "blocked")
        self.assertIn("review", result["summary"])
        self.assertEqual(result["findings"], [])

    def test_insert_audit_log_writes_row(self) -> None:
        conn = mod.sqlite3.connect(":memory:")
        try:
            conn.row_factory = mod.sqlite3.Row
            mod.ensure_audit_log_schema(conn)
            item = {"id": 1, "proposal_id": 2, "candidate_date": "2026-06-10", "source_key": "demo"}
            mod.insert_audit_log(
                conn,
                item=item,
                attempt_no=3,
                stage="execution",
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
            row = conn.execute("SELECT * FROM improvement_audit_log").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["stage"], "execution")
            self.assertEqual(row["attempt_no"], 3)
            self.assertEqual(row["summary"], "ok")
        finally:
            conn.close()

    def test_ensure_work_item_audit_link_schema_adds_column(self) -> None:
        conn = mod.sqlite3.connect(":memory:")
        try:
            conn.execute(
                """
                CREATE TABLE improvement_work_items (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  proposal_id INTEGER NOT NULL
                )
                """
            )
            mod.ensure_work_item_audit_link_schema(conn)
            cols = [row[1] for row in conn.execute("PRAGMA table_info(improvement_work_items)").fetchall()]
            self.assertIn("audit_log_ids_json", cols)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
