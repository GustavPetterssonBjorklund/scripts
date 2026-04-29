from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from openai_tag import build_tag_prompt, generate_tag_suggestion, parse_tag_suggestion


class OpenAITagTests(unittest.TestCase):
    def test_parse_tag_suggestion_accepts_json(self):
        suggestion = parse_tag_suggestion(
            '{"tag":"v1.3.0","bump":"minor","message":"Release v1.3.0\\n- Add tagging"}'
        )

        self.assertIsNotNone(suggestion)
        self.assertEqual("v1.3.0", suggestion.tag)
        self.assertEqual("minor", suggestion.bump)
        self.assertIn("Add tagging", suggestion.message)

    def test_parse_tag_suggestion_rejects_invalid_bump(self):
        suggestion = parse_tag_suggestion('{"tag":"v1.3.0","bump":"huge","message":"Release"}')

        self.assertIsNone(suggestion)

    def test_prompt_includes_previous_tags_and_commits(self):
        prompt = build_tag_prompt("v1.2.3 previous", "v1.2.3", "abc123 feat: add tagging")

        self.assertIn("Latest tag:\nv1.2.3", prompt)
        self.assertIn("Recent tags:\nv1.2.3 previous", prompt)
        self.assertIn("abc123 feat: add tagging", prompt)
        self.assertIn("Return only JSON", prompt)

    def test_generate_tag_suggestion_reports_progress(self):
        messages: list[str] = []

        with patch(
            "openai_tag.request_openai_text",
            return_value='{"tag":"v1.3.0","bump":"minor","message":"Release v1.3.0"}',
        ):
            suggestion = generate_tag_suggestion(
                previous_tags="v1.2.3 previous",
                latest_tag="v1.2.3",
                recent_commits="abc123 feat: add tagging",
                progress=messages.append,
            )

        self.assertEqual("v1.3.0", suggestion.tag if suggestion else None)
        self.assertIn("Building tag suggestion prompt...", messages)
        self.assertIn("Waiting for OpenAI to suggest a tag...", messages)
        self.assertIn("Received AI tag suggestion.", messages)


if __name__ == "__main__":
    unittest.main()
