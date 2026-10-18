"""S-021/S-022: changing accio's committed files in place (frontmatter values and sections)."""
import pathlib
import tempfile
import unittest

from support import write

from accio_lib import story, storyfiles

TEXT = "---\nid: S-001\ntitle: x\ntrack: story\nstatus: review  # after the build\n---\n## Context\nWhy.\n" \
       "## Definition of Done\n- [ ] S-001/1 WHEN x THE SYSTEM SHALL y\n## Review notes\n- old note\n" \
       "## Blocked question\n"


class StoryFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tmp.name) / "S-001.md"
        write(self.path, TEXT)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_missing_key_is_added_before_the_closing_marker(self):
        text = storyfiles.with_fields(self.path, {"status": "dropped", "dropped": "not needed"})
        self.assertIn("status: dropped  # after the build\ndropped: not needed\n---\n", text)
        write(self.path, text)
        self.assertEqual(story.parse(self.path).meta["dropped"], "not needed")

    def test_a_section_is_appended_to_or_replaced_and_the_rest_kept(self):
        appended = storyfiles.with_section(TEXT, "Review notes", "- new note", append=True)
        self.assertIn("## Review notes\n- old note\n- new note\n## Blocked question\n", appended)
        replaced = storyfiles.with_section(TEXT, "Review notes", "- only note")
        self.assertIn("## Review notes\n- only note\n## Blocked question\n", replaced)
        self.assertTrue(replaced.startswith(TEXT.split("## Review notes")[0]))

    def test_appending_keeps_the_blank_lines_between_earlier_notes(self):
        text = TEXT.replace("- old note\n", "First paragraph.\n\nSecond paragraph.\n\n")
        appended = storyfiles.with_section(text, "Review notes", "- new note", append=True)
        self.assertIn("First paragraph.\n\nSecond paragraph.\n- new note\n## Blocked question", appended)

    def test_a_missing_section_goes_at_the_end_and_crlf_files_stay_crlf(self):
        crlf = TEXT.replace("\n", "\r\n")
        text = storyfiles.with_section(crlf.replace("## Blocked question\r\n", ""), "Blocked question", "Why?")
        self.assertTrue(text.endswith("## Blocked question\r\nWhy?\r\n"))
        self.assertNotIn("\n", text.replace("\r\n", ""))

    def test_a_section_at_the_end_with_no_body_takes_one(self):
        text = storyfiles.with_section(TEXT, "Blocked question", "Email or SMS?\n\nAnswer: Email")
        self.assertTrue(text.endswith("## Blocked question\nEmail or SMS?\n\nAnswer: Email\n"))


if __name__ == "__main__":
    unittest.main()
