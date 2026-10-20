# boggart's eval set

Six small cases for `agents/boggart.md` (S-042; research in `docs/research/breaker.md`): 3 with a planted break
(`break-*`) and 3 clean stories (`clean-*`) boggart must leave alone. Each case is a folder:

- `story.md`: the story, with its DoD.
- `change.diff`: the story's diff (the review package's diff; there is no house-elf report on purpose).
- `expected.md`: the planted break (its claim and why it fails), or `none` on the first line for a clean case.

## Run them by hand

For each case:

1. In a scratch git repo, make `.accio/stories/` and `.accio/run/<ID>/`, copy `story.md` in as the story (it has
   accio frontmatter, so `story.parse` accepts it), and put the story and `change.diff` together in a file as the
   review package. The `change.diff` files apply with `git apply --check`: the `break-*` and `clean-average` /
   `clean-paginate` diffs add new files to an empty repo; the `*price` diffs change `price.py` and
   `test_price.py`, so commit those two files as the base first (the diff's `-` and context lines). Commit the
   base, then apply the diff for the head (or run boggart on the diff text alone and skip `accio-break`; the claim
   and the repro are what you grade).
2. Give the scratch repo `.accio/config.json`. `accio-break` needs a `breaker` command (with `{file}` where the
   repro's path goes), and every entry in `checks` needs a `glob`:

   ```json
   {
     "breaker": {"command": "python3 -m pytest -q {file}"},
     "checks": [{"command": "python3 -m pytest -q", "glob": "**/*.py"}]
   }
   ```

3. Run boggart as the plugin agent `accio:boggart`. An installed accio from before S-052 lets boggart do nothing
   under curfew, and curfew sees the agent as `accio:boggart` only when it runs as a plugin agent. So start
   `claude -p --plugin-dir <a copy of accio from main>` in the scratch repo, and have its Workflow run an
   `agent()` of type `accio:boggart`. Give the prompt (the review package) on stdin: a `--allowedTools` list
   swallows a prompt given after it.
4. Open the repros it wrote under `run/<ID>/boggart/` and its JSON reply.

## Grade

- A **planted break** is caught when a repro names the claim in `expected.md` (quoted, with its source) and fails
  on the diff for that reason.
- A **clean story** passes when boggart keeps no break (an empty `breaks` list; questions are fine).
- Success for S-042: at least 2 of the 3 planted breaks are caught and no break is kept on the clean stories.
  Note the date, the Claude Code version and what boggart cost, in the iteration file.
