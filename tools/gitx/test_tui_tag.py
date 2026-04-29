from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tui import bump_version_tag, parse_tag_approval


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


if __name__ == "__main__":
    unittest.main()
