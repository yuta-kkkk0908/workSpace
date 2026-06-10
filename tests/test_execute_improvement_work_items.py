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


if __name__ == "__main__":
    unittest.main()
