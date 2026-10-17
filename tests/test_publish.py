"""S-002/3: scripts/publish.py copies the plugin into the release marketplace."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PUBLISH = ROOT / "scripts" / "publish.py"


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def commit_all(cwd):
    git(cwd, "add", "-A")
    git(cwd, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "snapshot")


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class PublishTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.tmp.name)
        self.source = base / "source"
        self.dest = base / "release"
        write(self.source / ".claude-plugin" / "plugin.json",
              json.dumps({"name": "accio", "version": "0.1.0", "description": "Test accio."}))
        write(self.source / "skills" / "map" / "SKILL.md", "map skill\n")
        write(self.source / "bin" / "accio_lib" / "__init__.py", "")
        write(self.source / "README.md", "readme\n")
        write(self.source / "tests" / "test_x.py", "not shipped\n")
        write(self.source / "docs" / "DESIGN.md", "not shipped\n")
        write(self.source / ".gitignore", ".env\n")
        git(self.source, "init", "-q", "-b", "main")
        commit_all(self.source)
        write(self.dest / ".claude-plugin" / "marketplace.json", json.dumps({"name": "nazihx", "plugins": [
            {"name": "other", "source": "./other", "description": "Idea → design"}]}, indent=2, ensure_ascii=False))
        git(self.dest, "init", "-q", "-b", "main")
        commit_all(self.dest)

    def tearDown(self):
        self.tmp.cleanup()

    def publish(self):
        return subprocess.run(
            [sys.executable, "-I", str(PUBLISH), "--source", str(self.source), "--dest", str(self.dest)],
            capture_output=True, text=True, check=False,
        )

    def marketplace(self):
        return json.loads((self.dest / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))

    def test_S_002_3_copies_only_the_plugin_parts(self):
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        target = self.dest / "accio"
        self.assertTrue((target / ".claude-plugin" / "plugin.json").is_file())
        self.assertTrue((target / "skills" / "map" / "SKILL.md").is_file())
        self.assertTrue((target / "README.md").is_file())
        self.assertFalse((target / "tests").exists())
        self.assertFalse((target / "docs").exists())

    def test_S_002_3_removes_files_left_from_an_earlier_publish(self):
        write(self.dest / "accio" / "skills" / "old" / "SKILL.md", "stale\n")
        commit_all(self.dest)
        self.assertEqual(self.publish().returncode, 0)
        self.assertFalse((self.dest / "accio" / "skills" / "old").exists())

    def test_S_002_3_registers_accio_once_and_keeps_other_plugins(self):
        self.assertEqual(self.publish().returncode, 0)
        commit_all(self.dest)
        self.assertEqual(self.publish().returncode, 0)
        plugins = self.marketplace()["plugins"]
        self.assertEqual([p["name"] for p in plugins], ["other", "accio"])
        self.assertEqual(plugins[1], {"name": "accio", "source": "./accio", "description": "Test accio."})

    def test_S_002_3_refuses_when_the_working_tree_is_dirty(self):
        write(self.source / "skills" / "map" / "SKILL.md", "uncommitted change\n")
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("uncommitted", result.stderr)
        self.assertFalse((self.dest / "accio").exists())

    def test_refuses_a_destination_that_is_not_a_marketplace(self):
        (self.dest / ".claude-plugin" / "marketplace.json").unlink()
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("marketplace.json", result.stderr)
        self.assertFalse((self.dest / "accio").exists())

    def assert_refused(self, result, reason):
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(reason, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse((self.dest / "accio").exists())

    def test_S_002_3_never_ships_files_git_ignores(self):
        write(self.source / "bin" / ".env", "SECRET=1\n")
        self.assertEqual(self.publish().returncode, 0)
        self.assertFalse((self.dest / "accio" / "bin" / ".env").exists())
        self.assertTrue((self.dest / "accio" / "bin" / "accio_lib" / "__init__.py").is_file())

    def test_refuses_a_committed_symlink(self):
        outside = pathlib.Path(self.tmp.name) / "outside.txt"
        write(outside, "private\n")
        (self.source / "bin" / "link").symlink_to(outside)
        commit_all(self.source)
        self.assert_refused(self.publish(), "symlink")

    def test_keeps_other_entries_byte_for_byte_and_extra_fields_on_accio(self):
        self.assertEqual(self.publish().returncode, 0)
        data = self.marketplace()
        data["plugins"][1]["category"] = "dev"
        write(self.dest / ".claude-plugin" / "marketplace.json", json.dumps(data, indent=2, ensure_ascii=False))
        commit_all(self.dest)
        self.assertEqual(self.publish().returncode, 0)
        raw = (self.dest / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
        self.assertIn("Idea → design", raw)
        self.assertEqual(self.marketplace()["plugins"][1]["category"], "dev")

    def test_refuses_a_manifest_that_is_not_accio(self):
        write(self.source / ".claude-plugin" / "plugin.json",
              json.dumps({"name": "foreman", "version": "1.0.0", "description": "x"}))
        commit_all(self.source)
        self.assert_refused(self.publish(), "accio")

    def test_refuses_a_manifest_missing_a_field_and_changes_nothing(self):
        write(self.source / ".claude-plugin" / "plugin.json", json.dumps({"name": "accio", "version": "0.1.0"}))
        commit_all(self.source)
        before = (self.dest / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
        self.assert_refused(self.publish(), "description")
        self.assertEqual((self.dest / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"), before)

    def test_refuses_when_the_release_repo_has_uncommitted_changes_there(self):
        write(self.dest / "accio" / "README.md", "hand edit\n")
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("uncommitted", result.stderr)
        self.assertEqual((self.dest / "accio" / "README.md").read_text(encoding="utf-8"), "hand edit\n")

    def test_refuses_when_the_target_is_a_symlink(self):
        elsewhere = pathlib.Path(self.tmp.name) / "elsewhere"
        elsewhere.mkdir()
        (self.dest / "accio").symlink_to(elsewhere)
        commit_all(self.dest)
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink", result.stderr)
        self.assertTrue(elsewhere.is_dir())


if __name__ == "__main__":
    unittest.main()
