from pathlib import Path
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from commands import commit, tag


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


if __name__ == "__main__":
    unittest.main()
