"""S-063: fence, the PostToolUse hook that hides an off-origin page from mad-eye (DESIGN § 4.4; spike S-L5)."""
import copy
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from support import FIXTURES, ROOT, init_repo, write

FENCE = ROOT / "hooks" / "fence.py"
PREVIEW = "http://localhost:3000/"
AGENT = "a9549e371ba1e3b80"


class FenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = init_repo(pathlib.Path(self.tmp.name).resolve() / "app")
        self.run_dir = self.repo / ".accio" / "run"
        write(self.repo / ".accio" / "config.json", json.dumps({"preview": {"command": "x", "url": PREVIEW}}))
        self.fixture = json.loads((FIXTURES / "browser-click-offorigin.json").read_text(encoding="utf-8"))

    def tearDown(self):
        self.tmp.cleanup()

    def payload(self, url="http://evil.com/", **changes):
        data = copy.deepcopy(self.fixture)
        data["cwd"] = str(self.repo)
        text = data["tool_response"][0]["text"]
        if url is None:
            text = text.replace("- Page URL: http://localhost:8766/\n", "")
        else:
            text = text.replace("http://localhost:8766/", url)
        data["tool_response"][0]["text"] = text
        return {**data, **changes}

    def call(self, payload):
        return subprocess.run([sys.executable, "-I", str(FENCE)], input=json.dumps(payload), capture_output=True,
                              text=True, check=False)

    def fence(self):
        path = self.run_dir / "mad-eye-fence.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def test_S_063_1_off_origin_page_is_replaced_by_the_reason(self):
        result = self.call(self.payload())
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "PostToolUse")
        blocks = out["updatedMCPToolOutput"]
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["type"], "text")
        self.assertIn("http://evil.com/", blocks[0]["text"])
        self.assertIn("browser_navigate", blocks[0]["text"])
        self.assertIn(PREVIEW, blocks[0]["text"])
        self.assertNotIn("Page Title", blocks[0]["text"])

    def test_S_063_2_fence_record_keeps_other_agents(self):
        write(self.run_dir / "mad-eye-fence.json", json.dumps({"other": {"url": "http://x.org/"}}))
        self.call(self.payload())
        self.assertEqual(self.fence(), {"other": {"url": "http://x.org/"}, AGENT: {"url": "http://evil.com/"}})

    def test_S_063_3_log_line_goes_to_the_claimed_story(self):
        write(self.run_dir / "claims.json", json.dumps({AGENT: {"story": "S-009", "worktree": "/w"}}))
        self.call(self.payload())
        lines = (self.run_dir / "S-009" / "mad-eye-fence.log").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        _, agent, tool, url = lines[0].split(" ")
        self.assertEqual((agent, tool, url), (AGENT, self.fixture["tool_name"], "http://evil.com/"))
        self.assertRegex(lines[0], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\S* ")

    def test_S_063_4_log_line_without_a_claim_goes_to_the_run_folder(self):
        self.call(self.payload())
        self.call(self.payload())
        lines = (self.run_dir / "mad-eye-fence.log").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)

    def test_S_063_5_on_origin_page_returns_no_output(self):
        result = self.call(self.payload(url="http://localhost:3000/about"))
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertIsNone(self.fence())

    def test_S_063_6_on_origin_page_lifts_the_fence_for_that_agent(self):
        write(self.run_dir / "mad-eye-fence.json",
              json.dumps({AGENT: {"url": "http://evil.com/"}, "other": {"url": "http://x.org/"}}))
        result = self.call(self.payload(url="http://localhost:3000/"))
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.fence(), {"other": {"url": "http://x.org/"}})

    def test_S_063_7_other_agents_get_no_output(self):
        for agent in ("accio:house-elf", "general-purpose", None):
            result = self.call(self.payload(agent_type=agent))
            self.assertEqual((result.returncode, result.stdout), (0, ""), agent)
        self.assertIsNone(self.fence())

    def test_S_063_8_a_crash_adds_no_output(self):
        write(self.repo / ".accio" / "config.json", "{ not json")
        for raw in ("not json", json.dumps([1]), json.dumps({**self.payload(), "tool_response": 5})):
            result = subprocess.run([sys.executable, "-I", str(FENCE)], input=raw, capture_output=True, text=True,
                                    check=False)
            self.assertEqual((result.returncode, result.stdout), (0, ""), raw)
        result = self.call(self.payload())
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_S_063_9_no_page_url_changes_nothing(self):
        write(self.run_dir / "mad-eye-fence.json", json.dumps({AGENT: {"url": "http://evil.com/"}}))
        before = (self.run_dir / "mad-eye-fence.json").read_text(encoding="utf-8")
        result = self.call(self.payload(url=None))
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertEqual((self.run_dir / "mad-eye-fence.json").read_text(encoding="utf-8"), before)

    def test_S_063_10_hooks_json_lists_the_post_tool_use_hook(self):
        data = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        groups = data["hooks"]["PostToolUse"]
        self.assertEqual([g["matcher"] for g in groups], ["mcp__.*__browser_.*"])
        self.assertTrue(groups[0]["hooks"][0]["command"].endswith('/hooks/fence.py"'))
        self.assertNotIn("onFailure", groups[0]["hooks"][0])


if __name__ == "__main__":
    unittest.main()
