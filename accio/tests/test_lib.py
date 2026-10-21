"""S-003: the shared library (paths, config, story files)."""
import json
import pathlib
import tempfile
import unittest

from support import FIXTURES, git, init_repo, write

from accio_lib import config, paths, story


class PathsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.tmp.name).resolve()
        self.repo = init_repo(self.base / "app")

    def tearDown(self):
        self.tmp.cleanup()

    def test_S_003_1_main_checkout_and_outside_worktree_find_the_same_accio(self):
        (self.repo / ".accio").mkdir()
        worktree = self.base / ".app-accio-wt" / "S-012"
        git(self.repo, "worktree", "add", "-q", str(worktree), "-b", "story/S-012")
        expected = self.repo / ".accio"
        self.assertEqual(paths.accio_dir(self.repo), expected)
        self.assertEqual(paths.accio_dir(worktree), expected)
        (worktree / "nested").mkdir()
        self.assertEqual(paths.accio_dir(worktree / "nested"), expected)

    def test_S_003_2_no_accio_folder_returns_none(self):
        self.assertIsNone(paths.accio_dir(self.repo))

    def test_S_003_2_outside_any_git_repo_returns_none(self):
        outside = self.base / "plain"
        outside.mkdir()
        self.assertIsNone(paths.accio_dir(outside))

    def test_S_003_1_submodule_finds_its_own_accio(self):
        library = init_repo(self.base / "lib")
        git(self.repo, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(library), "sub")
        (self.repo / "sub" / ".accio").mkdir()
        self.assertEqual(paths.accio_dir(self.repo / "sub"), self.repo / "sub" / ".accio")

    def test_S_003_1_separate_git_dir_finds_accio(self):
        checkout = self.base / "sep"
        git(self.base, "init", "-q", "--separate-git-dir", str(self.base / "sep.git"), str(checkout))
        (checkout / ".accio").mkdir()
        self.assertEqual(paths.accio_dir(checkout), checkout / ".accio")

    def test_worktree_of_a_separate_git_dir_repo_is_not_supported(self):
        """Pinned on purpose (DESIGN § 4.6): git doesn't record the main checkout here; setup warns (S-012)."""
        checkout = self.base / "sep"
        git(self.base, "init", "-q", "--separate-git-dir", str(self.base / "sep.git"), str(checkout))
        write(checkout / "README.md", "x\n")
        git(checkout, "add", "-A")
        git(checkout, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "init")
        (checkout / ".accio").mkdir()
        git(checkout, "worktree", "add", "-q", str(self.base / "sep-wt"), "-b", "story/S-001")
        self.assertIsNone(paths.accio_dir(self.base / "sep-wt"))

    def test_S_003_2_unreadable_folder_returns_none(self):
        locked = self.base / "locked"
        locked.mkdir(mode=0o000)
        try:
            self.assertIsNone(paths.accio_dir(locked))
        finally:
            locked.chmod(0o755)

    def test_worktree_root_sits_next_to_the_repo(self):
        self.assertEqual(paths.worktree_root(self.repo), self.base / ".app-accio-wt")

    def test_main_root_is_the_main_checkout_from_a_worktree(self):
        worktree = self.base / "wt"
        git(self.repo, "worktree", "add", "-q", str(worktree), "-b", "x")
        self.assertEqual(paths.main_root(worktree), self.repo)


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.accio = pathlib.Path(self.tmp.name) / ".accio"
        self.accio.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write_config(self, data):
        write(self.accio / "config.json", json.dumps(data))

    def test_S_003_3_missing_file_gives_the_design_defaults(self):
        loaded = config.load(self.accio)
        expected = {"base_branch": "main", "push_mode": "direct", "checks": (), "wip": 3, "iteration_max": 8,
                    "stack_depth": 2, "agent_allow": (), "paid_call_cap_usd": 0,
                    "budgets": {"quick": 80000, "story": 400000}}
        for key, value in expected.items():
            self.assertEqual(loaded[key], value, key)
        self.assertIn(".github/workflows/**", loaded["risky_paths"])

    def test_values_from_the_file_are_read_only_too(self):
        self.write_config({"agent_allow": ["make"], "checks": [{"command": "make test", "glob": "**"}]})
        loaded = config.load(self.accio)
        with self.assertRaises(AttributeError):
            loaded["agent_allow"].append("rm")
        with self.assertRaises(TypeError):
            loaded["checks"][0]["command"] = "rm -rf /"

    def test_unreadable_config_names_the_file(self):
        (self.accio / "config.json").write_bytes(b"\xff\xfe{")
        with self.assertRaisesRegex(config.ConfigError, "config.json"):
            config.load(self.accio)

    def test_S_003_3_missing_keys_fall_back_to_defaults(self):
        self.write_config({"wip": 2, "budgets": {"story": 300000}})
        loaded = config.load(self.accio)
        self.assertEqual(loaded["wip"], 2)
        self.assertEqual(loaded["budgets"], {"quick": 80000, "story": 300000})
        self.assertEqual(loaded["base_branch"], "main")
        self.assertEqual(loaded["push_mode"], "direct")
        self.assertEqual(loaded["iteration_max"], 8)
        self.assertEqual(loaded["stack_depth"], 2)
        self.assertEqual(loaded["paid_call_cap_usd"], 0)
        self.assertEqual(loaded["agent_allow"], ())

    def test_loaded_config_is_read_only(self):
        loaded = config.load(self.accio)
        with self.assertRaises(TypeError):
            loaded["wip"] = 5
        with self.assertRaises(AttributeError):
            loaded["agent_allow"].append("npm install")

    def test_checks_need_a_command_and_a_glob(self):
        self.write_config({"checks": [{"command": "npm test"}]})
        with self.assertRaisesRegex(config.ConfigError, "glob"):
            config.load(self.accio)

    def test_snapshot_skip_defaults_to_nothing_and_takes_globs(self):
        self.assertEqual(config.load(self.accio)["snapshot_skip"], ())
        self.write_config({"snapshot_skip": [".remember/**"]})
        self.assertEqual(config.load(self.accio)["snapshot_skip"], (".remember/**",))

    def test_snapshot_skip_must_be_a_list_of_globs(self):
        for bad in (".remember/**", [""], [3]):
            self.write_config({"snapshot_skip": bad})
            with self.assertRaisesRegex(config.ConfigError, "snapshot_skip"):
                config.load(self.accio)

    def test_S_047_1_ui_globs_is_a_list_of_globs_and_empty_when_unset(self):
        self.assertEqual(config.load(self.accio)["ui_globs"], ())
        self.write_config({"ui_globs": ["src/ui/**", "**/*.css"]})
        self.assertEqual(config.load(self.accio)["ui_globs"], ("src/ui/**", "**/*.css"))
        for bad in ("src/**", [""], [3]):
            self.write_config({"ui_globs": bad})
            with self.assertRaisesRegex(config.ConfigError, "ui_globs"):
                config.load(self.accio)

    def test_pr_push_mode_is_refused_until_v2(self):
        self.write_config({"push_mode": "pr"})
        with self.assertRaisesRegex(config.ConfigError, "push_mode"):
            config.load(self.accio)

    def test_unknown_key_is_rejected_by_name(self):
        self.write_config({"wipp": 3})
        with self.assertRaisesRegex(config.ConfigError, "wipp"):
            config.load(self.accio)

    def test_wrong_type_is_rejected_by_name(self):
        self.write_config({"wip": "three"})
        with self.assertRaisesRegex(config.ConfigError, "wip"):
            config.load(self.accio)

    def test_invalid_json_names_the_file(self):
        write(self.accio / "config.json", "{not json")
        with self.assertRaisesRegex(config.ConfigError, "config.json"):
            config.load(self.accio)


class StoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_S_003_4_parses_frontmatter_with_lists_ints_and_comments(self):
        parsed = story.parse(FIXTURES / "stories" / "S-012.md")
        self.assertEqual(parsed.meta["id"], "S-012")
        self.assertEqual(parsed.meta["title"], "Password reset email (fix #12)")
        self.assertEqual(parsed.meta["track"], "story")
        self.assertEqual(parsed.meta["deps"], ("S-010",))
        self.assertEqual(parsed.meta["files"], ("src/auth/reset.ts", "src/auth/reset.test.ts"))
        self.assertEqual(parsed.meta["budget_tokens"], 400000)

    def test_S_003_4_parses_numbered_dod_lines_and_no_test_marks(self):
        lines = story.parse(FIXTURES / "stories" / "S-012.md").dod
        self.assertEqual([line.id for line in lines], ["S-012/1", "S-012/2", "S-012/3"])
        self.assertEqual([line.testable for line in lines], [True, True, False])
        self.assertEqual([line.done for line in lines], [False, True, False])
        self.assertTrue(lines[0].text.startswith("WHEN a user requests a reset"))
        self.assertEqual(lines[2].text, "checks pass: `npm test`, `npm run lint`")

    def test_section_returns_the_text_under_a_heading(self):
        parsed = story.parse(FIXTURES / "stories" / "S-012.md")
        self.assertEqual(story.section(parsed, "Context"), "Users who forget their password need a way back in.")
        self.assertEqual(story.section(parsed, "Review notes"), "")
        self.assertEqual(story.section(parsed, "Missing"), "")

    def test_parsed_story_is_immutable(self):
        parsed = story.parse(FIXTURES / "stories" / "S-012.md")
        with self.assertRaises(TypeError):
            parsed.meta["status"] = "done"

    def malformed(self, text):
        path = self.dir / "S-099.md"
        write(path, text)
        with self.assertRaises(story.StoryError) as caught:
            story.parse(path)
        return str(caught.exception)

    def test_S_003_5_line_without_a_colon_names_file_and_line(self):
        message = self.malformed("---\nid: S-099\ntitle no colon\n---\n")
        self.assertIn("S-099.md:3", message)

    def test_S_003_5_missing_closing_marker_names_the_file(self):
        self.assertIn("S-099.md:1", self.malformed("---\nid: S-099\ntitle: x\n"))

    def test_S_003_5_bad_status_names_file_and_line(self):
        text = "---\nid: S-099\ntitle: x\ntrack: story\nstatus: finished\n---\n"
        message = self.malformed(text)
        self.assertIn("S-099.md:5", message)
        self.assertIn("finished", message)

    def test_S_003_5_missing_required_key_is_reported(self):
        self.assertIn("title", self.malformed("---\nid: S-099\ntrack: story\nstatus: ready\n---\n"))

    HEAD = "---\nid: S-099\ntitle: x\ntrack: story\nstatus: ready\n---\n"

    def test_S_003_5_dod_line_without_a_checkbox_is_rejected(self):
        self.assertIn("S-099.md:8", self.malformed(self.HEAD + "## Definition of Done\n- S-099/1 WHEN x THE SYSTEM SHALL y\n"))

    def test_S_003_5_indented_or_star_dod_lines_are_rejected(self):
        for line in ("  - [ ] S-099/1 WHEN x", "* [ ] S-099/1 WHEN x"):
            self.assertIn("S-099.md:8", self.malformed(self.HEAD + f"## Definition of Done\n{line}\n"))

    def test_S_003_5_missing_dod_section_is_rejected(self):
        self.assertIn("Definition of Done", self.malformed(self.HEAD + "## Definition of done\n- [ ] S-099/1 WHEN x\n"))

    def test_S_003_5_empty_dod_section_is_rejected(self):
        self.assertIn("Definition of Done", self.malformed(self.HEAD + "## Definition of Done\n\n## Review notes\n"))

    def test_S_003_4_subheadings_inside_the_dod_keep_every_line(self):
        path = self.dir / "S-099.md"
        write(path, self.HEAD + "## Definition of Done\n- [ ] S-099/1 WHEN a\n### Security\n- [ ] S-099/2 WHEN b\n## Review notes\n")
        self.assertEqual([line.id for line in story.parse(path).dod], ["S-099/1", "S-099/2"])

    def test_revert_is_a_valid_commit_type(self):
        path = self.dir / "S-099.md"
        write(path, "---\nid: S-099\ntitle: x\ntype: revert\ntrack: quick\nstatus: ready\n---\n## Definition of Done\n- [ ] S-099/1 WHEN a\n")
        self.assertEqual(story.parse(path).meta["type"], "revert")

    def test_S_003_5_duplicate_dod_id_is_rejected(self):
        body = "## Definition of Done\n- [ ] S-099/1 WHEN a\n- [ ] S-099/1 WHEN b\n"
        self.assertIn("S-099.md:9", self.malformed(self.HEAD + body))

    def test_S_003_5_list_key_without_brackets_is_rejected(self):
        message = self.malformed("---\nid: S-099\ntitle: x\ntrack: story\nstatus: ready\ndeps: S-010\n---\n")
        self.assertIn("S-099.md:6", message)
        self.assertIn("deps", message)

    def test_S_003_5_dep_that_is_not_a_story_id_is_rejected(self):
        self.assertIn("S-099.md:6", self.malformed("---\nid: S-099\ntitle: x\ntrack: story\nstatus: ready\ndeps: [S-10]\n---\n"))

    def test_S_003_5_unknown_key_is_rejected(self):
        message = self.malformed("---\nid: S-099\ntitle: x\ntrack: story\nstatus: ready\ndep: [S-010]\n---\n")
        self.assertIn("S-099.md:6", message)
        self.assertIn("dep", message)

    def test_S_003_5_budget_must_be_a_whole_number(self):
        self.assertIn("S-099.md:6", self.malformed("---\nid: S-099\ntitle: x\ntrack: story\nstatus: ready\nbudget_tokens: lots\n---\n"))

    def test_a_zero_budget_is_rejected(self):
        self.assertIn("S-099.md:6", self.malformed("---\nid: S-099\ntitle: x\ntrack: story\nstatus: ready\nbudget_tokens: 0\n---\n"))

    def test_whole_line_comments_are_skipped_and_titles_keep_hashes_and_digits(self):
        path = self.dir / "S-099.md"
        write(path, "---\n# note: planning\nid: S-099\ntitle: 404 page for C # parser\ntrack: story # t\nstatus: ready\n---\n"
                    "## Definition of Done\n- [ ] S-099/1 WHEN x THE SYSTEM SHALL y\n")
        parsed = story.parse(path)
        self.assertEqual(parsed.meta["title"], "404 page for C # parser")
        self.assertEqual(parsed.meta["track"], "story")
        self.assertNotIn("# note", parsed.meta)

    def test_unreadable_story_names_the_file(self):
        path = self.dir / "S-099.md"
        path.write_bytes(b"---\nid: \xff\n")
        with self.assertRaisesRegex(story.StoryError, "S-099.md"):
            story.parse(path)

    def test_dod_line_whose_id_belongs_to_another_story_is_rejected(self):
        text = "---\nid: S-099\ntitle: x\ntrack: story\nstatus: ready\n---\n## Definition of Done\n- [ ] S-001/1 WHEN x THE SYSTEM SHALL y\n"
        self.assertIn("S-099.md:8", self.malformed(text))


if __name__ == "__main__":
    unittest.main()
