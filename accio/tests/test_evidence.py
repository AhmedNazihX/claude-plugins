"""S-068: `ui_evidence` in config, and `accio-preview <ID> evidence` (screenshots of a native app's real window)."""
import json
import pathlib
import tempfile
import unittest

from support import write

from accio_lib import config

GOOD = {"command": "app --ui-walk {steps} --out {folder}", "steps_doc": "docs/ui-walk.md", "takes_over_screen": False}


class EvidenceConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.accio = pathlib.Path(self.tmp.name).resolve() / ".accio"

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, data):
        write(self.accio / "config.json", json.dumps(data))
        return config.load(self.accio)

    def refused(self, data):
        with self.assertRaises(config.ConfigError) as caught:
            self.load(data)
        return str(caught.exception)

    def test_S_068_8_a_good_ui_evidence_loads_and_defaults_to_none(self):
        self.assertIsNone(self.load({})["ui_evidence"])
        settings = self.load({"ui_evidence": {**GOOD, "themes": ["light", "dark"], "timeout": 120}})["ui_evidence"]
        self.assertEqual(settings["command"], GOOD["command"])
        self.assertEqual(list(settings["themes"]), ["light", "dark"])

    def test_S_068_8_preview_and_ui_evidence_together_are_refused_with_set_one(self):
        preview = {"command": "npm start", "url": "http://localhost:3000", "test_data": True}
        message = self.refused({"preview": preview, "ui_evidence": GOOD})
        self.assertIn("set one", message)
        self.assertIn("preview", message)
        self.assertIn("ui_evidence", message)

    def test_S_068_8_a_missing_required_key_is_named(self):
        for key in ("command", "steps_doc", "takes_over_screen"):
            with self.subTest(key=key):
                data = {name: value for name, value in GOOD.items() if name != key}
                message = self.refused({"ui_evidence": data})
                self.assertIn("ui_evidence", message)
                self.assertIn(key, message)

    def test_S_068_8_a_command_without_steps_or_folder_is_named(self):
        for command, missing in (("app --out {folder}", "{steps}"), ("app {steps}", "{folder}"), ("", "{steps}")):
            with self.subTest(command=command):
                message = self.refused({"ui_evidence": {**GOOD, "command": command}})
                self.assertIn(missing, message)

    def test_S_068_8_bad_values_are_refused(self):
        bad = ({"takes_over_screen": "no"}, {"steps_doc": ""}, {"steps_doc": "/abs/ui-walk.md"},
               {"steps_doc": "../outside.md"}, {"themes": "dark"}, {"themes": ["light", ""]}, {"timeout": 0},
               {"timeout": True}, {"unknown": 1})
        for extra in bad:
            with self.subTest(extra=extra):
                self.assertIn("ui_evidence", self.refused({"ui_evidence": {**GOOD, **extra}}))
        self.assertIn("ui_evidence", self.refused({"ui_evidence": "app"}))


if __name__ == "__main__":
    unittest.main()
