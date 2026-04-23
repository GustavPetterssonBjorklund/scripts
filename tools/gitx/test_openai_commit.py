from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from openai_commit import (
    _sample_changed_lines,
    build_change_summary,
    build_commit_prompt,
    generate_commit_message,
    prepare_commit_diff,
    split_diff_by_file,
)


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
        self.assertIn("content changes: +1 / -1", prepared)
        self.assertIn("+new behavior", prepared)
        self.assertIn("-old behavior", prepared)
        self.assertNotIn("y" * 100, prepared)

    def test_truncated_manifest_reports_add_and_remove_counts(self):
        diff = (
            "diff --git a/tools/gitx/openai_commit.py b/tools/gitx/openai_commit.py\n"
            "index 3333333..4444444 100644\n"
            "--- a/tools/gitx/openai_commit.py\n"
            "+++ b/tools/gitx/openai_commit.py\n"
            "@@ -1,8 +1,6 @@\n"
            "-remove stale summary line\n"
            "-remove unused helper line\n"
            "-remove compatibility branch\n"
            "-remove fallback wording\n"
            "+keep short replacement\n"
            "+keep second replacement\n"
            "+keep concise note\n"
            "+keep final note\n"
        )

        prepared, truncated = prepare_commit_diff(diff, max_chars=320)

        self.assertTrue(truncated)
        self.assertIn("+4/-4 changed lines", prepared)
        self.assertIn("Diff excerpts by file:", prepared)

    def test_sampled_changed_lines_include_deletions_and_additions(self):
        diff = (
            "diff --git a/tools/gitx/openai_commit.py b/tools/gitx/openai_commit.py\n"
            "index 3333333..4444444 100644\n"
            "--- a/tools/gitx/openai_commit.py\n"
            "+++ b/tools/gitx/openai_commit.py\n"
            "@@ -1,8 +1,6 @@\n"
            "-remove stale summary line\n"
            "-remove unused helper line\n"
            "-remove compatibility branch\n"
            "-remove fallback wording\n"
            "+keep short replacement\n"
            "+keep second replacement\n"
            "+keep concise note\n"
            "+keep final note\n"
        )

        sampled = _sample_changed_lines(diff, max_chars=80)

        self.assertIn("-remove stale summary line", sampled)
        self.assertIn("+keep short replacement", sampled)

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

        self.assertIn("Structured change summary:", prompt)
        self.assertIn("Prefer the changed command, package, or top-level tool as scope", prompt)
        self.assertIn("never use an unstaged or merely suggested project name", prompt)
        self.assertIn("context leakage", prompt)
        self.assertIn("removed code, deleted files, and narrowed behavior", prompt)
        self.assertIn("prefer a refactor/chore style subject", prompt)

    def test_change_summary_calls_out_deleted_subsystem(self):
        diff = (
            "diff --git a/apps/agent/Cargo.toml b/apps/agent/Cargo.toml\n"
            "deleted file mode 100644\n"
            "index 1111111..0000000\n"
            "--- a/apps/agent/Cargo.toml\n"
            "+++ /dev/null\n"
            "@@ -1,2 +0,0 @@\n"
            "-[package]\n"
            "-name = \"agent\"\n"
            "diff --git a/apps/agent/src/main.rs b/apps/agent/src/main.rs\n"
            "deleted file mode 100644\n"
            "index 2222222..0000000\n"
            "--- a/apps/agent/src/main.rs\n"
            "+++ /dev/null\n"
            "@@ -1,2 +0,0 @@\n"
            "-fn main() {}\n"
            "-println!(\"agent\");\n"
            "diff --git a/apps/api/src/routes/nodes.ts b/apps/api/src/routes/nodes.ts\n"
            "index 3333333..4444444 100644\n"
            "--- a/apps/api/src/routes/nodes.ts\n"
            "+++ b/apps/api/src/routes/nodes.ts\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )

        summary = build_change_summary(split_diff_by_file(diff), truncated=True)

        self.assertIn("2 deleted", summary)
        self.assertIn("Dominant change: removal-heavy", summary)
        self.assertIn("Major removals: apps/agent (2 files)", summary)
        self.assertIn("Deleted paths: apps/agent/Cargo.toml, apps/agent/src/main.rs", summary)

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

    def test_request_uses_gpt_5_4_mini_by_default(self):
        captured_payload: dict[str, object] = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"output_text":"refactor(gitx): test"}'

        def fake_urlopen(request, timeout):
            self.assertEqual(timeout, 30)
            captured_payload.update(json.loads(request.data.decode("utf-8")))
            return FakeResponse()

        with patch("openai_commit.get_openai_api_key", return_value="test-key"):
            with patch("openai_commit.get_config_value", return_value=None):
                with patch("openai_commit.urllib.request.urlopen", side_effect=fake_urlopen):
                    response = generate_commit_message(
                        "diff --git a/tools/gitx/openai_commit.py b/tools/gitx/openai_commit.py\n"
                        "index 1111111..2222222 100644\n"
                        "--- a/tools/gitx/openai_commit.py\n"
                        "+++ b/tools/gitx/openai_commit.py\n"
                        "@@ -1 +1 @@\n"
                        "-old\n"
                        "+new\n"
                    )

        self.assertEqual("gpt-5.4-mini", captured_payload["model"])
        self.assertEqual("refactor(gitx): test", response.output_text if response else None)


if __name__ == "__main__":
    unittest.main()
