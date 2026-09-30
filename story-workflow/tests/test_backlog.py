"""Tests for scripts/backlog.py. Stdlib only: run with `python3 -m unittest discover -s tests` from the repo root."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "backlog.py"
FIXTURE = Path(__file__).parent / "fixtures" / "backlog.md"

spec = importlib.util.spec_from_file_location("backlog", SCRIPT)
assert spec and spec.loader
backlog = importlib.util.module_from_spec(spec)
sys.modules["backlog"] = backlog
spec.loader.exec_module(backlog)


def run(*args: str, path: Path = FIXTURE) -> subprocess.CompletedProcess[str]:
    """Run the CLI on a backlog, outside any git repo so no story branches are found."""
    with tempfile.TemporaryDirectory() as cwd:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--file", str(path), *args],
            capture_output=True, text=True, cwd=cwd,
        )


def section(output: str, name: str) -> str:
    """The lines of one '## <name> (n)' section of the status output."""
    lines = output.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"## {name}"))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start:end])


class ParseDeps(unittest.TestCase):
    def test_ids_ranges_and_sub_story_ranges(self) -> None:
        ids, notes = backlog.parse_deps("F1, E2–E4, B5a–c")
        self.assertEqual(ids, ["F1", "E2", "E3", "E4", "B5a", "B5b", "B5c"])
        self.assertEqual(notes, [])

    def test_none_with_a_remark_is_a_manual_condition(self) -> None:
        self.assertEqual(backlog.parse_deps("– (run in week 9)"), ([], ["run in week 9"]))

    def test_text_beside_an_id_is_kept_as_a_condition(self) -> None:
        ids, notes = backlog.parse_deps("B3 committed")
        self.assertEqual(ids, ["B3"])
        self.assertEqual(notes, ["B3 committed"])


class Parsing(unittest.TestCase):
    def setUp(self) -> None:
        self.b = backlog.Backlog(FIXTURE)

    def test_a_grouped_entry_answers_to_its_group_and_sub_ids(self) -> None:
        group = self.b.find("B2")
        self.assertEqual(group.sub_ids, ["B2a", "B2b", "B2c"])
        self.assertIs(self.b.find("B2b"), group)
        self.assertTrue(group.is_done("B2a"))
        self.assertFalse(group.is_done("B2b"))

    def test_tags(self) -> None:
        f1, f2, e1 = self.b.find("F1"), self.b.find("F2"), self.b.find("E1")
        self.assertTrue(f1.solo)
        self.assertEqual(f1.size, 1)
        self.assertEqual(f2.resources, ["db-schema"])
        self.assertEqual(e1.lane, "Engine")

    def test_fields_read_inline_and_ignore_notes(self) -> None:
        e2 = self.b.find("E2")
        self.assertIn("labels.yaml", e2.fields("Input"))
        self.assertNotIn("labels.yaml", e2.fields("Output"))
        self.assertNotIn("scaffolded", self.b.find("F1").fields("Output", "DoD"))


class Warnings(unittest.TestCase):
    def setUp(self) -> None:
        self.b = backlog.Backlog(FIXTURE)

    def test_a_migration_without_a_resource_tag_is_hinted(self) -> None:
        self.assertEqual(self.b.find("E3").resource_hints, ["db-schema"])

    def test_a_tagged_story_has_no_hint(self) -> None:
        self.assertEqual(self.b.find("F2").resource_hints, [])

    def test_frozen_lockfile_is_not_lockfile_work(self) -> None:
        self.assertEqual(self.b.find("P1").resource_hints, [])

    def test_a_dod_naming_an_open_sub_story_outside_the_deps_is_a_gap(self) -> None:
        # E1 depends on B2a only; its DoD needs the B2b cases.
        gaps = self.b.dod_input_gaps(self.b.find("E1"))
        self.assertEqual(len(gaps), 1)
        self.assertIn("B2b", gaps[0])

    def test_an_input_path_another_open_story_creates_is_a_gap(self) -> None:
        gaps = self.b.dod_input_gaps(self.b.find("E2"))
        self.assertEqual(len(gaps), 1)
        self.assertIn("B1's Output creates", gaps[0])

    def test_a_dep_on_the_whole_group_covers_its_sub_stories(self) -> None:
        self.assertEqual(self.b.ancestors(self.b.find("E3")) >= {"B2", "B2a", "B2b", "B2c", "E2", "F3", "F1"}, True)

    def test_a_dep_on_one_sub_story_covers_only_that_one(self) -> None:
        covered = self.b.ancestors(self.b.find("E1"))
        self.assertIn("B2a", covered)
        self.assertNotIn("B2b", covered)


class Commands(unittest.TestCase):
    def test_check_passes_and_prints_the_warnings(self) -> None:
        out = run("check")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("E3: mentions db-schema work", out.stdout)
        self.assertIn("E1's Input/DoD names B2b", out.stdout)
        self.assertIn("3 warning(s)", out.stdout)

    def test_check_fails_on_a_missing_field_and_an_unknown_dep(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "backlog.md"
            bad.write_text("- [ ] **A1 · Broken** · Deps: Z9 · Type: robot\n  Output: x.\n", encoding="utf-8")
            out = run("check", path=bad)
        self.assertEqual(out.returncode, 1)
        self.assertIn("Type is 'robot'", out.stdout)
        self.assertIn("no 'DoD:'", out.stdout)
        self.assertIn("unknown story Z9", out.stdout)

    def test_check_reports_a_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            cyclic = Path(d) / "backlog.md"
            cyclic.write_text(
                "- [ ] **A1 · One** · Deps: A2 · Type: agent\n  Output: a. DoD: a.\n\n"
                "- [ ] **A2 · Two** · Deps: A1 · Type: agent\n  Output: b. DoD: b.\n",
                encoding="utf-8",
            )
            out = run("check", path=cyclic)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("Dependency cycle", out.stderr)

    def test_status_groups_the_stories(self) -> None:
        out = run("status").stdout
        ready, blocked = section(out, "Ready"), section(out, "Blocked")
        self.assertIn("F3 · Contracts", ready)
        self.assertIn("B1 · Label cases", ready)
        self.assertIn("W1 · Week-nine check", ready)
        self.assertIn("(check: run in week 9)", ready)
        self.assertIn("E1 · Engine node  ← waiting on F3", blocked)
        self.assertIn("B2a–c", blocked)
        self.assertIn("sub-stories left: B2b, B2c", blocked)
        self.assertIn("Backlog: 2/10 stories done", out)

    def test_status_names_what_the_next_critical_story_waits_on(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "backlog.md"
            path.write_text(
                "- [ ] **A1 · First** · Deps: – · Type: human\n  Output: a. DoD: a.\n\n"
                "- [ ] **A2 · Second** · Deps: A1 · Type: agent · Size: L\n  Output: b. DoD: b.\n",
                encoding="utf-8",
            )
            out = run("status", path=path).stdout
        self.assertIn("next on the path: A1", out)
        self.assertNotIn("waiting on", section(out, "Critical path"))

    def test_status_marks_a_story_ready_to_build_but_not_to_finish(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "backlog.md"
            path.write_text(
                "- [ ] **A1 · Cases** · Deps: – · Type: human\n  Output: `cases/a.yaml`. DoD: approved.\n\n"
                "- [ ] **A2 · Node** · Deps: – · Type: agent\n  Output: node. DoD: passes on `cases/a.yaml`.\n",
                encoding="utf-8",
            )
            ready = section(run("status", path=path).stdout, "Ready")
        self.assertIn("A2 · Node", ready)
        self.assertIn("ready to build, not to finish", ready)

    def test_info_is_json_with_the_new_fields(self) -> None:
        info = json.loads(run("info", "E3").stdout)
        self.assertEqual(info["resource_hints"], ["db-schema"])
        self.assertEqual(info["deps"], ["E2", "B2"])
        self.assertIn("dod_input_gaps", info)
        sub = json.loads(run("info", "B2a").stdout)
        self.assertEqual(sub["branch_id"], "B2a")
        self.assertTrue(sub["done"])

    def test_a_sub_story_is_startable_but_its_group_is_not(self) -> None:
        self.assertEqual(json.loads(run("info", "B2b").stdout)["sub_stories"], [])
        self.assertEqual(json.loads(run("info", "B2").stdout)["sub_stories"], ["B2a", "B2b", "B2c"])

    def test_waves_wait_for_the_one_sub_story_a_story_depends_on(self) -> None:
        # E1 depends on F3 and B2a (done): it runs right after F3, not after the whole B2 group.
        waves = [[s.id for s in w] for w in backlog.Backlog(FIXTURE).waves()]
        e1 = next(i for i, w in enumerate(waves) if "E1" in w)
        f3 = next(i for i, w in enumerate(waves) if "F3" in w)
        group = next(i for i, w in enumerate(waves) if "B2a–c" in w)
        self.assertEqual(e1, f3 + 1)
        self.assertLessEqual(e1, group)

    def test_an_unknown_id_inside_a_written_condition_is_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "backlog.md"
            path.write_text(
                "- [ ] **A1 · Model** · Deps: – (GPT4 access granted) · Type: human\n  Output: a. DoD: a.\n\n"
                "- [ ] **A2 · Other** · Deps: GPT4 access, A1 · Type: agent\n  Output: b. DoD: b.\n",
                encoding="utf-8",
            )
            out = run("check", path=path)
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertNotIn("unknown story", out.stdout)

    def test_a_range_across_letters_keeps_both_ends(self) -> None:
        ids, notes = backlog.parse_deps("C1–D3")
        self.assertEqual(ids, ["C1", "D3"])
        self.assertTrue(any("across letters" in n for n in notes))

    def test_missing_arguments_give_usage_not_a_traceback(self) -> None:
        for args in (("show",), ("tick",), ("--file",)):
            out = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertNotIn("Traceback", out.stderr)

    def copy(self, d: str) -> Path:
        path = Path(d) / "backlog.md"
        shutil.copy(FIXTURE, path)
        return path

    def test_note_adds_a_hand_over_line_to_the_entry(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self.copy(d)
            out = run("note", "E1", "--from", "F3", "use the Result schema", path=path)
            self.assertEqual(out.returncode, 0, out.stderr)
            shown = run("show", "E1", path=path).stdout
        self.assertTrue(shown.rstrip().endswith("**From F3 (merged):** use the Result schema"))

    def test_note_on_a_sub_story_goes_on_its_group(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self.copy(d)
            run("note", "B2b", "**Rule:** keep German cases", path=path)
            self.assertIn("**Rule:** keep German cases", run("show", "B2", path=path).stdout)

    def test_set_deps_replaces_the_field_and_keeps_the_header(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self.copy(d)
            self.assertEqual(run("set-deps", "E2", "F3, B1", path=path).returncode, 0)
            header = run("show", "E2", path=path).stdout.splitlines()[0]
            self.assertIn("· Deps: F3, B1 · Type: agent", header)
            self.assertIn("B1", json.loads(run("info", "E2", path=path).stdout)["deps"])

    def test_set_deps_refuses_a_cycle_and_leaves_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self.copy(d)
            before = path.read_text(encoding="utf-8")
            out = run("set-deps", "F3", "E1", path=path)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("cycle", out.stderr)
            self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_add_inserts_a_story_after_another(self) -> None:
        entry = "- [ ] **C9 · Relevance cut-off** · Deps: F3 · Type: agent\n  Output: `x.py`. DoD: tests pass.\n"
        with tempfile.TemporaryDirectory() as d:
            path = self.copy(d)
            with tempfile.TemporaryDirectory() as cwd:
                out = subprocess.run([sys.executable, str(SCRIPT), "--file", str(path), "add", "--after", "E1"],
                                     input=entry, capture_output=True, text=True, cwd=cwd)
            self.assertEqual(out.returncode, 0, out.stderr)
            ids = [s.id for s in backlog.Backlog(path).stories]
            self.assertEqual(ids.index("C9"), ids.index("E1") + 1)
            self.assertEqual(run("check", path=path).returncode, 0)

    def test_add_refuses_a_duplicate_id(self) -> None:
        entry = "- [ ] **E1 · Again** · Deps: – · Type: agent\n  Output: x. DoD: y.\n"
        with tempfile.TemporaryDirectory() as d:
            path = self.copy(d)
            out = subprocess.run([sys.executable, str(SCRIPT), "--file", str(path), "add", "--after", "F3"],
                                 input=entry, capture_output=True, text=True)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("duplicate ID E1", out.stderr)

    def test_note_refuses_a_newline_or_a_fake_outcome_and_leaves_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self.copy(d)
            before = path.read_text(encoding="utf-8")
            injected = "line1\n- [ ] **Z9 · Injected** · Deps: – · Type: agent"
            for text in (injected, "**Outcome (B2b):** done"):
                out = run("note", "B2", text, path=path)
                self.assertNotEqual(out.returncode, 0, text)
            self.assertEqual(path.read_text(encoding="utf-8"), before)
            self.assertFalse(json.loads(run("info", "B2b", path=path).stdout)["done"])

    def test_a_sub_story_note_is_marked_with_its_id(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self.copy(d)
            run("note", "B2b", "for b only", path=path)
            self.assertIn("(B2b) for b only", run("show", "B2", path=path).stdout)

    def test_set_deps_refuses_a_sub_story_and_an_unknown_dep(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self.copy(d)
            before = path.read_text(encoding="utf-8")
            sub = run("set-deps", "B2b", "–", path=path)
            self.assertNotEqual(sub.returncode, 0)
            self.assertIn("group", sub.stderr)
            unknown = run("set-deps", "E2", "C99", path=path)
            self.assertNotEqual(unknown.returncode, 0)
            self.assertIn("unknown story C99", unknown.stderr)
            self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_writes_keep_windows_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "backlog.md"
            path.write_bytes(FIXTURE.read_bytes().replace(b"\n", b"\r\n"))
            self.assertEqual(run("note", "E1", "keep CRLF", path=path).returncode, 0)
            data = path.read_bytes()
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))
        self.assertIn(b"  keep CRLF\r\n", data)

    def test_add_drops_trailing_blank_lines_and_refuses_a_story_without_a_dod(self) -> None:
        good = "- [ ] **C9 · Cut-off** · Deps: F3 · Type: agent\n  Output: `x.py`. DoD: tests pass.\n\n\n  \n"
        bad = "- [ ] **C8 · No DoD** · Deps: F3 · Type: agent\n  Output: `y.py`.\n"
        with tempfile.TemporaryDirectory() as d:
            path = self.copy(d)
            for entry, ok in ((good, True), (bad, False)):
                out = subprocess.run([sys.executable, str(SCRIPT), "--file", str(path), "add", "--after", "E1"],
                                     input=entry, capture_output=True, text=True)
                self.assertEqual(out.returncode == 0, ok, out.stderr)
            text = path.read_text(encoding="utf-8")
        self.assertIn("DoD: tests pass.\n\n- [ ] **E2", text)
        self.assertNotIn("C8 · No DoD", text)

    def test_deps_exit_code(self) -> None:
        self.assertEqual(run("deps", "F3").returncode, 0)
        blocked = run("deps", "E1")
        self.assertEqual(blocked.returncode, 1)
        self.assertIn("unmet: F3", blocked.stdout)

    def test_plan_puts_solo_alone_and_one_story_per_resource(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "backlog.md"
            path.write_text(
                "- [ ] **A1 · Alone** · Deps: – · Type: agent · Solo\n  Output: a. DoD: a.\n\n"
                "- [ ] **A2 · Schema one** · Deps: – · Type: agent · Resource: db\n  Output: b. DoD: b.\n\n"
                "- [ ] **A3 · Schema two** · Deps: – · Type: agent · Resource: db\n  Output: c. DoD: c.\n",
                encoding="utf-8",
            )
            waves = backlog.Backlog(path).waves()
        ids = [[s.id for s in w] for w in waves]
        self.assertIn(["A1"], ids)
        self.assertTrue(all(not {"A2", "A3"} <= set(w) for w in ids))

    def test_tick_a_sub_story_then_the_group(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "backlog.md"
            shutil.copy(FIXTURE, path)
            refused = run("tick", "B2", "all", path=path)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("B2b, B2c", refused.stderr)
            for sid in ("B2b", "B2c"):
                self.assertEqual(run("tick", sid, f"{sid} done", path=path).returncode, 0)
            self.assertIn("- [ ] **B2a–c", path.read_text(encoding="utf-8"))
            self.assertEqual(run("tick", "B2", "all three", path=path).returncode, 0)
            text = path.read_text(encoding="utf-8")
        self.assertIn("- [x] **B2a–c", text)
        self.assertIn("**Outcome (B2c):** B2c done", text)
        self.assertIn("**Outcome:** all three", text)


if __name__ == "__main__":
    unittest.main()
