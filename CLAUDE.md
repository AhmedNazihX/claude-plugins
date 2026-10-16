# claude-plugins

The `nazihx` marketplace: `foreman/` (the story workflow plugin) and `git-guardrails/` (its dependency).

- **Design and plan:** `docs/DESIGN.md` (foreman 0.11–0.13), `docs/BACKLOG.md` (the stories),
  `docs/decisions/` (decision records).
- **Layout:** `docs/LAYOUT.md` is the source of truth for where files go. In short: agents in
  `foreman/agents/<name>.md`, skills in `foreman/skills/<name>/SKILL.md`, hooks in `foreman/hooks/<name>.sh` with a
  `test-<name>.sh` next to each, stdlib Python scripts in `foreman/scripts/` with tests in `foreman/tests/`.
- **Checks:** listed once, in the backlog's *Global rules for every story* (and in `.claude/foreman.json` ›
  `checks` once `setup` has run). Don't copy them elsewhere.
- **Versions:** only release stories change `foreman/.claude-plugin/plugin.json`'s version and the README version
  line; other changes add a line under `## Unreleased` in `foreman/CHANGELOG.md`.
- **The installed plugin** comes from a separate release copy (backlog story H1), not this working tree: a merge
  here reaches sessions only after a release and a `git pull` there.
- **Writing:** plain English, short sentences, no jargon, matching the existing skills.
