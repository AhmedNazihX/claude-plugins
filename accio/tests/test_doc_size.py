"""S-028: doc-size, the PreToolUse Read guard for long Markdown files, and the `librarian` agent (DESIGN § 4.2,
§ 4.4; analysis.md § 3.1). A block is exit 2 with the reason on stderr; a pass is exit 0 and silent.
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, init_repo, write

DOC_SIZE = ROOT / "hooks" / "doc_size.py"
HOOKS_JSON = ROOT / "hooks" / "hooks.json"
LIBRARIAN = ROOT / "agents" / "librarian.md"
LIMIT_BYTES = 40 * 1024


class DocSizeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = init_repo(pathlib.Path(self.tmp.name).resolve() / "app")
        (self.repo / ".accio").mkdir()
        self.big = self.repo / "docs" / "DESIGN.md"
        write(self.big, "x" * (LIMIT_BYTES + 1))

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, path, cwd=None, **extra):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Read",
                   "tool_input": {"file_path": str(path), **extra}, "cwd": str(cwd or self.repo)}
        return subprocess.run([sys.executable, "-I", str(DOC_SIZE)], input=json.dumps(payload), capture_output=True,
                              text=True, check=False)

    def assert_allowed(self, path, **kwargs):
        result = self.read(path, **kwargs)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""), path)

    def test_S_028_1_a_whole_read_of_a_long_markdown_file_is_blocked(self):
        for path in (self.big, self.repo / "NOTES.MD"):
            write(path, "x" * (LIMIT_BYTES + 1))
            with self.subTest(path.name):
                result = self.read(path)
                self.assertEqual(result.returncode, 2)
                for word in ("librarian", "offset", "limit", path.name):
                    self.assertIn(word, result.stderr)

    def test_S_028_1_a_read_that_still_loads_the_whole_file_is_blocked(self):
        for extra in ({"offset": 100}, {"offset": 1, "limit": 2000}, {"limit": 0}, {"limit": "50"},
                      {"limit": True}):
            with self.subTest(extra):
                self.assertEqual(self.read(self.big, **extra).returncode, 2)
        for name in ("GUIDE.markdown", "page.mdx"):
            write(self.repo / name, "x" * (LIMIT_BYTES + 1))
            self.assertEqual(self.read(self.repo / name).returncode, 2, name)
        self.assertIn("41 KB", self.read(self.big).stderr)

    def test_S_028_2_a_read_by_section_or_of_a_short_file_passes(self):
        self.assert_allowed(self.big, limit=200)
        self.assert_allowed(self.big, offset=900, limit=400)
        small = self.repo / "README.md"
        write(small, "x" * LIMIT_BYTES)
        self.assert_allowed(small)
        code = self.repo / "big.py"
        write(code, "x" * (LIMIT_BYTES + 1))
        self.assert_allowed(code)
        self.assert_allowed(self.repo / "missing.md")

    def test_S_028_2_the_repo_is_found_from_the_file_when_cwd_is_elsewhere(self):
        plain = init_repo(pathlib.Path(self.tmp.name).resolve() / "plain")
        self.assertEqual(self.read(self.big, cwd=plain).returncode, 2)

    def test_S_028_3_a_repo_without_accio_is_left_alone(self):
        plain = init_repo(pathlib.Path(self.tmp.name).resolve() / "plain")
        big = plain / "DESIGN.md"
        write(big, "x" * (LIMIT_BYTES + 1))
        self.assert_allowed(big, cwd=plain)

    def test_bad_payloads_pass_silently(self):
        for raw in ("not json", json.dumps({"tool_name": "Read", "tool_input": "x"}),
                    json.dumps({"tool_name": "Read", "tool_input": {"file_path": 5}, "cwd": str(self.repo)})):
            result = subprocess.run([sys.executable, "-I", str(DOC_SIZE)], input=raw, capture_output=True, text=True,
                                    check=False)
            self.assertEqual((result.returncode, result.stderr), (0, ""), raw)

    def test_hooks_json_runs_doc_size_on_read(self):
        config = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
        entries = [entry for entry in config if "doc_size.py" in json.dumps(entry)]
        self.assertEqual([entry["matcher"] for entry in entries], ["Read"])

    def test_S_028_4_librarian_is_haiku_with_read_and_grep_only(self):
        text = LIBRARIAN.read_text(encoding="utf-8")
        front = text.split("\n---\n", 1)[0].removeprefix("---\n")
        fields = dict(line.split(":", 1) for line in front.strip().splitlines())
        self.assertEqual(fields["name"].strip(), "librarian")
        self.assertEqual(fields["model"].strip(), "haiku")
        self.assertEqual({tool.strip() for tool in fields["tools"].split(",")}, {"Read", "Grep"})
        self.assertIn("file:line", text)


if __name__ == "__main__":
    unittest.main()
