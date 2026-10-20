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

    def configure(self, command, **extra):
        settings = {"command": command, "url": self.url, "test_data": True, **extra}
        write(self.accio / "config.json", json.dumps({"preview": settings}))

    def worktree(self, story_id):
        return paths.worktree_root(self.root) / story_id

    def preview(self, story_id, action, *extra, env=None):
        return subprocess.run([sys.executable, str(PREVIEW), story_id, action, *extra], cwd=self.root,
                              capture_output=True, text=True, timeout=60, env={**os.environ, **(env or {})})

    def test_S_049_1_start_refuses_without_test_data_true(self):
        for extra in ({"test_data": False}, {"test_data": None}):
            self.configure(f"sh -c '{self.serve} & wait'", **extra)
            result = self.preview("S-001", "start", "--timeout", "2")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("test_data", result.stderr)
            self.assertFalse((self.run_dir / "S-001" / "preview.json").exists())
        settings = {"command": "x", "url": self.url}
        write(self.accio / "config.json", json.dumps({"preview": settings}))
        result = self.preview("S-001", "start", "--timeout", "2")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("test_data", result.stderr)

    def test_S_049_2_start_refuses_when_a_login_variable_is_unset(self):
        self.configure(f"sh -c '{self.serve} & wait'", login={"username_env": "A49_USER", "password_env": "A49_PASS"})
        result = self.preview("S-001", "start", "--timeout", "2", env={"A49_USER": "u"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("A49_PASS", result.stderr)
        self.assertFalse((self.run_dir / "S-001" / "preview-login.json").exists())
        self.assertFalse((self.run_dir / "preview.lock").exists())

    def test_S_049_3_start_writes_the_login_file_from_the_variables(self):
        self.configure(f"sh -c '{self.serve} & wait'", login={"username_env": "A49_USER", "password_env": "A49_PASS"})
        result = self.preview("S-001", "start", "--timeout", "20", env={"A49_USER": "tester", "A49_PASS": "s3cret"})
        self.assertEqual(result.returncode, 0, result.stderr)
        path = self.run_dir / "S-001" / "preview-login.json"
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"username": "tester", "password": "s3cret"})
        self.assertEqual(path.stat().st_mode & 0o077, 0)
        with (self.root / ".gitignore").open("a", encoding="utf-8") as handle:
            handle.write(".accio/run/\n")  # accio-design adds this line to a real repo
        ignored = subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=self.root, check=False)
        self.assertEqual(ignored.returncode, 0)
        self.preview("S-001", "stop")
        self.assertFalse(path.exists())

    def test_S_049_4_config_with_a_login_value_is_refused_and_writes_no_login_file(self):
        for login in ({"username": "bob", "password": "x"}, {"username_env": "A", "password": "x"},
                      {"username_env": "A"}, "bob"):
            self.configure(f"sh -c '{self.serve} & wait'", login=login)
            result = self.preview("S-001", "start", "--timeout", "2", env={"A": "1"})
            self.assertNotEqual(result.returncode, 0, repr(login))
            self.assertIn("login", result.stderr)
            self.assertFalse((self.run_dir / "S-001" / "preview-login.json").exists())
            self.assertFalse((self.run_dir / "S-001" / "preview.json").exists())

    def test_S_049_5_env_variables_reach_the_preview_process(self):
        self.configure(f"sh -c 'echo $A49_MODE > marker.txt; {self.serve} & wait'", env={"A49_MODE": "demo"})
        result = self.preview("S-001", "start", "--timeout", "20")
        self.assertEqual(result.returncode, 0, result.stderr)
        with urllib.request.urlopen(self.url, timeout=5) as response:
            self.assertEqual(response.read().decode(), "demo\n")

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

    def test_S_046_11_config_accepts_mcp_prefix_as_a_preview_key(self):
        settings = {"command": "x", "url": "http://a", "mcp_prefix": "mcp__pw__"}
        write(self.accio / "config.json", json.dumps({"preview": settings}))
        self.assertEqual(config.load(self.accio)["preview"]["mcp_prefix"], "mcp__pw__")
        for bad in (1, "", " "):
            write(self.accio / "config.json", json.dumps({"preview": {**settings, "mcp_prefix": bad}}))
            with self.assertRaises(config.ConfigError, msg=repr(bad)):
                config.load(self.accio)

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


    def test_S_051_1_stop_holds_the_lock_until_the_port_is_free_and_the_lock_removed(self):
        from unittest import mock
        from accio_lib import preview, runlock
        self.assertEqual(self.preview("S-001", "start", "--timeout", "20").returncode, 0)
        seen = {}
        real_free = preview._free_port

        def spy(url):
            held = json.loads((self.run_dir / "preview.lock").read_text(encoding="utf-8"))
            seen["lock_story"] = held["story"]
            seen["lock_alive"] = preview._alive(held["pid"])
            real_free(url)
            seen["port_open_after"] = port_is_open(self.port)

        killed = []
        real_kill = preview._kill_group

        def kill_spy(pgid):
            real_kill(pgid)
            held = json.loads((self.run_dir / "preview.lock").read_text(encoding="utf-8"))
            killed.append(preview._alive(held["pid"]))
            # the guard is held now: another start cannot take the lock between the kill and the clear
            with open(self.run_dir / runlock.GUARD_NAME, "a", encoding="utf-8") as handle:
                import fcntl
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

        with mock.patch.object(preview, "_free_port", spy), mock.patch.object(preview, "_kill_group", kill_spy):
            self.assertTrue(preview.stop(self.run_dir, "S-001", None))
        self.assertEqual(seen["lock_story"], "S-001")
        self.assertFalse(seen["port_open_after"])
        self.assertTrue(killed)
        self.assertFalse((self.run_dir / "preview.lock").exists())

    def test_S_051_2_stop_frees_no_port_while_another_story_holds_the_lock(self):
        listen = ("import socket,time;s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);"
                  f"s.bind(('127.0.0.1',{self.port}));s.listen(5);time.sleep(120)")
        other = subprocess.Popen([sys.executable, "-c", listen], start_new_session=True)
        try:
            self.assertTrue(wait_until(lambda: port_is_open(self.port)))
            write(self.run_dir / "preview.lock", json.dumps({"story": "S-002", "pid": other.pid}))
            write(self.run_dir / "S-001" / "preview.json", json.dumps({"story": "S-001", "url": self.url}))
            self.assertEqual(self.preview("S-001", "stop").returncode, 0)
            self.assertIsNone(other.poll(), "S-002's listener must survive S-001's stop")
            self.assertTrue(port_is_open(self.port))
            self.assertFalse((self.run_dir / "S-001" / "preview.json").exists())
            held = json.loads((self.run_dir / "preview.lock").read_text(encoding="utf-8"))
            self.assertEqual(held["story"], "S-002")
        finally:
            other.kill()
            other.wait()

    def test_S_051_3_two_story_hand_over_passes_twenty_times_in_a_row(self):
        for round_number in range(20):
            with self.subTest(round=round_number):
                self.test_S_045_2_second_start_waits_on_the_lock_until_the_first_is_stopped()
                self.preview("S-002", "stop")
                self.assertTrue(wait_until(lambda: not port_is_open(self.port)))


class PolicyTest(unittest.TestCase):
    def test_S_045_1_portkey_may_run_accio_preview(self):
        from accio_lib import policy
        self.assertEqual(policy.SCRIPTS["scripts"]["accio-preview"], frozenset({"start", "stop"}))


if __name__ == "__main__":
    unittest.main()
