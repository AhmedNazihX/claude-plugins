"""S-070: curfew lets prefect run `accio-preview` (the exact forms brew.js gives it) and write ui-steps.txt.

brew.js has prefect start and stop a web preview, read `ui_evidence` and make the evidence (S-047, S-068). These tests
send the commands and writes brew.js asks for through the real hook, and check look-alikes are denied.
"""
import shlex

from support import ROOT

from accio_lib import policy
from test_curfew import CurfewTestBase

PREFECT = "accio:prefect"
HEAD = "0123456789abcdef0123456789abcdef01234567"
SUM = "89abcdef"
SCRIPT = shlex.quote(str(ROOT / "bin" / "accio-preview"))
BREW_FORMS = ("S-001 start", "S-001 stop", "S-001 evidence-plan", f"S-001 evidence --head {HEAD} --steps-sum {SUM}")


class PrefectPreviewTest(CurfewTestBase):
    def run_as_prefect(self, command):
        return self.decision("Bash", self.bash(command), agent=PREFECT)

    def test_S_070_1_prefect_runs_each_accio_preview_form_brew_gives_it(self):
        for args in (*BREW_FORMS, f"S-012 evidence --head {HEAD[:7]} --steps-sum {SUM}"):
            for program in ("accio-preview", SCRIPT):
                with self.subTest(program=program, args=args):
                    self.assertEqual(self.run_as_prefect(f"{program} {args}")[0], "allow")

    def test_S_070_2_any_other_action_story_id_head_or_extra_argument_is_denied(self):
        denied = ("S-001", "S-001 restart", "S-001 start --wait 1", "S-001 stop now", "S-001 evidence",
                  f"S-001 evidence --head {HEAD}", f"S-001 evidence --steps-sum {SUM} --head {HEAD}",
                  f"S-001 evidence --head {HEAD.upper()} --steps-sum {SUM}",
                  f"S-001 evidence --head {HEAD}0 --steps-sum {SUM}", f"S-001 evidence --head abc --steps-sum {SUM}",
                  f"S-001 evidence --head {HEAD} --steps-sum {SUM}0", f"S-001 evidence --head {HEAD} --steps-sum xyz",
                  f"S-001 evidence --head {HEAD} --steps-sum {SUM} --timeout 1", "S-01 start", "s-001 start",
                  "S-001x start", "../S-001 start", "S-001 START", "start S-001", "S-001 evidence-plan --head x",
                  "S-001 start $X", "S-001 {start,stop}")
        for args in denied:
            with self.subTest(args=args):
                verdict, reason = self.run_as_prefect(f"{SCRIPT} {args}")
                self.assertEqual(verdict, "deny")
                self.assertIn("prefect", reason)
        self.assertEqual(self.run_as_prefect("/tmp/accio-preview S-001 start")[0], "deny")

    def test_S_070_2_accio_preview_chained_with_another_command_is_denied(self):
        worktree = shlex.quote(str(self.worktree))
        for command in (f"{SCRIPT} S-001 start && ls", f"ls; {SCRIPT} S-001 stop", f"{SCRIPT} S-001 start || true",
                        f"{SCRIPT} S-001 evidence-plan | cat", f"cd {worktree} && {SCRIPT} S-001 start",
                        f"{SCRIPT} S-001 start\nls", f"{SCRIPT} S-001 start && {SCRIPT} S-001 stop"):
            with self.subTest(command=command):
                verdict, reason = self.run_as_prefect(command)
                self.assertEqual(verdict, "deny")
                self.assertIn("on its own", reason)
        for command in (f"{SCRIPT} S-001 start &", f"X=1 {SCRIPT} S-001 start", f"{SCRIPT} S-001 start > out.txt"):
            with self.subTest(command=command):
                self.assertEqual(self.run_as_prefect(command)[0], "deny")

    def test_S_070_2_prefects_other_commands_still_chain_as_before(self):
        self.assert_allowed("Bash", self.in_worktree("python3 -m unittest"), agent=PREFECT)
        self.assert_allowed("Bash", self.in_worktree(f"{shlex.quote(str(ROOT / 'bin' / 'accio-check'))} S-001"),
                            agent=PREFECT)

    def test_S_070_2_portkey_no_longer_runs_accio_preview_since_brew_never_asks_it_to(self):
        self.assertNotIn("accio-preview", policy.SCRIPTS["scripts"])
        for args in ("S-001 start", "S-001 stop"):
            with self.subTest(args=args):
                self.assert_denied("Bash", self.bash(f"{SCRIPT} {args}"), "portkey", agent="accio:portkey")
        self.assert_denied("Bash", self.bash(f"{SCRIPT} S-001 start"), "headmaster", agent="accio:headmaster")

    def test_S_070_3_prefect_writes_a_storys_ui_steps_file(self):
        for story_id in ("S-001", "S-123"):
            with self.subTest(story_id=story_id):
                self.assert_allowed("Write", {"file_path": str(self.run_dir / story_id / "ui-steps.txt"),
                                              "content": "open main\n"}, agent=PREFECT)
        self.assert_allowed("Write", {"file_path": str(self.run_dir / "questions" / "S-001.md"), "content": "x"},
                            agent=PREFECT)

    def test_S_070_3_prefect_still_may_not_write_anywhere_else(self):
        accio = self.repo / ".accio"
        for target in (self.run_dir / "S-001" / "ui-steps.md", self.run_dir / "S-001" / "ui-steps.txt.bak",
                       self.run_dir / "S-001" / "sub" / "ui-steps.txt", self.run_dir / "ui-steps.txt",
                       self.run_dir / "wand" / "ui-steps.txt", self.run_dir / "S-x" / "ui-steps.txt",
                       self.run_dir / "S-001" / "build-report.md", self.run_dir / "S-001" / "ui-evidence.head",
                       self.run_dir / "push-ok", accio / "config.json", self.worktree / ".accio" / "run" / "S-001" /
                       "ui-steps.txt", self.worktree / "a.py", self.repo / "ui-steps.txt"):
            with self.subTest(target=target):
                self.assert_denied("Write", {"file_path": str(target), "content": "x"}, "prefect", agent=PREFECT)
