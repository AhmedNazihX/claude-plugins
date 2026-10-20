"""S-045: accio-preview start and stop (a story's preview as a detached process)."""
import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

from support import ROOT, init_repo, write

from accio_lib import config, paths

PREVIEW = ROOT / "bin" / "accio-preview"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def port_is_open(port):
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def wait_until(check, seconds=10):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.1)
    return check()


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class PreviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = init_repo(pathlib.Path(self.tmp.name).resolve() / "repo")
        self.accio = self.root / ".accio"
        self.run_dir = self.accio / "run"
        self.run_dir.mkdir(parents=True)
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}/marker.txt"
        self.serve = f"python3 -m http.server {self.port} --bind 127.0.0.1"
        self.configure(f"sh -c '{self.serve} & wait'")
        for story_id in ("S-001", "S-002"):
            write(self.worktree(story_id) / "marker.txt", f"hello from {story_id}\n")
        self.started = []

    def tearDown(self):
        for story_id in ("S-001", "S-002"):
            self.preview(story_id, "stop")
        self.tmp.cleanup()

    def configure(self, command):
        write(self.accio / "config.json", json.dumps({"preview": {"command": command, "url": self.url}}))

    def worktree(self, story_id):
        return paths.worktree_root(self.root) / story_id

    def preview(self, story_id, action, *extra):
        return subprocess.run([sys.executable, str(PREVIEW), story_id, action, *extra], cwd=self.root,
                              capture_output=True, text=True, timeout=60)

    def state(self, story_id):
        return json.loads((self.run_dir / story_id / "preview.json").read_text(encoding="utf-8"))

    def test_S_045_1_start_runs_in_the_worktree_records_pid_and_waits_for_the_url(self):
        result = self.preview("S-001", "start", "--timeout", "20")
        self.assertEqual(result.returncode, 0, result.stderr)
        with urllib.request.urlopen(self.url, timeout=5) as response:
            self.assertEqual(response.read().decode(), "hello from S-001\n")
        state = self.state("S-001")
        self.assertTrue(alive(state["pid"]))
        self.assertEqual(state["url"], self.url)
        self.assertIn(self.url, result.stdout)

    def test_S_045_1_start_fails_when_the_url_never_answers(self):
        self.configure("sleep 60")
        result = self.preview("S-001", "start", "--timeout", "1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not answer", result.stderr)
        self.assertFalse((self.run_dir / "S-001" / "preview.json").exists())
        self.assertFalse((self.run_dir / "preview.lock").exists())

    def test_S_045_1_start_without_a_preview_config_says_so(self):
        write(self.accio / "config.json", "{}")
        result = self.preview("S-001", "start")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("preview", result.stderr)

    def test_S_045_1_config_checks_the_preview_shape(self):
        for bad in ({"command": "x"}, {"command": "x", "url": "ftp://a"}, "x", {"command": "", "url": "http://a"}):
            write(self.accio / "config.json", json.dumps({"preview": bad}))
            with self.assertRaises(config.ConfigError, msg=repr(bad)):
                config.load(self.accio)
        write(self.accio / "config.json", "{}")
        self.assertIsNone(config.load(self.accio)["preview"])

    def test_S_045_2_second_start_waits_on_the_lock_until_the_first_is_stopped(self):
        self.assertEqual(self.preview("S-001", "start", "--timeout", "20").returncode, 0)
        second = subprocess.Popen([sys.executable, str(PREVIEW), "S-002", "start", "--timeout", "20"],
                                  cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertTrue(wait_until(lambda: (self.run_dir / "preview.lock").exists()))
            time.sleep(1)
            self.assertIsNone(second.poll(), "the second start should still be waiting")
            self.assertEqual(self.preview("S-001", "stop").returncode, 0)
            out, err = second.communicate(timeout=30)
        finally:
            if second.poll() is None:
                second.kill()
        self.assertEqual(second.returncode, 0, err)
        with urllib.request.urlopen(self.url, timeout=5) as response:
            self.assertEqual(response.read().decode(), "hello from S-002\n")

    def test_S_045_2_second_start_gives_up_naming_the_lock(self):
        self.assertEqual(self.preview("S-001", "start", "--timeout", "20").returncode, 0)
        result = self.preview("S-002", "start", "--wait", "1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("preview.lock", result.stderr)

    def test_S_045_3_stop_kills_the_group_frees_the_port_and_removes_the_files(self):
        self.assertEqual(self.preview("S-001", "start", "--timeout", "20").returncode, 0)
        write(self.run_dir / "S-001" / "preview-login.json", "{}")
        pid = self.state("S-001")["pid"]
        result = self.preview("S-001", "stop")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(wait_until(lambda: not port_is_open(self.port)))
        self.assertTrue(wait_until(lambda: not alive(pid)))
        self.assertFalse((self.run_dir / "S-001" / "preview.json").exists())
        self.assertFalse((self.run_dir / "S-001" / "preview-login.json").exists())
        self.assertFalse((self.run_dir / "preview.lock").exists())

    def test_S_045_3_stop_with_nothing_running_is_fine(self):
        self.assertEqual(self.preview("S-001", "stop").returncode, 0)

    def test_S_045_4_stop_after_a_crashed_start_still_frees_the_port(self):
        listen = ("import socket,time;s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);"
                  f"s.bind(('127.0.0.1',{self.port}));s.listen(5);time.sleep(120)")
        self.configure(f'python3 -c "{listen}"')
        crashed = subprocess.Popen([sys.executable, str(PREVIEW), "S-001", "start", "--timeout", "60"],
                                   cwd=self.root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.assertTrue(wait_until(lambda: port_is_open(self.port)))
        crashed.kill()
        crashed.wait()
        self.assertTrue(port_is_open(self.port), "the preview outlives the crashed start")
        (self.run_dir / "S-001" / "preview.json").unlink(missing_ok=True)  # the crash may even lose the record
        self.assertEqual(self.preview("S-001", "stop").returncode, 0)
        self.assertTrue(wait_until(lambda: not port_is_open(self.port)))
        self.assertFalse((self.run_dir / "preview.lock").exists())


class PolicyTest(unittest.TestCase):
    def test_S_045_1_portkey_may_run_accio_preview(self):
        from accio_lib import policy
        self.assertEqual(policy.SCRIPTS["scripts"]["accio-preview"], frozenset({"start", "stop"}))


if __name__ == "__main__":
    unittest.main()
