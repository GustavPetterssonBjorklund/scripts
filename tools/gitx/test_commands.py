from pathlib import Path
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from commands import (
    commit,
    format_conflict_context,
    merge,
    parse_merge_branches,
    parse_merge_conflicts,
    resolve_conflict_markers,
    tag,
)
from tui import MergeAction


class CommitCommandTests(unittest.TestCase):
    def test_message_args_are_joined_as_commit_message(self):
        with patch("commands.run", return_value=0) as run:
            result = commit(["update", "docs"])

        self.assertEqual(0, result)
        run.assert_called_once_with(["git", "commit", "-m", "update docs"])

    def test_git_commit_flags_are_passed_through(self):
        with patch("commands.run", return_value=0) as run:
            result = commit(["--amend"])

        self.assertEqual(0, result)
        run.assert_called_once_with(["git", "commit", "--amend"])

    def test_git_commit_flags_with_values_are_passed_through(self):
        with patch("commands.run", return_value=0) as run:
            result = commit(["--amend", "--no-edit"])

        self.assertEqual(0, result)
        run.assert_called_once_with(["git", "commit", "--amend", "--no-edit"])

    def test_git_flags_cannot_be_silently_mixed_with_ai_commit(self):
        with patch("commands.run") as run:
            with redirect_stdout(StringIO()):
                result = commit(["--ai", "--amend"])

        self.assertEqual(1, result)
        run.assert_not_called()


class TagCommandTests(unittest.TestCase):
    def test_regular_tag_args_pass_through_to_git_tag(self):
        with patch("commands.run", return_value=0) as run:
            result = tag(["-l"])

        self.assertEqual(0, result)
        run.assert_called_once_with(["git", "tag", "-l"])

    def test_ai_tag_creates_annotated_tag_after_approval(self):
        context = {
            "latest_tag": "v1.2.3",
            "previous_tags": "v1.2.3\t2026-04-01\tprevious",
            "previous_info": "Latest tag: v1.2.3",
            "recent_commits": "abc1234 feat: add thing",
        }

        with patch("commands._tag_context", return_value=context):
            with patch("commands.approve_generated_tag", return_value=("v1.3.0", "Release v1.3.0")):
                with patch("commands.run", return_value=0) as run:
                    result = tag(["--ai"])

        self.assertEqual(0, result)
        run.assert_called_once_with(["git", "tag", "-a", "v1.3.0", "-m", "Release v1.3.0"])


