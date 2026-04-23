from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from openai_commit import build_commit_prompt, generate_commit_message, prepare_commit_diff


class PrepareCommitDiffTests(unittest.TestCase):
    def test_preserves_later_code_file_when_early_svg_is_large(self):
        svg_diff = (
            "diff --git a/assets/icon.svg b/assets/icon.svg\n"
            "index 1111111..2222222 100644\n"
            "--- a/assets/icon.svg\n"
            "+++ b/assets/icon.svg\n"
            "@@ -1 +1 @@\n"
            f"-{'x' * 5000}\n"
            f"+{'y' * 5000}\n"
        )
        code_diff = (
            "diff --git a/tools/gitx/openai_commit.py b/tools/gitx/openai_commit.py\n"
            "index 3333333..4444444 100644\n"
            "--- a/tools/gitx/openai_commit.py\n"
            "+++ b/tools/gitx/openai_commit.py\n"
            "@@ -1 +1 @@\n"
            "-old behavior\n"
            "+new behavior\n"
        )

        prepared, truncated = prepare_commit_diff(svg_diff + code_diff, max_chars=1200)

        self.assertTrue(truncated)
        self.assertIn("assets/icon.svg", prepared)
        self.assertIn("tools/gitx/openai_commit.py", prepared)
        self.assertIn("Scope candidates from staged paths, strongest first:\n- gitx", prepared)
        self.assertIn("+new behavior", prepared)
        self.assertNotIn("y" * 100, prepared)

    def test_uses_original_diff_when_within_limit(self):
        diff = (
            "diff --git a/tools/gitx/gitx.py b/tools/gitx/gitx.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/tools/gitx/gitx.py\n"
            "+++ b/tools/gitx/gitx.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )

        prepared, truncated = prepare_commit_diff(diff, max_chars=len(diff))

        self.assertFalse(truncated)
        self.assertEqual(diff, prepared)

    def test_prompt_prefers_tool_scope_and_mentions_scope_leakage(self):
        prompt = build_commit_prompt("diff --git a/tools/gitx/openai_commit.py b/tools/gitx/openai_commit.py", True)

        self.assertIn("Prefer the changed command, package, or top-level tool as scope", prompt)
        self.assertIn("never use an unstaged or merely suggested project name", prompt)
        self.assertIn("context leakage", prompt)

    def test_generate_commit_message_reports_progress(self):
        diff = (
            "diff --git a/tools/gitx/openai_commit.py b/tools/gitx/openai_commit.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/tools/gitx/openai_commit.py\n"
            "+++ b/tools/gitx/openai_commit.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        messages: list[str] = []

        with patch("openai_commit.request_openai_text", return_value="fix(gitx): test"):
            response = generate_commit_message(diff, messages.append)

        self.assertEqual("fix(gitx): test", response.output_text if response else None)
        self.assertIn("Reading AI commit configuration...", messages)
        self.assertIn("Analyzing 1 staged files for relevant context...", messages)
        self.assertIn("Building commit-message prompt...", messages)
        self.assertIn("Waiting for OpenAI to generate the commit message...", messages)
        self.assertIn("Received AI commit message.", messages)


if __name__ == "__main__":
    unittest.main()
