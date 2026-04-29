from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tui import (
    bump_version_tag,
    parse_tag_approval,
    _clamp_scroll,
    _action_label,
    _merge_context_width,
    _next_hunk_scroll,
    _previous_hunk_scroll,
    _review_visible_rows,
    _wrap_ai_merge_diff,
    _wrap_merge_context,
)


class TuiTagTests(unittest.TestCase):
    def test_bump_version_tag_preserves_prefix(self):
        self.assertEqual("v2.0.0", bump_version_tag("v1.2.3", "major"))
        self.assertEqual("v1.3.0", bump_version_tag("v1.2.3", "minor"))
        self.assertEqual("v1.2.4", bump_version_tag("v1.2.3", "patch"))

    def test_parse_tag_approval_reads_tag_and_message(self):
        approval = parse_tag_approval("Tag: v1.3.0\n\nMessage:\nRelease v1.3.0\n- Add tagging\n")

        self.assertIsNotNone(approval)
        self.assertEqual("v1.3.0", approval.tag)
        self.assertIn("Add tagging", approval.message)

    def test_wrap_merge_context_marks_current_and_incoming_blocks(self):
        lines = _wrap_merge_context(
            "\n".join([
                "Git options:",
                "- Current: keep our side",
                "- Incoming: keep their side",
                "",
                "Current / ours:",
                "  local change",
                "",
                "Incoming / theirs:",
                "  branch change",
            ]),
            80,
        )

        self.assertIn(("Git options:", "heading"), lines)
        self.assertIn(("- Current: keep our side", "current"), lines)
        self.assertIn(("  local change", "current"), lines)
        self.assertIn(("- Incoming: keep their side", "incoming"), lines)
        self.assertIn(("  branch change", "incoming"), lines)

    def test_merge_context_width_is_capped_at_80_columns(self):
        self.assertEqual(80, _merge_context_width(200))
        self.assertEqual(34, _merge_context_width(40))

    def test_clamp_scroll_bounds_to_visible_range(self):
        self.assertEqual(0, _clamp_scroll(-10, total_lines=20, visible_rows=5))
        self.assertEqual(15, _clamp_scroll(99, total_lines=20, visible_rows=5))
        self.assertEqual(0, _clamp_scroll(3, total_lines=4, visible_rows=5))

    def test_review_visible_rows_reserves_header_and_actions(self):
        self.assertEqual(12, _review_visible_rows(24))
        self.assertEqual(0, _review_visible_rows(10))

    def test_action_label_shows_shortcut_without_extra_separator(self):
        self.assertEqual(" o:Ours ", _action_label("Ours"))
        self.assertEqual(" i:AI ", _action_label("AI"))

    def test_wrap_ai_merge_diff_marks_original_and_ai_lines(self):
        lines = _wrap_ai_merge_diff("alpha\nold\nomega\n", "alpha\nnew\nomega\n", 80)

        self.assertIn(("--- original", "removed-heading"), lines)
        self.assertIn(("+++ ai proposal", "added-heading"), lines)
        self.assertIn(("-old", "removed"), lines)
        self.assertIn(("+new", "added"), lines)
        self.assertTrue(any(style == "hunk" for _line, style in lines))

    def test_hunk_navigation_wraps_between_hunks(self):
        hunks = [2, 10, 30]

        self.assertEqual(10, _next_hunk_scroll(hunks, current=2, visible_rows=5, total_lines=40))
        self.assertEqual(2, _next_hunk_scroll(hunks, current=30, visible_rows=5, total_lines=40))
        self.assertEqual(10, _previous_hunk_scroll(hunks, current=30, visible_rows=5, total_lines=40))
        self.assertEqual(30, _previous_hunk_scroll(hunks, current=2, visible_rows=5, total_lines=40))


if __name__ == "__main__":
    unittest.main()
