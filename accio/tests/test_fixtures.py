"""S-059: the recorded PostToolUse payload of a real mad-eye click that left the preview (spike S-L5,
docs/research/spike-s-l5.md). The fence hook's tests (S-063) build on it.
"""
import json
import unittest

from support import FIXTURES

CLICK = FIXTURES / "browser-click-offorigin.json"


class BrowserClickFixtureTest(unittest.TestCase):
    def test_S_059_1_click_fixture_holds_the_post_tool_use_keys(self):
        payload = json.loads(CLICK.read_text())
        for key in ("tool_name", "agent_type", "agent_id", "tool_response"):
            self.assertIn(key, payload)
        self.assertEqual(payload["hook_event_name"], "PostToolUse")
        self.assertEqual(payload["agent_type"], "accio:mad-eye")
        self.assertTrue(payload["tool_name"].endswith("__browser_click"))


if __name__ == "__main__":
    unittest.main()
