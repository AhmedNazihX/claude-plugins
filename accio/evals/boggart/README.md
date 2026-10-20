# boggart's eval set

Six small cases for `agents/boggart.md` (S-042; research in `docs/research/breaker.md`): 3 with a planted break
(`break-*`) and 3 clean stories (`clean-*`) boggart must leave alone. Each case is a folder:

- `story.md`: the story, with its DoD.
- `change.diff`: the story's diff (the review package's diff; there is no house-elf report on purpose).
- `expected.md`: the planted break (its claim and why it fails), or `none` on the first line for a clean case.

## Run them by hand

For each case:

1. In a scratch git repo, make `.accio/stories/` and `.accio/run/<ID>/`, copy `story.md` in as the story, and put
   the story and `change.diff` together in a file as the review package. Apply the diff's "before" side to commit a
   base, then the diff for the head (or run boggart on the diff text alone and skip `accio-break`; the claim and
   the repro are what you grade).
2. Run the `accio:boggart` agent on that package (Task tool, or `claude --agent accio:boggart`).
3. Open the repros it wrote under `run/<ID>/boggart/` and its JSON reply.

## Grade

- A **planted break** is caught when a repro names the claim in `expected.md` (quoted, with its source) and fails
  on the diff for that reason.
- A **clean story** passes when boggart keeps no break (an empty `breaks` list; questions are fine).
- Success for S-042: at least 2 of the 3 planted breaks are caught and no break is kept on the clean stories.
  Note the date, the Claude Code version and what boggart cost, in the iteration file.
