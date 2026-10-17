# accio v1: backlog

Built by hand, one story per session, in this order (decision 009). Source of truth: `docs/DESIGN.md`.
Each DoD line has an ID (`S-004/2`). The test that proves it carries that tag in its name or a comment.
`(no test)` marks a line checked by hand. Tick a story's DoD lines when they are met, then set its status to
`done`, and say in a line what changed.

**Layout** (applies to every story):
```
.claude-plugin/plugin.json   agents/<name>.md        skills/<name>/SKILL.md (+ references/)
workflows/brew.js            hooks/hooks.json        hooks/<name>.py
bin/accio-<name>             bin/accio_lib/          (shared Python, stdlib only)
tests/test_<name>.py         tests/workflow/*.test.mjs (node --test)   tests/fixtures/
evals/                       scripts/publish.sh
```

| Status | Story |
|---|---|
| todo | S-001 Spike: workflow, named agents, worktree |
| todo | S-002 Scaffold, CI and publish |
| todo | S-003 Shared library |
| todo | S-004 `accio-board` |
| todo | S-005 `accio-score` |
| todo | S-006 `accio-ledger` |
| todo | S-007 `accio-brief` |
| todo | S-008 `accio-merge` |
| todo | S-009 `accio-cost` |
| todo | S-010 `accio-summary` |
| todo | S-011 Secret patterns and `pre-commit` |
| todo | S-012 `accio-hooks`: install, chain, verify, `pre-push` |
| todo | S-013 `protego` |
| todo | S-014 `fidelius` |
| todo | S-015 `boundary` |
| todo | S-016 `session-start` |
| todo | S-028 `doc-size` and `librarian` |
| todo | S-017 Build agents: `portkey`, `house-elf`, `prefect` |
| todo | S-018 Review agents and findings template |
| todo | S-019 `brew.js`: load, prepare, implement, check, outcome |
| todo | S-020 `brew.js`: review, judge, fix rounds, budgets |
| todo | S-021 `prophecy` skill |
| todo | S-022 `owl` skill |
| todo | S-023 `sort` skill and `quill` |
| todo | S-024 `wand` skill, `seeker`, `wandmaker` |
| todo | S-025 `map` and `vow` skills |
| todo | S-026 Skill evals and baseline cost |
| conditional | S-027 `brew-by-hand` (only if S-001 says so) |

---

### S-001 · Spike: workflow, named agents, worktree
Deps: — · Files: `spike/` (throwaway, deleted at the end), `docs/research/spike-s001.md`
Context: DESIGN § 10 "The first story is a spike"; decision 003.
- [ ] S-001/1 (no test) WHEN a plugin workflow calls accio's named agents THE SPIKE SHALL record whether it works, with the evidence
- [ ] S-001/2 (no test) WHEN a script creates a worktree THE SPIKE SHALL record whether a workflow agent can run inside it
- [ ] S-001/3 (no test) THE REPORT SHALL answer each check in DESIGN § 10: token usage from `agent()`, the opt-in and permission prompt, tool-permission prompts inside agents, `bin/` on PATH, `${CLAUDE_PLUGIN_ROOT}`, whether hooks fire inside agents, `CLAUDECODE=1` inside agents, behaviour with workflows disabled
- [ ] S-001/4 (no test) THE REPORT SHALL end with one verdict: go, fallback 1, or fallback 2 (`brew-by-hand`, S-027), and any DESIGN changes it implies

### S-002 · Scaffold, CI and publish
Deps: S-001 · Files: `.claude-plugin/plugin.json`, the layout folders, `.github/workflows/ci.yml`, `scripts/publish.sh`, `tests/test_scaffold.py`, `.gitignore`
Context: DESIGN § 4, § 9 (CI), § 11 (one source tree); decision 007 (marketplace).
- [ ] S-002/1 WHEN `claude plugin validate` runs on the repo THE SYSTEM SHALL pass
- [ ] S-002/2 WHEN CI runs THE SYSTEM SHALL run `python3 -m unittest` and `node --test tests/workflow` on macOS and Linux
- [ ] S-002/3 WHEN `scripts/publish.sh` runs THE SYSTEM SHALL copy the plugin into `~/Workspace/claude-plugins-release/accio` and refuse when the working tree is dirty
- [ ] S-002/4 (no test) `claude --plugin-dir .` loads the plugin with no errors

