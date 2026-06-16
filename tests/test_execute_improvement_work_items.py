import os
import json
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from typing import Any
from unittest.mock import patch

from scripts.investment.analysis import execute_improvement_work_items as mod
from scripts.investment.analysis import generate_improvement_proposals_impl as proposals_mod


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

    def test_publication_state_records_github_token_presence(self) -> None:
        state = mod.publication_state("token123", "https://example.com/pr/1", True)
        self.assertEqual(state["enabled"], True)
        self.assertEqual(state["github_token_present"], True)
        self.assertEqual(state["published"], True)

    def test_resolve_codex_launcher_uses_current_path_environment(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path_dir = Path(td)
            launcher = path_dir / "codex.cmd"
            launcher.write_text("@echo off\r\nexit /b 0\r\n", encoding="utf-8")
            with patch.dict(os.environ, {"PATH": str(path_dir)}, clear=True):
                resolved = mod.resolve_codex_launcher()
                self.assertEqual(Path(resolved).name.lower(), "codex.cmd")

    def test_resolve_codex_launcher_raises_clear_error_when_missing(self) -> None:
        with patch.dict(os.environ, {"PATH": ""}, clear=True):
            with self.assertRaises(FileNotFoundError) as ctx:
                mod.resolve_codex_launcher()
        self.assertIn("codex not found on PATH", str(ctx.exception))
        self.assertIn("PATH=", str(ctx.exception))

    def test_load_codex_webhook_prefers_loger_env_name(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DISCORD_CODEX_LOGER_CHANNEL_HOOK": "https://example.com/loger",
                "DISCORD_CODEX_LOGGER_CHANNEL_HOOK": "https://example.com/logger",
            },
            clear=True,
        ):
            self.assertEqual(
                proposals_mod.load_codex_webhook(""),
                "https://example.com/loger",
            )

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
        cmds = ["& { exit 2 }"]
        results = mod.run_validation_commands(Path("."), cmds)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["returncode"], 2)

    def test_build_prompt_with_feedback_embeds_feedback_block(self) -> None:
        item = {"id": 1, "source_key": "demo", "validation_commands_json": "[]"}
        context = {"resolved_target_files": [], "target_patterns": []}
        prompt = mod.build_prompt_with_feedback(item, context, "validate again")
        self.assertIn("validate again", prompt)
        self.assertIn('"source_key": "demo"', prompt)

    def test_retry_feedback_helpers_branch_by_failure_reason(self) -> None:
        validation_feedback = mod.build_validation_retry_feedback("pytest -q", "ok", "boom")
        self.assertIn("失敗コマンド: pytest -q", validation_feedback)
        self.assertIn("stdout: ok", validation_feedback)
        self.assertIn("stderr: boom", validation_feedback)

        review_feedback = mod.build_review_retry_feedback(
            {
                "summary": "needs fixes",
                "findings": [{"severity": "high", "file": "a.py", "message": "fix this"}],
                "notes": "note",
            }
        )
        self.assertIn("自己レビューで修正要求あり: needs fixes", review_feedback)
        self.assertIn("[high] a.py: fix this", review_feedback)
        self.assertIn("note", review_feedback)

        blocked_feedback = mod.build_blocked_retry_feedback("codex output could not be parsed as JSON")
        self.assertIn("JSONとして解析できませんでした", blocked_feedback)
        self.assertIn("status", blocked_feedback)

    def test_parse_codex_json_result_returns_blocked_review_on_parse_failure(self) -> None:
        codex_run = {"command": ["codex"], "returncode": 0, "stdout": "", "stderr": ""}
        result = mod.parse_codex_json_result("", codex_run, stage="review")
        self.assertEqual(result["status"], "blocked")
        self.assertIn("review", result["summary"])
        self.assertEqual(result["findings"], [])

    def test_run_codex_json_stage_raises_clear_error_when_launcher_disappears(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            worktree = Path(td)
            with patch.object(mod, "resolve_codex_launcher", return_value="codex"), patch.object(
                mod.subprocess,
                "run",
                side_effect=FileNotFoundError(2, "No such file or directory"),
            ):
                with self.assertRaises(FileNotFoundError) as ctx:
                    mod.run_codex_json_stage(
                        prompt="{}",
                        model="",
                        worktree_root=worktree,
                        output_schema=mod.codex_output_schema(),
                        temp_prefix="codex-exec-test",
                    )
        self.assertIn("failed to launch codex", str(ctx.exception))
        self.assertIn("cwd=", str(ctx.exception))

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

    def test_update_work_item_persists_state_transition_and_audit_link(self) -> None:
        conn = mod.sqlite3.connect(":memory:")
        try:
            conn.row_factory = mod.sqlite3.Row
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
            mod.ensure_audit_log_schema(conn)
            log_id = mod.insert_audit_log(
                conn,
                item={"id": 1, "proposal_id": 2, "candidate_date": "2026-06-10", "source_key": "demo"},
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
            mod.update_work_item(
                conn,
                work_id=1,
                fields={
                    "work_status": "doing",
                    "review_status": "ready",
                    "audit_log_ids_json": f"[{log_id}]",
                    "branch_name": "branch",
                },
            )
            row = conn.execute("SELECT * FROM improvement_work_items WHERE id=1").fetchone()
            self.assertEqual(row["work_status"], "doing")
            self.assertEqual(row["review_status"], "ready")
            self.assertEqual(row["audit_log_ids_json"], f"[{log_id}]")
            self.assertEqual(row["branch_name"], "branch")
            audit_row = conn.execute("SELECT * FROM improvement_audit_log WHERE id=?", (log_id,)).fetchone()
            self.assertIsNotNone(audit_row)
            self.assertEqual(audit_row["pr_url"], "url")
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

    def test_main_retries_when_codex_produces_no_diff(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "ops.db"
            conn = mod.sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE improvement_work_items (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      proposal_id INTEGER NOT NULL,
                      candidate_date TEXT NOT NULL,
                      source_key TEXT NOT NULL,
                      repository_full_name TEXT NOT NULL,
                      work_title TEXT NOT NULL,
                      work_status TEXT NOT NULL,
                      work_priority INTEGER NOT NULL DEFAULT 0,
                      review_status TEXT NOT NULL DEFAULT 'pending',
                      blocked_reason TEXT,
                      error_message TEXT,
                      attempt_count INTEGER NOT NULL DEFAULT 0,
                      last_attempt_at TEXT,
                      work_body_json TEXT NOT NULL DEFAULT '{}',
                      validation_commands_json TEXT NOT NULL DEFAULT '[]',
                      audit_log_ids_json TEXT NOT NULL DEFAULT '[]',
                      branch_name TEXT,
                      commit_sha TEXT,
                      pr_url TEXT,
                      execution_commands_json TEXT NOT NULL DEFAULT '[]',
                      execution_result_json TEXT NOT NULL DEFAULT '{}',
                      validation_result_json TEXT NOT NULL DEFAULT '{}',
                      changed_files_json TEXT NOT NULL DEFAULT '[]',
                      diff_summary_json TEXT NOT NULL DEFAULT '{}',
                      completed_at TEXT,
                      updated_at TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO improvement_work_items(
                      id, proposal_id, candidate_date, source_key, repository_full_name,
                      work_title, work_status, work_priority, validation_commands_json,
                      work_body_json, review_status
                    ) VALUES(
                      1, 2, '2026-06-14', 'demo.source', 'openai/example',
                      'Improve demo', 'doing', 10, '[]',
                      '{"proposal": {}, "work": {"target_files": []}}', 'pending'
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

            worktree = root / "worktree"
            worktree.mkdir()
            exec_prompts: list[str] = []
            review_prompts: list[str] = []

            def fake_exec(prompt: str, model: str, worktree_root: Path) -> dict[str, Any]:
                exec_prompts.append(prompt)
                return {
                    "command": ["codex", "exec"],
                    "launcher": "codex",
                    "runtime": {"cwd": str(worktree_root)},
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                    "final_message": json.dumps(
                        {
                            "status": "done",
                            "summary": "applied",
                            "validation_commands": [],
                            "blocked_reason": "",
                            "notes": "",
                        },
                        ensure_ascii=False,
                    ),
                }

            def fake_review(prompt: str, model: str, worktree_root: Path) -> dict[str, Any]:
                review_prompts.append(prompt)
                return {
                    "command": ["codex", "exec"],
                    "launcher": "codex",
                    "runtime": {"cwd": str(worktree_root)},
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                    "final_message": json.dumps(
                        {
                            "status": "done",
                            "summary": "review ok",
                            "findings": [],
                            "blocked_reason": "",
                            "notes": "",
                        },
                        ensure_ascii=False,
                    ),
                }

            with patch.object(mod, "parse_args", return_value=SimpleNamespace(
                date="2026-06-14",
                db=db_path,
                limit=1,
                work_id=1,
                model_route="improvement_execution_engine",
                model="",
                dry_run=False,
                context_chars=12000,
                validation_retry_rounds=2,
                review_retry_rounds=2,
                max_rounds=3,
            )), patch.object(mod, "load_dotenv"), patch.object(mod, "resolve_model", return_value=(None, "test-model")), patch.object(mod, "get_github_token", return_value=""), patch.object(mod, "create_worktree_branch", return_value=worktree), patch.object(mod, "sync_worktree_inputs", return_value={"target_patterns": [], "resolved_target_files": [], "git_status": "", "git_diff_stat": ""}), patch.object(mod, "run_codex_exec", side_effect=fake_exec), patch.object(mod, "run_codex_review", side_effect=fake_review), patch.object(mod, "run_validation_commands", return_value=[]), patch.object(mod, "git_has_changes", side_effect=[False, True]), patch.object(mod, "commit_changes", return_value="abc123"), patch.object(mod, "commit_changed_files", return_value=["changed.py"]), patch.object(mod, "commit_diff_summary", return_value={"returncode": 0, "stat": "changed.py | 1 +", "error": ""}), patch.object(mod, "update_work_item"), patch.object(mod, "cleanup_worktree"):
                rc = mod.main()

            self.assertEqual(rc, 0)
            self.assertEqual(len(exec_prompts), 2)
            self.assertEqual(len(review_prompts), 2)
            self.assertIn("ファイル差分が作成されませんでした", exec_prompts[1])
            self.assertIn("Improve demo", exec_prompts[0])

            conn = mod.sqlite3.connect(db_path)
            try:
                conn.row_factory = mod.sqlite3.Row
                rows = conn.execute(
                    "SELECT stage, event_type, status, summary FROM improvement_audit_log ORDER BY id"
                ).fetchall()
                self.assertEqual(len(rows), 8)
                self.assertIn("retry", [row["event_type"] for row in rows])
                retry_row = next(row for row in rows if row["event_type"] == "retry")
                self.assertEqual(retry_row["stage"], "retry")
                self.assertEqual(retry_row["status"], "retry")
                self.assertIn("no diff", retry_row["summary"])
            finally:
                conn.close()

    def test_main_retries_when_codex_output_is_not_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "ops.db"
            conn = mod.sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE improvement_work_items (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      proposal_id INTEGER NOT NULL,
                      candidate_date TEXT NOT NULL,
                      source_key TEXT NOT NULL,
                      repository_full_name TEXT NOT NULL,
                      work_title TEXT NOT NULL,
                      work_status TEXT NOT NULL,
                      work_priority INTEGER NOT NULL DEFAULT 0,
                      review_status TEXT NOT NULL DEFAULT 'pending',
                      blocked_reason TEXT,
                      error_message TEXT,
                      attempt_count INTEGER NOT NULL DEFAULT 0,
                      last_attempt_at TEXT,
                      work_body_json TEXT NOT NULL DEFAULT '{}',
                      validation_commands_json TEXT NOT NULL DEFAULT '[]',
                      audit_log_ids_json TEXT NOT NULL DEFAULT '[]',
                      branch_name TEXT,
                      commit_sha TEXT,
                      pr_url TEXT,
                      execution_commands_json TEXT NOT NULL DEFAULT '[]',
                      execution_result_json TEXT NOT NULL DEFAULT '{}',
                      validation_result_json TEXT NOT NULL DEFAULT '{}',
                      changed_files_json TEXT NOT NULL DEFAULT '[]',
                      diff_summary_json TEXT NOT NULL DEFAULT '{}',
                      completed_at TEXT,
                      updated_at TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO improvement_work_items(
                      id, proposal_id, candidate_date, source_key, repository_full_name,
                      work_title, work_status, work_priority, validation_commands_json,
                      work_body_json, review_status
                    ) VALUES(
                      1, 2, '2026-06-14', 'demo.source', 'openai/example',
                      'Improve demo', 'doing', 10, '[]',
                      '{"proposal": {}, "work": {"target_files": []}}', 'pending'
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

            worktree = root / "worktree"
            worktree.mkdir()
            exec_prompts: list[str] = []
            review_prompts: list[str] = []

            def fake_exec(prompt: str, model: str, worktree_root: Path) -> dict[str, Any]:
                exec_prompts.append(prompt)
                if len(exec_prompts) == 1:
                    return {
                        "command": ["codex", "exec"],
                        "launcher": "codex",
                        "runtime": {"cwd": str(worktree_root)},
                        "returncode": 0,
                        "stdout": "not json",
                        "stderr": "",
                        "final_message": "not json",
                    }
                return {
                    "command": ["codex", "exec"],
                    "launcher": "codex",
                    "runtime": {"cwd": str(worktree_root)},
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                    "final_message": json.dumps(
                        {
                            "status": "done",
                            "summary": "applied",
                            "validation_commands": [],
                            "blocked_reason": "",
                            "notes": "",
                        },
                        ensure_ascii=False,
                    ),
                }

            def fake_review(prompt: str, model: str, worktree_root: Path) -> dict[str, Any]:
                review_prompts.append(prompt)
                return {
                    "command": ["codex", "exec"],
                    "launcher": "codex",
                    "runtime": {"cwd": str(worktree_root)},
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                    "final_message": json.dumps(
                        {
                            "status": "done",
                            "summary": "review ok",
                            "findings": [],
                            "blocked_reason": "",
                            "notes": "",
                        },
                        ensure_ascii=False,
                    ),
                }

            with patch.object(mod, "parse_args", return_value=SimpleNamespace(
                date="2026-06-14",
                db=db_path,
                limit=1,
                work_id=1,
                model_route="improvement_execution_engine",
                model="",
                dry_run=False,
                context_chars=12000,
                validation_retry_rounds=2,
                review_retry_rounds=2,
                max_rounds=3,
            )), patch.object(mod, "load_dotenv"), patch.object(mod, "resolve_model", return_value=(None, "test-model")), patch.object(mod, "get_github_token", return_value=""), patch.object(mod, "create_worktree_branch", return_value=worktree), patch.object(mod, "sync_worktree_inputs", return_value={"target_patterns": [], "resolved_target_files": [], "git_status": "", "git_diff_stat": ""}), patch.object(mod, "run_codex_exec", side_effect=fake_exec), patch.object(mod, "run_codex_review", side_effect=fake_review), patch.object(mod, "run_validation_commands", return_value=[]), patch.object(mod, "git_has_changes", return_value=True), patch.object(mod, "commit_changes", return_value="abc123"), patch.object(mod, "commit_changed_files", return_value=["changed.py"]), patch.object(mod, "commit_diff_summary", return_value={"returncode": 0, "stat": "changed.py | 1 +", "error": ""}), patch.object(mod, "update_work_item"), patch.object(mod, "cleanup_worktree"):
                rc = mod.main()

            self.assertEqual(rc, 0)
            self.assertEqual(len(exec_prompts), 2)
            self.assertEqual(len(review_prompts), 1)
            self.assertIn("JSONとして解析できませんでした", exec_prompts[1])
            self.assertIn("Improve demo", exec_prompts[0])

    def test_validation_and_review_retry_budgets_are_independent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "ops.db"
            conn = mod.sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE improvement_work_items (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      proposal_id INTEGER NOT NULL,
                      candidate_date TEXT NOT NULL,
                      source_key TEXT NOT NULL,
                      repository_full_name TEXT NOT NULL,
                      work_title TEXT NOT NULL,
                      work_status TEXT NOT NULL,
                      work_priority INTEGER NOT NULL DEFAULT 0,
                      review_status TEXT NOT NULL DEFAULT 'pending',
                      blocked_reason TEXT,
                      error_message TEXT,
                      attempt_count INTEGER NOT NULL DEFAULT 0,
                      last_attempt_at TEXT,
                      work_body_json TEXT NOT NULL DEFAULT '{}',
                      validation_commands_json TEXT NOT NULL DEFAULT '[]',
                      audit_log_ids_json TEXT NOT NULL DEFAULT '[]',
                      branch_name TEXT,
                      commit_sha TEXT,
                      pr_url TEXT,
                      execution_commands_json TEXT NOT NULL DEFAULT '[]',
                      execution_result_json TEXT NOT NULL DEFAULT '{}',
                      validation_result_json TEXT NOT NULL DEFAULT '{}',
                      changed_files_json TEXT NOT NULL DEFAULT '[]',
                      diff_summary_json TEXT NOT NULL DEFAULT '{}',
                      completed_at TEXT,
                      updated_at TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO improvement_work_items(
                      id, proposal_id, candidate_date, source_key, repository_full_name,
                      work_title, work_status, work_priority, validation_commands_json,
                      work_body_json, review_status
                    ) VALUES(
                      1, 2, '2026-06-14', 'demo.source', 'openai/example',
                      'Improve demo', 'doing', 10, '["pytest -q"]',
                      '{"proposal": {}, "work": {"target_files": []}}', 'pending'
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

            worktree = root / "worktree"
            worktree.mkdir()
            exec_prompts: list[str] = []
            review_prompts: list[str] = []
            validation_calls = {"count": 0}

            def fake_exec(prompt: str, model: str, worktree_root: Path) -> dict[str, Any]:
                exec_prompts.append(prompt)
                return {
                    "command": ["codex", "exec"],
                    "launcher": "codex",
                    "runtime": {"cwd": str(worktree_root)},
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                    "final_message": json.dumps(
                        {
                            "status": "done",
                            "summary": "applied",
                            "validation_commands": ["pytest -q"],
                            "blocked_reason": "",
                            "notes": "",
                        },
                        ensure_ascii=False,
                    ),
                }

            def fake_review(prompt: str, model: str, worktree_root: Path) -> dict[str, Any]:
                review_prompts.append(prompt)
                status = "revise" if len(review_prompts) == 1 else "done"
                payload = {
                    "status": status,
                    "summary": "review" if status == "done" else "needs more work",
                    "findings": [] if status == "done" else [{"severity": "medium", "file": "a.py", "message": "adjust"}],
                    "blocked_reason": "",
                    "notes": "",
                }
                return {
                    "command": ["codex", "exec"],
                    "launcher": "codex",
                    "runtime": {"cwd": str(worktree_root)},
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                    "final_message": json.dumps(payload, ensure_ascii=False),
                }

            def fake_validation(base_dir: Path, commands: list[str]) -> list[dict[str, Any]]:
                validation_calls["count"] += 1
                if validation_calls["count"] == 1:
                    return [{"command": commands[0], "returncode": 1, "stdout": "", "stderr": "boom"}]
                return [{"command": commands[0], "returncode": 0, "stdout": "", "stderr": ""}]

            with patch.object(mod, "parse_args", return_value=SimpleNamespace(
                date="2026-06-14",
                db=db_path,
                limit=1,
                work_id=1,
                model_route="improvement_execution_engine",
                model="",
                dry_run=False,
                context_chars=12000,
                max_rounds=3,
                validation_retry_rounds=1,
                review_retry_rounds=1,
            )), patch.object(mod, "load_dotenv"), patch.object(mod, "resolve_model", return_value=(None, "test-model")), patch.object(mod, "get_github_token", return_value=""), patch.object(mod, "create_worktree_branch", return_value=worktree), patch.object(mod, "sync_worktree_inputs", return_value={"target_patterns": [], "resolved_target_files": [], "git_status": "", "git_diff_stat": ""}), patch.object(mod, "run_codex_exec", side_effect=fake_exec), patch.object(mod, "run_codex_review", side_effect=fake_review), patch.object(mod, "run_validation_commands", side_effect=fake_validation), patch.object(mod, "git_has_changes", return_value=True), patch.object(mod, "commit_changes", return_value="abc123"), patch.object(mod, "commit_changed_files", return_value=["changed.py"]), patch.object(mod, "commit_diff_summary", return_value={"returncode": 0, "stat": "changed.py | 1 +", "error": ""}), patch.object(mod, "update_work_item"), patch.object(mod, "cleanup_worktree"):
                rc = mod.main()

            self.assertEqual(rc, 0)
            self.assertEqual(len(exec_prompts), 3)
            self.assertEqual(len(review_prompts), 2)
            self.assertEqual(validation_calls["count"], 3)
            self.assertIn("Improve demo", exec_prompts[0])


if __name__ == "__main__":
    unittest.main()
