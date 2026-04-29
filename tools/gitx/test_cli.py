from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli import main


class CliTests(unittest.TestCase):
    def test_unknown_command_passes_through_to_git(self):
        with patch.object(sys, "argv", ["gitx", "branch", "-l"]):
            with patch("cli.run", return_value=0) as run:
                result = main()

        self.assertEqual(0, result)
        run.assert_called_once_with(["git", "branch", "-l"])

    def test_git_top_level_options_pass_through_to_git(self):
        with patch.object(sys, "argv", ["gitx", "-C", "/tmp/repo", "status"]):
            with patch("cli.run", return_value=0) as run:
                result = main()

        self.assertEqual(0, result)
        run.assert_called_once_with(["git", "-C", "/tmp/repo", "status"])

    def test_known_alias_still_uses_gitx_behavior(self):
        with patch.object(sys, "argv", ["gitx", "s"]):
            with patch("cli.run", return_value=0) as run:
                result = main()

        self.assertEqual(0, result)
        run.assert_called_once_with(["git", "status"])


if __name__ == "__main__":
    unittest.main()