### S-003 · Shared library
Deps: S-002 · Files: `bin/accio_lib/{paths,config,story}.py`, `tests/test_lib.py`, `tests/fixtures/`
Context: DESIGN § 4.6 (git common dir), § 5.1, § 5.2, § 4.4 (silent exit outside accio repos).
- [ ] S-003/1 WHEN called from the main checkout or from a worktree outside the repo THE SYSTEM SHALL return the same main `.accio/` path
- [ ] S-003/2 WHEN the repo has no `.accio/` THE SYSTEM SHALL return none, without raising
- [ ] S-003/3 WHEN `config.json` lacks a key THE SYSTEM SHALL return the default from DESIGN § 5.2
- [ ] S-003/4 WHEN a story file is parsed THE SYSTEM SHALL return its frontmatter and its numbered DoD lines, including `(no test)` marks
- [ ] S-003/5 WHEN a story file has malformed frontmatter THE SYSTEM SHALL fail with the file name and the line

### S-004 · `accio-board`
Deps: S-003 · Files: `bin/accio-board`, `bin/accio_lib/board.py`, `tests/test_board.py`
Context: DESIGN § 3.3, § 3.4 (stacking), § 4.6, § 5, § 12.2.
- [ ] S-004/1 WHEN `new` runs THE SYSTEM SHALL return the next free `S-NNN` ID
- [ ] S-004/2 WHEN `move <ID> <status>` runs during a build THE SYSTEM SHALL write only `run/status.json`
- [ ] S-004/3 WHEN `ready --json` runs THE SYSTEM SHALL list Ready stories in dependency order, including a child whose parent is in the batch, up to `stack_depth`
- [ ] S-004/4 WHEN a story's parent is BLOCKED in the current run THE SYSTEM SHALL leave the child out of `ready`
- [ ] S-004/5 WHEN `board` runs THE SYSTEM SHALL regenerate `board.md` with the six columns and a Dropped line
- [ ] S-004/6 WHEN a story is `dropped` THE SYSTEM SHALL never list it as ready

### S-005 · `accio-score`
Deps: S-003 · Files: `bin/accio-score`, `bin/accio_lib/score.py`, `tests/test_score.py`
Context: DESIGN § 3.2; decision 002.
- [ ] S-005/1 WHEN a story touches a `risky_paths` glob THE SYSTEM SHALL return track `story` or higher, whatever its size
- [ ] S-005/2 WHEN the score is above the Story threshold THE SYSTEM SHALL return the split flag
- [ ] S-005/3 WHEN the score is computed THE SYSTEM SHALL print the files, risk and new-dependency parts it used

### S-006 · `accio-ledger`
Deps: S-003 · Files: `bin/accio-ledger`, `bin/accio_lib/ledger.py`, `tests/test_ledger.py`
Context: DESIGN § 12.4.
- [ ] S-006/1 WHEN the diff, the checks, the panel or the DoD changes THE SYSTEM SHALL produce a different key
- [ ] S-006/2 WHEN only the commit layout changes (same patch) THE SYSTEM SHALL produce the same key
- [ ] S-006/3 WHEN the story is a stacked child THE SYSTEM SHALL diff from the parent's head
- [ ] S-006/4 WHEN `check` finds a recorded pass for the key THE SYSTEM SHALL report a skip
- [ ] S-006/5 WHEN `clear <ID>` runs THE SYSTEM SHALL delete that story's entries

### S-007 · `accio-brief`
Deps: S-004 · Files: `bin/accio-brief`, `bin/accio_lib/brief.py`, `bin/accio_lib/templates/brief.md`, `tests/test_brief.py`
Context: DESIGN § 3.4 step 1, § 12.3.
- [ ] S-007/1 WHEN a story has no branch THE SYSTEM SHALL create `<wt>/<ID>` on `story/<ID>` from base, or from the parent's head when stacked
- [ ] S-007/2 WHEN the branch exists THE SYSTEM SHALL reuse it and rebase it on base or on the parent's current head
- [ ] S-007/3 WHEN the rebase conflicts THE SYSTEM SHALL write the conflict into the brief and not fail
- [ ] S-007/4 WHEN a brief is written THE SYSTEM SHALL include the DoD lines with IDs, the file boundary, the existing code to reuse, the checks to run, the scripts' absolute paths and any Review notes
- [ ] S-007/5 WHEN `--fix <findings>` runs THE SYSTEM SHALL write a short fix brief that lists only those findings

