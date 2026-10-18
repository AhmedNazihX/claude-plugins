"""accio_lib.shellwords: shell commands split into simple commands, the way the shell reads them (S-013; reused by
curfew, S-015)."""
import unittest

import support  # noqa: F401  (puts bin/ on the path)

from accio_lib import shellwords


def words(command):
    return [list(segment.words) for segment in shellwords.segments(command) if segment.words]


class ShellwordsTest(unittest.TestCase):
    def test_operators_split_only_outside_quotes(self):
        self.assertEqual(words('a "x && y" && b; c | d'), [["a", "x && y"], ["b"], ["c"], ["d"]])
        self.assertEqual(words("echo '(' ; cd /"), [["echo", "("], ["cd", "/"]])

    def test_quotes_and_escapes_are_removed_and_empty_words_kept(self):
        self.assertEqual(words('git commit -m "" -n'), [["git", "commit", "-m", "", "-n"]])
        self.assertEqual(words(r'echo a\ b "c\"d" \'e'), [["echo", "a b", 'c"d', "'e"]])

    def test_redirects_and_their_targets_are_not_words(self):
        self.assertEqual(words("rm -rf build 2>/dev/null >>log &>all <in"), [["rm", "-rf", "build"]])
        self.assertEqual(words("git log -n 5 >out 2>&1"), [["git", "log", "-n", "5"]])

    def test_heredoc_bodies_are_data_unless_never_closed(self):
        self.assertEqual(words("cat <<'E' >f\nrm -rf /\nE\nls"), [["cat"], ["ls"]])
        self.assertEqual(words("cat <<-E\n\tbody\n\tE\nls"), [["cat"], ["ls"]])
        self.assertEqual(words("cat <<E\nls"), [["cat"], ["ls"]])
        self.assertEqual(words('echo "<<E"\nls'), [["echo", "<<E"], ["ls"]])

    def test_subshell_parentheses_are_operators(self):
        self.assertEqual([s.operator for s in shellwords.segments("(cd /x && ls)>out; y")], ["(", "&&", ")", ";", ""])

    def test_ansi_c_quotes_are_decoded_the_way_bash_decodes_them(self):
        # a guard must judge the word bash runs: $'\x72\x6d' is rm (security review, 2026-10-18)
        cases = {r"$'\x72\x6d' -rf $'\x2e\x2e'": ["rm", "-rf", ".."], r"$'\162\155'": ["rm"],
                 r"$'rm'": ["rm"], r"$'\U00000072m'": ["rm"], r"$'a\nb\tc'": ["a\nb\tc"],
                 r"$'\cA'": ["\x01"], r"$'\e[0m'": ["\x1b[0m"], r"$'\q'": ["\\q"], r"$'a\x00b' c": ["a", "c"],
                 r"$'\x7' $'\x4g'": ["\x07", "\x04g"], r"$'\'\"\\\?'": ["'\"\\?"],
                 r"$'\c?'": ["\x7f"], r"$'\c\\a'": ["\x1ca"], r"$'\UFFFFFFFF'": ["\\UFFFFFFFF"],
                 r"$'\uD800x'": ["\\uD800x"]}
        for command, expected in cases.items():
            with self.subTest(command):
                self.assertEqual(words(command), [expected])

    def test_ansi_c_quotes_end_at_an_unescaped_quote(self):
        self.assertEqual(words("echo $'it\\'s' ; ls"), [["echo", "it's"], ["ls"]])

    def test_arithmetic_is_one_word_and_starts_no_heredoc(self):
        self.assertEqual(words("echo $((1<<n))\nls\nn"), [["echo", "$((1<<n))"], ["ls"], ["n"]])

    def test_heredoc_bodies_and_here_strings_are_the_commands_input(self):
        segments = [s for s in shellwords.segments("bash <<'E'\nls\nE\ncat <<< hi") if s.words]
        self.assertEqual([(s.words, s.inputs) for s in segments], [(("bash",), ("ls",)), (("cat",), ("hi",))])

    def test_a_heredoc_ends_only_at_its_exact_line(self):
        self.assertEqual(words("cat <<E\n  E\nls\nE\npwd"), [["cat"], ["pwd"]])
        self.assertEqual(words("cat <<-E\n\tbody\n\tE\npwd"), [["cat"], ["pwd"]])

    def test_command_substitutions_are_listed(self):
        self.assertEqual(shellwords.substitutions('echo "$(git status)" `ls -a` "a $(echo (x))"'),
                         ("git status", "ls -a", "echo (x)"))

    def test_unbalanced_quotes_run_to_the_end(self):
        self.assertEqual(words('echo "open && git status'), [["echo", "open && git status"]])

    def test_comments_are_dropped(self):
        self.assertEqual(words("git status # rm -rf /\nls"), [["git", "status"], ["ls"]])


if __name__ == "__main__":
    unittest.main()