class MergeCommandTests(unittest.TestCase):
    def test_regular_merge_args_pass_through_to_git_merge(self):
        with patch("commands.run", return_value=0) as run:
            result = merge(["--abort"])

        self.assertEqual(0, result)
        run.assert_called_once_with(["git", "merge", "--abort"])

    def test_interactive_merge_runs_selected_branch(self):
        context = {
            "current_branch": "main",
            "status": "",
            "merge_in_progress": False,
            "branches": [],
            "conflicts": [],
        }

        with patch("commands._merge_context", return_value=context):
            with patch("commands.choose_merge_action", return_value=MergeAction("merge", "feature", "no-ff")):
                with patch("commands.run", return_value=0) as run:
                    result = merge([])

        self.assertEqual(0, result)
        run.assert_called_once_with(["git", "merge", "--no-ff", "feature"])

    def test_interactive_merge_can_squash_selected_branch(self):
        context = {
            "current_branch": "main",
            "status": "",
            "merge_in_progress": False,
            "branches": [],
            "conflicts": [],
        }

        with patch("commands._merge_context", return_value=context):
            with patch("commands.choose_merge_action", return_value=MergeAction("merge", "feature", "squash")):
                with patch("commands.run", return_value=0) as run:
                    result = merge([])

        self.assertEqual(0, result)
        run.assert_called_once_with(["git", "merge", "--squash", "feature"])

    def test_interactive_merge_can_continue_in_progress_merge(self):
        context = {
            "current_branch": "main",
            "status": "UU file.txt",
            "merge_in_progress": True,
            "branches": [],
            "conflicts": [],
        }

        with patch("commands._merge_context", return_value=context):
            with patch("commands.choose_merge_action", return_value=MergeAction("continue")):
                with patch("commands.run", return_value=0) as run:
                    result = merge([])

        self.assertEqual(0, result)
        run.assert_called_once_with(["git", "merge", "--continue"])

    def test_interactive_merge_can_stage_conflict_then_continue(self):
        context = {
            "current_branch": "main",
            "status": "UU file.txt",
            "merge_in_progress": True,
            "branches": [],
            "conflicts": parse_merge_conflicts("UU file.txt"),
        }

        with patch("commands._merge_context", return_value=context):
            with patch(
                "commands.choose_merge_action",
                side_effect=[
                    MergeAction("add-conflict", path="file.txt"),
                    MergeAction("continue"),
                ],
            ):
                with patch("commands.run", side_effect=[0, 0]) as run:
                    result = merge([])

        self.assertEqual(0, result)
        self.assertEqual([
            (["git", "add", "file.txt"],),
            (["git", "merge", "--continue"],),
        ], [call.args for call in run.call_args_list])

    def test_interactive_merge_can_edit_conflict_then_continue(self):
        context = {
            "current_branch": "main",
            "status": "UU file.txt",
            "merge_in_progress": True,
            "branches": [],
            "conflicts": parse_merge_conflicts("UU file.txt"),
        }

        with patch("commands._merge_context", return_value=context):
            with patch(
                "commands.choose_merge_action",
                side_effect=[
                    MergeAction("edit-conflict", path="file.txt"),
                    MergeAction("continue"),
                ],
            ):
                with patch("commands.edit_file", return_value=True) as edit_file:
                    with patch("commands.run", return_value=0) as run:
                        result = merge([])

        self.assertEqual(0, result)
        edit_file.assert_called_once_with("file.txt")
        run.assert_called_once_with(["git", "merge", "--continue"])

    def test_interactive_merge_can_accept_current_then_continue(self):
        context = {
            "current_branch": "main",
            "status": "UU file.txt",
            "merge_in_progress": True,
            "branches": [],
            "conflicts": parse_merge_conflicts("UU file.txt"),
        }

        with patch("commands._merge_context", return_value=context):
            with patch(
                "commands.choose_merge_action",
                side_effect=[
                    MergeAction("use-current", path="file.txt"),
                    MergeAction("continue"),
                ],
            ):
                with patch("commands.run", side_effect=[0, 0, 0]) as run:
                    result = merge([])

        self.assertEqual(0, result)
        self.assertEqual([
            (["git", "checkout", "--ours", "--", "file.txt"],),
            (["git", "add", "file.txt"],),
            (["git", "merge", "--continue"],),
        ], [call.args for call in run.call_args_list])

    def test_interactive_merge_can_accept_incoming_then_continue(self):
        context = {
            "current_branch": "main",
            "status": "UU file.txt",
            "merge_in_progress": True,
            "branches": [],
            "conflicts": parse_merge_conflicts("UU file.txt"),
        }

        with patch("commands._merge_context", return_value=context):
            with patch(
                "commands.choose_merge_action",
                side_effect=[
                    MergeAction("use-incoming", path="file.txt"),
                    MergeAction("continue"),
                ],
            ):
                with patch("commands.run", side_effect=[0, 0, 0]) as run:
                    result = merge([])

        self.assertEqual(0, result)
        self.assertEqual([
            (["git", "checkout", "--theirs", "--", "file.txt"],),
            (["git", "add", "file.txt"],),
            (["git", "merge", "--continue"],),
        ], [call.args for call in run.call_args_list])

    def test_interactive_merge_applies_approved_ai_proposal_then_continue(self):
        context = {
            "current_branch": "main",
            "status": "UU file.txt",
            "merge_in_progress": True,
            "branches": [],
            "conflicts": parse_merge_conflicts("UU file.txt"),
        }

        with patch("commands._merge_context", return_value=context):
            with patch(
                "commands.choose_merge_action",
                side_effect=[
                    MergeAction("apply-ai", path="file.txt", content="resolved\n"),
                    MergeAction("continue"),
                ],
            ):
                with patch("commands._write_ai_merge_resolution", return_value=True) as write_ai:
                    with patch("commands.run", side_effect=[0, 0]) as run:
                        result = merge([])

        self.assertEqual(0, result)
        write_ai.assert_called_once_with("file.txt", "resolved\n")
        self.assertEqual([
            (["git", "add", "file.txt"],),
            (["git", "merge", "--continue"],),
        ], [call.args for call in run.call_args_list])

    def test_parse_merge_conflicts_reads_unmerged_statuses(self):
        conflicts = parse_merge_conflicts("\n".join([
            " M normal.txt",
            "UU both-modified.txt",
            "AA both-added.txt",
            "R  old.txt -> renamed.txt",
        ]))

        self.assertEqual(["both-modified.txt", "both-added.txt"], [conflict.path for conflict in conflicts])
        self.assertEqual(["UU", "AA"], [conflict.status for conflict in conflicts])

    def test_resolve_conflict_markers_keeps_both_sides_without_markers(self):
        text = "\n".join([
            "before",
            "<<<<<<< HEAD",
            "ours",
            "=======",
            "theirs",
            ">>>>>>> feature",
            "after",
            "",
        ])

        resolved = resolve_conflict_markers(text, "both")

        self.assertEqual("before\nours\ntheirs\nafter\n", resolved)

    def test_format_conflict_context_labels_git_options(self):
        text = "\n".join([
            "<<<<<<< HEAD",
            "ours",
            "=======",
            "theirs",
            ">>>>>>> feature",
        ])

        context = format_conflict_context(text)

        self.assertIn("Current: keep our side", context)
        self.assertIn("Incoming: keep their side", context)
        self.assertIn("Both: keep current followed by incoming", context)
        self.assertIn("Current / ours:", context)
        self.assertIn("Incoming / theirs:", context)

    def test_parse_merge_branches_skips_current_and_remote_head(self):
        text = "\n".join([
            "main\torigin/main\t2 days ago\tmain work",
            "feature\torigin/feature\t1 hour ago\tadd thing",
            "origin/HEAD\t\t1 hour ago\torigin main",
            "origin/feature\t\t1 hour ago\tremote add thing",
            "feature\torigin/feature\t1 hour ago\tduplicate",
        ])

        branches = parse_merge_branches(text, "main")

        self.assertEqual(["feature", "origin/feature"], [branch.name for branch in branches])
        self.assertEqual("add thing", branches[0].subject)


if __name__ == "__main__":
    unittest.main()