### S-008 · `accio-merge`
Deps: S-004, S-006 · Files: `bin/accio-merge`, `bin/accio_lib/merge.py`, `tests/test_merge.py`
Context: DESIGN § 3.5 Merge, § 12.3 steps 3–4, § 12.6; decision 009.
- [ ] S-008/1 WHEN stories are accepted THE SYSTEM SHALL merge them `--no-ff` in dependency order on `accio/integrate-<N>`, with messages `<type>(<ID>): <title>`
- [ ] S-008/2 WHEN the full checks pass THE SYSTEM SHALL fast-forward main and never reset it
- [ ] S-008/3 WHEN the full checks fail THE SYSTEM SHALL leave main unchanged and name the first story whose merge makes the failing checks fail
- [ ] S-008/4 WHEN main's checkout has uncommitted changes in the same files THE SYSTEM SHALL stop with one plain question
- [ ] S-008/5 WHEN the merge succeeds THE SYSTEM SHALL remove the worktrees and delete the branches with `git branch -d` only
- [ ] S-008/6 WHEN an `accio/integrate-<N>` branch is left by a crash THE SYSTEM SHALL delete and rebuild it

### S-009 · `accio-cost`
Deps: S-001, S-003 · Files: `bin/accio-cost`, `bin/accio_lib/cost.py`, `tests/test_cost.py`, `tests/fixtures/transcripts/`
Context: DESIGN § 8; the S-001 report (where usage is found).
- [ ] S-009/1 WHEN given a run's transcripts THE SYSTEM SHALL sum the tokens per story and per iteration
- [ ] S-009/2 WHEN a story exceeds its budget THE SYSTEM SHALL flag it, and flag 2× separately
- [ ] S-009/3 WHEN a transcript is missing or unreadable THE SYSTEM SHALL report "unknown" for that story, not zero

### S-010 · `accio-summary`
Deps: S-004, S-009 · Files: `bin/accio-summary`, `bin/accio_lib/summary.py`, `tests/test_summary.py`
Context: DESIGN § 3.5, § 7.2.
- [ ] S-010/1 WHEN a run ends THE SYSTEM SHALL write `run/owl.md` with, per READY story: what changed, how to try it, risks, token cost
- [ ] S-010/2 WHEN a story is BLOCKED THE SYSTEM SHALL include its one question
- [ ] S-010/3 WHEN a story has a stacked parent THE SYSTEM SHALL say that accepting it requires the parent
- [ ] S-010/4 WHEN the summary is written THE SYSTEM SHALL keep it within about 150 tokens per story

### S-011 · Secret patterns and `pre-commit`
Deps: S-003 · Files: `bin/accio_lib/secrets.py`, `tests/test_secrets.py`
Context: DESIGN § 6 (pattern list); `~/Workspace/claude-mods/secret-guard/hooks/patterns.ts`.
- [ ] S-011/1 WHEN text contains a Stripe, Google or AWS key THE SYSTEM SHALL report it
- [ ] S-011/2 WHEN a JWT's role is not `service_role` THE SYSTEM SHALL not report it
- [ ] S-011/3 WHEN a database URL's password is for a local host, or a value is a known example THE SYSTEM SHALL not report it
- [ ] S-011/4 WHEN a secret is reported THE SYSTEM SHALL show only a prefix
- [ ] S-011/5 WHEN gitleaks is installed THE SYSTEM SHALL use it for the staged scan, and the built-in patterns otherwise
- [ ] S-011/6 WHEN a test needs a fake key THE TEST SHALL build it at runtime by concatenation

