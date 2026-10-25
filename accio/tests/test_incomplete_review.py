"""S-080: a reviewer (or boggart) that can't read a file it needs says so with `incomplete`, never a verdict; sort
names an incomplete backlog check in its summary."""
import unittest

from support import ROOT

AGENTS = ROOT / "agents"
REVIEWERS = ("examiner", "professor", "auror")


def body(name):
    text = (AGENTS / f"{name}.md").read_text(encoding="utf-8")
    return " ".join(text.removeprefix("---\n").split("\n---\n", 1)[1].split())


def sort_step(number):
    text = (ROOT / "skills" / "sort" / "SKILL.md").read_text(encoding="utf-8")
    return " ".join(text.split(f"## {number}.", 1)[1].split(f"## {number + 1}.", 1)[0].split())


class IncompleteReviewTest(unittest.TestCase):
    def test_S_080_4_reviewers_read_every_input_first_and_reply_incomplete_with_the_path(self):
        for name in REVIEWERS:
            with self.subTest(name):
                text = body(name)
                self.assertIn("Before any verdict, read the package, the diff, the story and every checklist the "
                              "package names", text)
                self.assertIn("If one can't be read, write no findings", text)
                self.assertIn('"verdict": "incomplete"', text)
                self.assertIn('"missing": "<the path you couldn\'t read>"', text)
                self.assertIn("counts all 0", text)
                self.assertIn('"pass" | "fail" | "incomplete"', text)

    def test_S_080_4_boggart_replies_incomplete_with_the_path(self):
        text = body("boggart")
        self.assertIn("If a file you need can't be read", text)
        self.assertIn('"incomplete": true', text)
        self.assertIn('"missing": "<the path you couldn\'t read>"', text)

    def test_S_080_5_sort_calls_an_incomplete_backlog_check_once_more_then_names_it(self):
        step = sort_step(4)
        self.assertIn("If its verdict is incomplete, call examiner once more", step)
        self.assertIn("still incomplete", step)
        self.assertIn("never take it as a pass", step)
        summary = sort_step(6)
        self.assertIn("backlog check incomplete", summary)
        self.assertIn("What I need from you: <nothing | the fix | the file the backlog check couldn't read>", summary)


if __name__ == "__main__":
    unittest.main()
