"""accio_lib.shellpaths: where a shell word points, judged without running it (S-013; reused by curfew, S-015)."""
import os
import pathlib
import tempfile
import time
import unittest

from support import init_repo

from accio_lib import shellpaths


class ShellpathsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = init_repo(pathlib.Path(self.tmp.name).resolve() / "app")

    def tearDown(self):
        self.tmp.cleanup()

    def test_variables_the_command_sets_are_unknowable(self):
        names = shellpaths.assigned_names([("X=/",), ("for", "TMPDIR", "in", "/"), ("read", "-r", "LINE")])
        self.assertEqual(names, {"X", "TMPDIR", "LINE"})
        self.assertEqual(shellpaths.expand("$TMPDIR/x", "/", names), "$TMPDIR/x")
        self.assertEqual(shellpaths.expand("~/x", "/", frozenset({"HOME"})), "~/x")
        self.assertEqual(shellpaths.expand("$PWD/x", "/opt"), "/opt/x")

    def test_brace_lists_expand_and_anything_else_in_braces_is_unknowable(self):
        self.assertEqual(shellpaths.brace_alternatives("b/{a,c{1,2}}"), ("b/a", "b/c1", "b/c2"))
        self.assertIsNone(shellpaths.target_path("build/{1..3}", str(self.repo)))
        too_many = "{" + ",".join("abcdefghij") + "}{" + ",".join("abcdefghij") + "}"
        self.assertEqual(shellpaths.brace_alternatives(too_many), (too_many,))

    def test_a_brace_bomb_with_few_groups_is_refused_at_once(self):
        bomb = "{" + ",".join(f"o{n}" for n in range(20)) + "}"
        started = time.monotonic()
        self.assertEqual(shellpaths.brace_alternatives(bomb * 6), (bomb * 6,))
        self.assertLess(time.monotonic() - started, 1)

    def test_a_loop_variable_from_the_environment_is_not_trusted(self):
        names = shellpaths.assigned_names([("for", "TMPDIR", "in", "/")])
        self.assertFalse(shellpaths.deletable("$TMPDIR/usr", str(self.repo), self.repo, names))
        self.assertTrue(shellpaths.deletable("build", str(self.repo), self.repo))

    def test_cd_reads_options_and_the_directory_stack(self):
        root = self.repo
        self.assertEqual(shellpaths.cd("/", ("cd", "-P", "--", "/opt"), root), "/opt")
        self.assertEqual(shellpaths.cd("/", ("cd", '$(git rev-parse --show-toplevel)'), root), str(root))
        for argv in (("pushd",), ("pushd", "+1"), ("pushd", "-n", "/x"), ("cd", "-"), ("cd", "$NOPE_UNSET_X")):
            self.assertIsNone(shellpaths.cd("/", argv, root), argv)


if __name__ == "__main__":
    unittest.main()
