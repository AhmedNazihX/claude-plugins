# Review checklist

Workers read this before DONE and check their own staged diff against each line that applies. `story-finish` adds
a line when the same kind of major finding comes back in a second story (with both story IDs).

- Only release stories (V1–V3) change the version in `plugin.json` or the README; others add one line under
  `## Unreleased` in `foreman/CHANGELOG.md`. (Design › Rules)
- Scripts import only the Python standard library. (Design › Rules)
- Every hook change has a test that blocks the forbidden case and passes a legitimate near-miss. (Design › Rules)
- Read-only agents keep a read-only `tools` list. (Design › Rules)
- Docs and skill text are plain English: short sentences, no jargon, matching the existing skills. (Design › Rules)
- No text from a real transcript or the capstone in fixtures or docs. (Backlog › Global rules)
