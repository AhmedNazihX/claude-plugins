"""S-019: the README's agent table lists every agent file and its model."""
import re
import unittest

from support import ROOT

AGENTS = ROOT / "agents"
README = ROOT / "README.md"


def agent_models():
    models = {}
    for path in sorted(AGENTS.glob("*.md")):
        front = path.read_text(encoding="utf-8").removeprefix("---\n").split("\n---\n", 1)[0]
        fields = dict(line.split(":", 1) for line in front.strip().splitlines())
        models[path.stem] = fields["model"].strip()
    return models


def table_rows():
    """Rows of the README table whose header starts with Agent, as {name: cells}."""
    rows, in_table = {}, False
    for line in README.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if line.startswith("|") and cells[0] == "Agent":
            in_table, header = True, cells
            continue
        if in_table and not line.startswith("|"):
            break
        if in_table and not set(line) <= set("|- "):
            rows[cells[0].strip("`")] = dict(zip(header, cells))
    return rows


class ReadmeAgentTableTest(unittest.TestCase):
    def test_S_019_1_one_row_per_agent_file(self):
        self.assertEqual(set(table_rows()), set(agent_models()))

    def test_S_019_2_model_column_matches_each_agent_file(self):
        rows = table_rows()
        for name, model in agent_models().items():
            with self.subTest(name):
                self.assertEqual(re.sub(r"[`]", "", rows[name]["Model"]), model)


if __name__ == "__main__":
    unittest.main()