### S-012 · `accio-hooks`: install, chain, verify, `pre-push`
Deps: S-011 · Files: `bin/accio-hooks`, `bin/accio_lib/githooks.py`, `tests/test_githooks.py`
Context: DESIGN § 4.5, § 12.1; decisions 004 and 009.
- [ ] S-012/1 WHEN the repo has no hook manager THE SYSTEM SHALL write the hooks, or append to hand-written ones under `# accio`
- [ ] S-012/2 WHEN husky is active THE SYSTEM SHALL append the `# accio` call to `.husky/<hook>` after the project's lines
- [ ] S-012/3 WHEN lefthook or the pre-commit framework is found THE SYSTEM SHALL edit nothing and print a copy-paste snippet
- [ ] S-012/4 WHEN `verify` runs THE SYSTEM SHALL report a missing marker, an inactive hooks folder, or a stale plugin path, and rewrite a stale path
- [ ] S-012/5 WHEN a push to base comes with `CLAUDECODE=1` and no valid token THE SYSTEM SHALL block it; WHEN `CLAUDECODE` is unset THE SYSTEM SHALL allow it
- [ ] S-012/6 WHEN the token matches the pushed sha THE SYSTEM SHALL allow one fast-forward push and delete the token
- [ ] S-012/7 WHEN anyone force-pushes THE SYSTEM SHALL block it
- [ ] S-012/8 WHEN `uninstall` runs THE SYSTEM SHALL remove only the marked lines
- [ ] S-012/9 WHEN `install` runs THE SYSTEM SHALL propose the § 12.1 allow rules and write them only after approval

### S-013 · `protego`
Deps: S-003 · Files: `hooks/protego.py`, `hooks/hooks.json`, `tests/test_protego.py`
Context: DESIGN § 4.4; decision 004.
- [ ] S-013/1 WHEN a Bash command is on the § 4.4 list THE SYSTEM SHALL exit 2 and name the safe alternative
- [ ] S-013/2 WHEN the command is `git branch -d` THE SYSTEM SHALL allow it
- [ ] S-013/3 WHEN the repo has no `.accio/` THE SYSTEM SHALL exit 0 silently
- [ ] S-013/4 WHEN dcg is installed THE SYSTEM SHALL defer to it

### S-014 · `fidelius`
Deps: S-011, S-013 · Files: `hooks/fidelius.py`, `hooks/hooks.json`, `tests/test_fidelius.py`
Context: DESIGN § 4.4, § 6.
- [ ] S-014/1 WHEN Write/Edit content holds a reported secret THE SYSTEM SHALL exit 2 without echoing the value
- [ ] S-014/2 WHEN the repo has no `.accio/` THE SYSTEM SHALL exit 0 silently

### S-015 · `boundary`
Deps: S-013 · Files: `hooks/boundary.py`, `hooks/hooks.json`, `tests/test_boundary.py`
Context: DESIGN § 4.4, § 6; decision 009.
- [ ] S-015/1 WHEN the session runs in an accio worktree and Write/Edit targets a path outside it THE SYSTEM SHALL exit 2 naming the allowed folder
- [ ] S-015/2 WHEN the target is `.accio/run/<ID>/` of that story THE SYSTEM SHALL allow it
- [ ] S-015/3 WHEN the session is not in an accio worktree THE SYSTEM SHALL exit 0 silently
- [ ] S-015/4 WHEN a path uses `..` or a symlink to leave the worktree THE SYSTEM SHALL resolve it and block

### S-016 · `session-start`
Deps: S-001 (how to detect workflows off), S-004 · Files: `hooks/session_start.py`, `hooks/hooks.json`, `tests/test_session_start.py`
Context: DESIGN § 4.4, § 10 (workflows off).
- [ ] S-016/1 WHEN the repo has `.accio/` THE SYSTEM SHALL inject at most 10 lines: board summary, next step, plain-words rule
- [ ] S-016/2 WHEN workflows are disabled THE SYSTEM SHALL say so and point to `/accio:brew-by-hand`
- [ ] S-016/3 WHEN the repo has no `.accio/` THE SYSTEM SHALL print nothing

