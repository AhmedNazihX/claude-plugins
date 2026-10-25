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

    def test_S_081_5_first_year_has_its_model_and_role(self):
        row = table_rows()["first-year"]
        self.assertEqual(row["Model"], "`sonnet`")
        self.assertEqual(row["Role"], "the fresh reader")
        self.assertIn("design", row["What it does"])


DESIGN = ROOT / "docs" / "DESIGN.md"
PLUGIN = ROOT / ".claude-plugin" / "plugin.json"
TOKEN_FIGURE = re.compile(r"~?([\d,]+) tokens of accio's descriptions|about ([\d,]+) tokens for all accio descriptions")


def token_figures(path):
    found = []
    text = re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))
    for match in TOKEN_FIGURE.finditer(text):
        found.append(int((match.group(1) or match.group(2)).replace(",", "")))
    return found


class StaleTextTest(unittest.TestCase):
    def test_S_031_1_no_two_checkpoints_text(self):
        for path in (PLUGIN, README, DESIGN):
            with self.subTest(path.name):
                text = re.sub(r"\s+", " ", path.read_text(encoding="utf-8")).lower()
                self.assertNotIn("two checkpoints", text)
                self.assertNotIn("two checkpoints per iteration", text)

    def test_S_031_2_same_token_figure_in_readme_and_design(self):
        readme, design = token_figures(README), token_figures(DESIGN)
        self.assertEqual(len(readme), 1)
        self.assertEqual(readme, design)
        self.assertLessEqual(readme[0], 2000)


if __name__ == "__main__":
    unittest.main()
