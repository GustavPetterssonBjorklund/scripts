from pathlib import Path
import argparse
import importlib.util
import sys
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parent / "copy.py"
MODULE_SPEC = importlib.util.spec_from_file_location("copy_tool", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
copy_module = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(copy_module)


class ResolveTextTests(unittest.TestCase):
    def setUp(self):
        self.parser = argparse.ArgumentParser(prog="copy")

    def test_prefers_arguments_over_other_sources(self):
        args = argparse.Namespace(primary=False, text=["Hello", "World"])

        with patch.object(copy_module, "stdin_has_data", return_value=True):
            with patch.object(copy_module, "read_tmux_previous_command", return_value="tmux text\n"):
                with patch.object(copy_module.sys, "stdin") as fake_stdin:
                    fake_stdin.read.return_value = "stdin text\n"
                    resolved = copy_module.resolve_text(args, self.parser)

        self.assertEqual("Hello World", resolved)

    def test_prefers_stdin_over_tmux_recovery(self):
        args = argparse.Namespace(primary=False, text=[])

        with patch.object(copy_module, "stdin_has_data", return_value=True):
            with patch.object(copy_module, "read_tmux_previous_command", return_value="tmux text\n"):
                with patch.object(copy_module.sys, "stdin") as fake_stdin:
                    fake_stdin.read.return_value = "stdin text\n"
                    resolved = copy_module.resolve_text(args, self.parser)

        self.assertEqual("stdin text\n", resolved)

    def test_falls_back_to_tmux_when_stdin_missing(self):
        args = argparse.Namespace(primary=True, text=[])

        with patch.object(copy_module, "stdin_has_data", return_value=False):
            with patch.object(copy_module, "read_tmux_previous_command", return_value="tmux text\n") as read_tmux:
                resolved = copy_module.resolve_text(args, self.parser)

        self.assertEqual("tmux text\n", resolved)
        read_tmux.assert_called_once_with(["copy", "copy --primary", "copy -p"])


if __name__ == "__main__":
    unittest.main()