### S-028 · `doc-size` and `librarian`
Deps: S-013 · Files: `hooks/doc_size.py`, `hooks/hooks.json`, `agents/librarian.md`, `tests/test_doc_size.py`
Context: DESIGN § 4.2, § 4.4; `analysis.md` § 2.3 (foreman's `doc-guard` and `doc-reader`). Built here, after
S-016, but numbered last because it was added later.
- [ ] S-028/1 WHEN Read targets a `.md` file over 40 KB with no offset or limit THE SYSTEM SHALL exit 2 and point to `librarian` or to reading by section
- [ ] S-028/2 WHEN the read has an offset or limit, or the file is 40 KB or less THE SYSTEM SHALL allow it
- [ ] S-028/3 WHEN the repo has no `.accio/` THE SYSTEM SHALL exit 0 silently
- [ ] S-028/4 (no test) `librarian` runs on Haiku with Read and Grep only, and returns quotes with `file:line`

### S-017 · Build agents: `portkey`, `house-elf`, `prefect`
Deps: S-007, S-006, S-015 · Files: `agents/{portkey,house-elf,prefect}.md`, `bin/accio_lib/checks.py`, `tests/test_checks.py`
Context: DESIGN § 3.4 steps 0–3 and 7, § 4.2, § 12.5.
- [ ] S-017/1 WHEN `prefect`'s check script runs THE SYSTEM SHALL run only the checks whose globs match the diff
- [ ] S-017/2 WHEN the diff touches a file outside the story's `files` (plus tests) THE SYSTEM SHALL list it in `out_of_bounds`
- [ ] S-017/3 WHEN a numbered DoD line not marked `(no test)` has no tagged test THE SYSTEM SHALL list it in `untagged`
- [ ] S-017/4 WHEN the main checkout's `git status` differs from the snapshot THE SYSTEM SHALL list the paths in `main_changed`
- [ ] S-017/5 (no test) each agent file sets the model from § 4.2, the tools from § 4.2 and the reply schema from § 12.5

### S-018 · Review agents and findings template
Deps: S-017 · Files: `agents/{examiner,professor,auror,headmaster}.md`, `agents/references/findings-template.md`, `tests/test_agents.py`
Context: DESIGN § 3.4 steps 4–5, § 7.1, § 12.5.
- [ ] S-018/1 WHEN an agent file is loaded THE TEST SHALL find its model, tools and reply schema as in § 4.2 and § 12.5
- [ ] S-018/2 (no test) the findings template holds severity, confidence, `file:line`, claim, failure scenario and DoD tag
- [ ] S-018/3 (no test) `examiner` checks the DoD line by line and judges only whether each tagged test checks its line
- [ ] S-018/4 (no test) each reviewer lists the false positives it ignores and the ≥ 80 confidence rule

### S-019 · `brew.js`: load, prepare, implement, check, outcome
Deps: S-001, S-017 · Files: `workflows/brew.js`, `tests/workflow/brew-core.test.mjs`, `tests/workflow/stub.mjs`
Context: DESIGN § 3.4, § 12.6; `docs/research/build-engine.md` "Option C in detail".
- [ ] S-019/1 WHEN more than 3 stories are ready THE SYSTEM SHALL keep at most 3 in progress
- [ ] S-019/2 WHEN an agent is silent past `stallMs` THE SYSTEM SHALL mark the story BLOCKED with a plain question
- [ ] S-019/3 WHEN a child's parent is not yet READY THE SYSTEM SHALL hold the child and give its slot to another story
- [ ] S-019/4 WHEN the parent ends BLOCKED THE SYSTEM SHALL not start the child
- [ ] S-019/5 WHEN the ledger reports a skip THE SYSTEM SHALL not re-run that step
- [ ] S-019/6 WHEN a story was left in *Doing* by a crash THE SYSTEM SHALL resume it at check or prepare as in § 12.6
- [ ] S-019/7 WHEN the run ends THE SYSTEM SHALL return the § 7.2 table only

### S-020 · `brew.js`: review, judge, fix rounds, budgets
Deps: S-018, S-019 · Files: `workflows/brew.js`, `tests/workflow/brew-review.test.mjs`
Context: DESIGN § 3.4 steps 4–6, § 7.1, § 8.6.
- [ ] S-020/1 WHEN findings remain after 2 fix rounds THE SYSTEM SHALL mark the story BLOCKED and never run a third
- [ ] S-020/2 WHEN a fix round runs THE SYSTEM SHALL re-run only the reviewers that raised findings, on the fix diff only
- [ ] S-020/3 WHEN a finding conflicts with the story, or an agent returns NEEDS_CONTEXT THE SYSTEM SHALL call `headmaster`
- [ ] S-020/4 WHEN `headmaster` returns a question THE SYSTEM SHALL write `run/questions/<ID>.md` and mark the story BLOCKED
- [ ] S-020/5 WHEN a story is on the Quick track THE SYSTEM SHALL use one combined reviewer; WHEN it touches a risky path THE SYSTEM SHALL add `auror`
- [ ] S-020/6 WHEN usage passes 2× the budget (or `maxTurns`, per S-001) THE SYSTEM SHALL stop the story as BLOCKED

### S-021 · `prophecy` skill
Deps: S-004, S-005 · Files: `skills/prophecy/SKILL.md`, `skills/prophecy/references/`, `evals/prophecy/`
Context: DESIGN § 3.3, § 7.3.
- [ ] S-021/1 (no test) proposes at most 8 eligible stories (deps done, or stacked within 2 levels), never a dropped one
- [ ] S-021/2 (no test) asks one question at a time in the `decisions.md` format and bundles low-stakes defaults
- [ ] S-021/3 (no test) asks about stories whose dependency was dropped
- [ ] S-021/4 (no test) on "go", moves the stories to Ready, writes `iterations/<N>.md`, commits, and tells the user to type `/accio:brew`
- [ ] S-021/5 (no test) SKILL.md is at most about 80 lines

### S-022 · `owl` skill
Deps: S-008, S-010, S-012 · Files: `skills/owl/SKILL.md`, `skills/owl/references/`, `evals/owl/`
Context: DESIGN § 3.5, § 7.2, § 7.3.
- [ ] S-022/1 (no test) reads only `run/owl.md` and takes one batch answer: accept, reject or drop per story; answers; push
- [ ] S-022/2 (no test) refuses to accept a child without its parent, in plain words
- [ ] S-022/3 (no test) on reject, writes the Review notes, clears the ledger, and sends the story and its children back to Ready
- [ ] S-022/4 (no test) on drop, sets `dropped` with the reason and removes the worktree
- [ ] S-022/5 (no test) runs `accio-merge`, writes the push token only after the user confirms, and makes one `chore(accio): iteration <N> review` commit
- [ ] S-022/6 (no test) runs `accio-hooks verify` and raises a missing marker as a question

### S-023 · `sort` skill and `quill`
Deps: S-005, S-018 · Files: `skills/sort/SKILL.md`, `agents/quill.md`, `evals/sort/`
Context: DESIGN § 3.2, § 5.1.
- [ ] S-023/1 (no test) `quill` writes story files in the § 5.1 format, with numbered EARS DoD lines and `(no test)` marks
- [ ] S-023/2 (no test) a story the score flags is split, and each child gets the next free ID
- [ ] S-023/3 (no test) `examiner` checks the backlog and its findings are fixed in the same run
- [ ] S-023/4 (no test) the main chat shows only the summary

### S-024 · `wand` skill, `seeker`, `wandmaker`
Deps: S-012, S-025 · Files: `skills/wand/SKILL.md`, `skills/wand/references/`, `agents/{seeker,wandmaker}.md`, `evals/wand/`
Context: DESIGN § 3.1, § 12.1.
- [ ] S-024/1 (no test) interviews one question at a time and deletes a requirement without an owner
- [ ] S-024/2 (no test) `seeker` returns `findings: <path>` and treats an undocumented capability as unavailable
- [ ] S-024/3 (no test) `wandmaker` returns 2–3 options with trade-offs and "what breaks first"
- [ ] S-024/4 (no test) writes `.accio/design.md`, records each decision with `vow`, and runs `accio-hooks install` on first use

### S-025 · `map` and `vow` skills
Deps: S-004, S-016 · Files: `skills/{map,vow}/SKILL.md`, `evals/{map,vow}/`
Context: DESIGN § 3.7.
- [ ] S-025/1 (no test) `map` shows the board from `accio-board` and points to `brew-by-hand` when workflows are off
- [ ] S-025/2 (no test) `vow` writes `.accio/decisions/NNN-<slug>.md` in the `decisions.md` format

### S-026 · Skill evals and baseline cost
Deps: S-021, S-022, S-023, S-024, S-025 · Files: `evals/`, `.github/workflows/ci.yml`
Context: DESIGN § 8.5, § 9.
- [ ] S-026/1 WHEN `claude plugin eval` runs THE SYSTEM SHALL use only free graders and `--max-cost-usd 2`
- [ ] S-026/2 WHEN each skill's trigger phrases are given THE EVAL SHALL show the right skill used
- [ ] S-026/3 (no test) `claude plugin details accio` shows about 2k tokens or less for all descriptions

### S-027 · `brew-by-hand` (conditional)
Deps: S-001 (verdict: fallback 2, or workflows are off for the user), S-020 · Files: `skills/brew-by-hand/SKILL.md`
Context: DESIGN § 10 Fallbacks.
- [ ] S-027/1 (no test) runs the § 3.4 steps as plain subagents with the same scripts, files and caps
- [ ] S-027/2 (no test) is suggested by `session-start` and `map` when workflows are off
