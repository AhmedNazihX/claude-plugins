"""curfew lets prefect run `accio-break <ID> verify`, the one form brew.js gives it (S-043), and nothing else.

Found 2026-10-24 building S-075: prefect's script list had no `accio-break`, so every break boggart kept in a real
build ended as "boggart's verify gave no answer" and never reached a fix round.
"""
import shlex

from support import ROOT

from test_curfew import CurfewTestBase

PREFECT = "accio:prefect"
SCRIPT = shlex.quote(str(ROOT / "bin" / "accio-break"))


class PrefectBreakVerifyTest(CurfewTestBase):
    def run_as_prefect(self, command):
        return self.decision("Bash", self.bash(command), agent=PREFECT)

    def test_prefect_runs_accio_break_verify(self):
        for program in ("accio-break", SCRIPT):
            for sid in ("S-001", "S-075"):
                with self.subTest(program=program, sid=sid):
                    self.assertEqual(self.run_as_prefect(f"{program} {sid} verify")[0], "allow")

    def test_any_other_form_is_denied(self):
        denied = ("S-001", "S-001 try x.py", "S-001 verify --all", "S-001 VERIFY", "verify S-001", "S-01 verify",
                  "s-001 verify", "S-001x verify", "../S-001 verify", "S-001 verify $X", "S-001 {verify,try}")
        for args in denied:
            with self.subTest(args=args):
                self.assertEqual(self.run_as_prefect(f"{SCRIPT} {args}")[0], "deny")
        self.assertEqual(self.run_as_prefect("/tmp/accio-break S-001 verify")[0], "deny")

    def test_chained_with_another_command_is_denied(self):
        for command in (f"{SCRIPT} S-001 verify && ls", f"ls; {SCRIPT} S-001 verify", f"{SCRIPT} S-001 verify | cat",
                        f"{SCRIPT} S-001 verify > out.txt", f"X=1 {SCRIPT} S-001 verify",
                        f"cd {shlex.quote(str(self.worktree))} && {SCRIPT} S-001 verify"):
            with self.subTest(command=command):
                self.assertEqual(self.run_as_prefect(command)[0], "deny")
