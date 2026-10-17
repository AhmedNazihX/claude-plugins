"""S-009: accio-cost (tokens per story and iteration from workflow transcripts)."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, init_repo, write

from accio_lib import cost

COST = ROOT / "bin" / "accio-cost"


def usage(inp=0, create=0, read=0, out=0):
    return {"input_tokens": inp, "cache_creation_input_tokens": create, "cache_read_input_tokens": read,
            "output_tokens": out}


def add_agent(run_dir, agent_id, label, messages):
    """A workflow agent transcript the way Claude Code writes it (spike S-001, finding 4)."""
    write(run_dir / f"agent-{agent_id}.meta.json", json.dumps({"agentType": "accio:house-elf", "description": label}))
    lines = [json.dumps({"type": "user", "message": {"content": "prompt"}})]
    for entry in messages:
        u, message_id = entry if isinstance(entry, tuple) else (entry, None)
        message = {"model": "claude-sonnet", "usage": u, **({"id": message_id} if message_id else {})}
        lines.append(json.dumps({"type": "assistant", "requestId": f"req-{message_id}", "message": message}))
    write(run_dir / f"agent-{agent_id}.jsonl", "\n".join(lines) + "\n")


class CostTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = pathlib.Path(self.tmp.name) / "wf_1"
        self.run.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_S_009_4_sums_every_agent_grouped_by_its_label(self):
        add_agent(self.run, "a1", "S-001 implement", [usage(10, 100, 1000, 5), usage(1, 0, 2000, 4)])
        add_agent(self.run, "a2", "S-001 review: spec", [usage(2, 50, 500, 3)])
        add_agent(self.run, "a3", "S-002 implement", [usage(7, 0, 0, 1)])
        totals = cost.story_tokens([self.run], ("S-001", "S-002"))
        self.assertEqual(totals["S-001"]["tokens"], 10 + 100 + 1000 + 5 + 1 + 2000 + 4 + 2 + 50 + 500 + 3)
        self.assertEqual(totals["S-001"]["breakdown"], {"input": 13, "cache_creation": 150, "cache_read": 3500,
                                                         "output": 12})
        self.assertEqual(totals["S-002"]["tokens"], 8)

    def test_S_009_4_one_api_response_split_over_lines_is_counted_once(self):
        add_agent(self.run, "a1", "S-001 implement", [(usage(10, 100, 1000, 6), "msg_1"), (usage(10, 100, 1000, 139), "msg_1"),
                                                      (usage(1, 0, 0, 5), "msg_2")])
        totals = cost.story_tokens([self.run], ("S-001",))
        self.assertEqual(totals["S-001"]["breakdown"], {"input": 11, "cache_creation": 100, "cache_read": 1000,
                                                         "output": 144})

    def test_the_same_run_folder_given_twice_is_counted_once(self):
        add_agent(self.run, "a1", "S-001 implement", [usage(out=10)])
        self.assertEqual(cost.report([self.run, self.run.parent / "wf_1" / "."], {"S-001": 100})["total"], 10)

    def test_label_matching_is_exact_on_the_story_id(self):
        add_agent(self.run, "a1", "S-0012 implement", [usage(out=1)])
        add_agent(self.run, "a2", "S-001x implement", [usage(out=2)])
        add_agent(self.run, "a3", "S-001: review", [usage(out=4)])
        report = cost.report([self.run], {"S-001": 100})
        self.assertEqual(report["stories"]["S-001"]["tokens"], 4)
        self.assertEqual(report["unattributed"], 3)

    def test_usage_outside_assistant_messages_is_ignored(self):
        add_agent(self.run, "a1", "S-001 implement", [usage(out=10)])
        with (self.run / "agent-a1.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"type": "user", "message": {"usage": usage(out=999)}}) + "\n")
        self.assertEqual(cost.report([self.run], {"S-001": 100})["stories"]["S-001"]["tokens"], 10)

    def test_S_009_1_sums_across_runs_and_for_the_iteration(self):
        second = pathlib.Path(self.tmp.name) / "wf_2"
        add_agent(self.run, "a1", "S-001 implement", [usage(out=100)])
        add_agent(second, "b1", "S-001 fix round 1", [usage(out=50)])
        add_agent(second, "b2", "S-002 implement", [usage(out=25)])
        report = cost.report([self.run, second], {"S-001": 1000, "S-002": 1000})
        self.assertEqual(report["stories"]["S-001"]["tokens"], 150)
        self.assertEqual(report["total"], 175)
        self.assertFalse(report["partial"])

    def test_agents_without_a_story_label_are_counted_apart(self):
        add_agent(self.run, "a1", "load batch", [usage(out=40)])
        add_agent(self.run, "a2", "S-001 implement", [usage(out=10)])
        report = cost.report([self.run], {"S-001": 1000})
        self.assertEqual(report["unattributed"], 40)
        self.assertEqual(report["total"], 50)

    def test_S_009_2_over_budget_and_two_times_over_are_flagged_separately(self):
        add_agent(self.run, "a1", "S-001 implement", [usage(out=150)])
        add_agent(self.run, "a2", "S-002 implement", [usage(out=250)])
        add_agent(self.run, "a3", "S-003 implement", [usage(out=50)])
        stories = cost.report([self.run], {"S-001": 100, "S-002": 100, "S-003": 100})["stories"]
        self.assertEqual((stories["S-001"]["over"], stories["S-001"]["stop"]), (True, False))
        self.assertEqual((stories["S-002"]["over"], stories["S-002"]["stop"]), (True, True))
        self.assertEqual((stories["S-003"]["over"], stories["S-003"]["stop"]), (False, False))

    def test_S_009_3_a_story_with_no_readable_transcript_is_unknown_not_zero(self):
        add_agent(self.run, "a1", "S-001 implement", [usage(out=10)])
        write(self.run / "agent-a2.meta.json", json.dumps({"description": "S-002 implement"}))
        report = cost.report([self.run], {"S-001": 100, "S-002": 100, "S-003": 100})
        self.assertIsNone(report["stories"]["S-002"]["tokens"])
        self.assertIsNone(report["stories"]["S-003"]["tokens"])
        self.assertTrue(report["partial"])
        self.assertEqual(report["total"], 10)

    def test_S_009_3_a_corrupt_transcript_makes_its_story_unknown(self):
        add_agent(self.run, "a1", "S-001 implement", [usage(out=10)])
        with (self.run / "agent-a1.jsonl").open("a", encoding="utf-8") as stream:
            stream.write("{not json\n")
        self.assertIsNone(cost.report([self.run], {"S-001": 100})["stories"]["S-001"]["tokens"])

    def test_S_009_3_one_good_and_one_broken_agent_make_the_story_unknown(self):
        add_agent(self.run, "a1", "S-001 implement", [usage(out=10)])
        add_agent(self.run, "a2", "S-001 review", [usage(out=10)])
        (self.run / "agent-a2.jsonl").write_text("{not json\n", encoding="utf-8")
        self.assertIsNone(cost.report([self.run], {"S-001": 100})["stories"]["S-001"]["tokens"])

    def test_S_009_3_a_meta_file_without_its_transcript_makes_the_story_unknown(self):
        add_agent(self.run, "a1", "S-001 implement", [usage(out=10)])
        write(self.run / "agent-a2.meta.json", json.dumps({"description": "S-001 review"}))
        self.assertIsNone(cost.report([self.run], {"S-001": 100})["stories"]["S-001"]["tokens"])

    def test_a_broken_agent_without_a_story_makes_the_total_partial(self):
        add_agent(self.run, "a1", "S-001 implement", [usage(out=10)])
        add_agent(self.run, "a2", "load batch", [usage(out=10)])
        (self.run / "agent-a2.jsonl").write_text("{not json\n", encoding="utf-8")
        report = cost.report([self.run], {"S-001": 100})
        self.assertEqual(report["stories"]["S-001"]["tokens"], 10)
        self.assertTrue(report["partial"])

    def test_a_corrupt_or_missing_meta_file_is_unreadable_not_unattributed(self):
        add_agent(self.run, "a1", "S-001 implement", [usage(out=10)])
        add_agent(self.run, "a2", "S-001 review", [usage(out=500)])
        (self.run / "agent-a2.meta.json").write_text("{broken", encoding="utf-8")
        report = cost.report([self.run], {"S-001": 100})
        self.assertTrue(report["partial"])
        self.assertEqual(report["unattributed"], 0)
        (self.run / "agent-a2.meta.json").unlink()
        self.assertTrue(cost.report([self.run], {"S-001": 100})["partial"])

    def test_odd_but_valid_json_makes_the_story_unknown_without_a_crash(self):
        for number, line in enumerate(('[1, 2]', '{"type": "assistant", "message": "hi"}',
                                       json.dumps({"type": "assistant", "message": {"usage": {"output_tokens": "abc"}}}),
                                       json.dumps({"type": "assistant", "message": {"usage": {"output_tokens": {"n": 1}}}}))):
            run = pathlib.Path(self.tmp.name) / f"odd{number}"
            add_agent(run, "a1", "S-001 implement", [usage(out=10)])
            with (run / "agent-a1.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
            self.assertIsNone(cost.report([run], {"S-001": 100})["stories"]["S-001"]["tokens"], line)

    def test_a_missing_run_folder_makes_everything_unknown(self):
        report = cost.report([self.run / "gone"], {"S-001": 100})
        self.assertIsNone(report["stories"]["S-001"]["tokens"])
        self.assertTrue(report["partial"])


class CostCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = init_repo(pathlib.Path(self.tmp.name).resolve() / "app")
        self.accio = self.repo / ".accio"
        write(self.accio / "config.json", json.dumps({"budgets": {"quick": 50, "story": 100}}))
        for story_id, track, extra in (("S-001", "quick", ""), ("S-002", "story", "budget_tokens: 500\n")):
            write(self.accio / "stories" / f"{story_id}.md",
                  f"---\nid: {story_id}\ntitle: x\ntrack: {track}\nstatus: review\n{extra}---\n"
                  f"## Definition of Done\n- [ ] {story_id}/1 WHEN x THE SYSTEM SHALL y\n")
        self.run = pathlib.Path(self.tmp.name) / "wf_1"
        add_agent(self.run, "a1", "S-001 implement", [usage(out=60)])
        add_agent(self.run, "a2", "S-002 implement", [usage(out=300)])

    def tearDown(self):
        self.tmp.cleanup()

    def test_budgets_come_from_the_track_or_the_story(self):
        result = subprocess.run([sys.executable, "-I", str(COST), "--run", str(self.run), "--json", "S-001", "S-002"],
                                cwd=self.repo, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        stories = json.loads(result.stdout)["stories"]
        self.assertEqual((stories["S-001"]["budget"], stories["S-001"]["over"]), (50, True))
        self.assertEqual((stories["S-002"]["budget"], stories["S-002"]["over"]), (500, False))

    def test_plain_output_names_each_story(self):
        result = subprocess.run([sys.executable, "-I", str(COST), "--run", str(self.run), "S-001", "S-002"],
                                cwd=self.repo, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("S-001", result.stdout)
        self.assertIn("over budget", result.stdout)


if __name__ == "__main__":
    unittest.main()
