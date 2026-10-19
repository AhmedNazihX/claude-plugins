"""Tests for run_tests.py, the runner that runs each test file in its own process (S-017)."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
RUNNER = TESTS_DIR / "run_tests.py"

PASSING = "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n"
FAILING = "import unittest\nclass T(unittest.TestCase):\n    def test_bad(self):\n        self.fail('boom-marker')\n"


def rendezvous(mine, theirs):
    return (
        "import os, time, unittest\n"
        "class T(unittest.TestCase):\n"
        "    def test_meet(self):\n"
        f"        open({mine!r}, 'w').close()\n"
        "        end = time.time() + 10\n"
        f"        while time.time() < end and not os.path.exists({theirs!r}):\n"
        "            time.sleep(0.05)\n"
        f"        self.assertTrue(os.path.exists({theirs!r}))\n"
    )


class TestRunner(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        # The runner finds its own folder, so each case gets its own copy of it.
        self.runner = self.dir / "run_tests.py"
        shutil.copy(RUNNER, self.runner)

    def add(self, name, body):
        (self.dir / name).write_text(body)

    def run_runner(self, *args, cwd=None):
        return subprocess.run(
            [sys.executable, str(self.runner), *args],
            cwd=cwd or self.dir, capture_output=True, text=True, timeout=60,
        )

    def test_S_017_1_all_pass(self):
        self.add("test_a.py", PASSING)
        self.add("test_b.py", PASSING)
        r = self.run_runner()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"passed\s+test_a")
        self.assertRegex(r.stdout, r"passed\s+test_b")
        self.assertIn("2 files", r.stdout.splitlines()[-1])

    def test_S_017_2_failure_reported_and_others_run(self):
        self.add("test_a.py", PASSING)
        self.add("test_bad.py", FAILING)
        self.add("test_c.py", PASSING)
        r = self.run_runner()
        self.assertNotEqual(r.returncode, 0)
        self.assertRegex(r.stdout, r"FAILED\s+test_bad")
        self.assertRegex(r.stdout, r"passed\s+test_a")
        self.assertRegex(r.stdout, r"passed\s+test_c")
        self.assertIn("boom-marker", r.stdout)

    def test_S_017_3_no_test_files(self):
        r = self.run_runner()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no test file", (r.stdout + r.stderr).lower())

    def test_S_017_4_jobs_runs_files_side_by_side(self):
        a, b = self.dir / "a.marker", self.dir / "b.marker"
        self.add("test_a.py", rendezvous(str(a), str(b)))
        self.add("test_b.py", rendezvous(str(b), str(a)))
        r = self.run_runner("--jobs", "2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_S_017_5_runs_from_another_folder(self):
        self.add("test_cwd.py", (
            "import os, unittest\nfrom pathlib import Path\n"
            "class T(unittest.TestCase):\n"
            "    def test_cwd(self):\n"
            f"        self.assertEqual(Path(os.getcwd()).resolve(), Path({str(self.dir)!r}).resolve())\n"
        ))
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other, True)
        r = self.run_runner(cwd=other)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"passed\s+test_cwd")

    def test_S_017_6_discover_does_not_load_runner(self):
        loaded = unittest.TestLoader().discover(str(TESTS_DIR), pattern="test*.py")

        def modules(suite):
            for item in suite:
                if isinstance(item, unittest.TestSuite):
                    yield from modules(item)
                else:
                    yield type(item).__module__

        self.assertNotIn("run_tests", set(modules(loaded)))


if __name__ == "__main__":
    unittest.main()
