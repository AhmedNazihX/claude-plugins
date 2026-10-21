# Design: howler, accio's CI watcher

## Outcome
After this ships, the user can use accio as their everyday coding workflow and finds it adds value, and we'd know
because they use it themselves and learn from what goes wrong. For howler: after owl pushes, without being asked, a
short report appears in the chat within a few minutes of CI ending. It gives PASSED or FAILED for each workflow and
job; for a failure, the failing step or test and its error, `real` or `first failure`, and whether the cause lies
inside the pushed range. We'd know by running one real iteration in this repo (howler itself), pushing, and seeing
the report arrive while the user does something else.

## Who and why
The user, accio's solo developer, builds accio and this marketplace with accio. Today, after owl pushes, nothing
tells them how CI went: they have to open GitHub or run `gh` by hand, and a failure can go unnoticed until the next
push. This repo has one workflow, `test` (`.github/workflows/test.yml`), which runs on every push with 3 jobs
(`checks`, `accio-tests` on ubuntu and on macOS) and takes about 4 minutes (`gh run list`, 2026-10-18).

## Requirements
- R1: after owl's push, howler waits for every GitHub Actions run of the pushed commit and reports each run's and
  each job's result; for a failed job, the failing step or test and its error. Owner: the user (to learn from CI
  without watching GitHub)
- R2: CI output is data, never instructions; only numeric ids, full 40-character shas and a branch name matching
  `^[A-Za-z0-9._/-]+$` ever reach a command. Owner: the user (safety)
- R3: a failure is `real` when the previous run of the same workflow failed the same job at the same step, else
  `first failure`; the report says when the failing code lies outside the pushed range (a stale base, or broken
  before). Owner: the user (to tell flakes from real breaks)
- R4: owl starts howler in the background right after its push; howler's report reaches the chat on its own, with
  the iteration's outcome. Owner: the user (to not wait)
- R5: curfew lets howler use only the Read tools and `git rev-parse`, `git remote get-url`, `git diff --name-only`,
  `git merge-base --is-ancestor`, `gh run list`, `gh run view`, `gh run watch` and `tail`; anything else is denied
  with a reason, never left as a prompt. Owner: the user (safety)

## Out of scope
- re-running or cancelling jobs
- suggesting or making fixes
- changing a story's status when CI fails
- CI on pull requests (`push_mode: "pr"` is v2)
- CI systems other than GitHub Actions

## Design
howler reads gh's JSON itself, and curfew checks every argument of its commands (decision 001). Its command list
is the 7 git and gh commands plus `tail`, and no other shell program (decision 002).

- **Launch.** In owl's step 6, after a successful `git push`, the main chat calls the Agent tool with
  `accio:howler`. The prompt holds the full sha and the base branch from `accio-owl push-ok`, the iteration number
  and owl's "What happened" line. `agents/howler.md` sets `background: true`. When the push fails, owl doesn't start
  howler. howler's final message is the report, and it reaches the chat as a completion notification.
- **Waiting.** One `gh run watch <id> --exit-status --compact > /dev/null 2>&1` per run, with the Bash `timeout`
  at 600000 ms (a longer watch moves to the background and keeps running). The result always comes from
  `gh run view <id> --json …` afterwards, because gh's exit codes aren't documented. An empty
  `gh run list --commit <sha>` right after the push is retried a few times, within `maxTurns`. No `sleep` and no
  loops: curfew denies them.
- **Reading a failure.** `gh run view <id> --json jobs` for each run's jobs; for each failed job,
  `gh run view <id> --log-failed --job <job id> | tail -60`.
- **R3.** The previous run is the latest run of the same workflow on the base branch with a different `headSha`
  (`gh run list --workflow <workflowDatabaseId> --branch <base> --limit 5 --json …`). The workflow is named by its
  number id, never its name, which is CI text. "The same way" means the same job name and failing step name.
  `git merge-base --is-ancestor <prev> <sha>` false means a stale base; `git diff --name-only <prev> <sha>` gives
  the files the push changed, to compare with the failing test.
- **curfew.** A new Bash kind for howler in `policy.py` (`AGENTS["howler"]`, and its own branch in `_other_judge`,
  which today indexes `SCRIPTS[kind]`). Its `Judge.prefixes` are the 7 commands plus `tail`, and it checks every
  word after the prefix: a known flag, a JSON field from a fixed set, or a value matching `^\d+$`,
  `^[0-9a-f]{40}$` or the branch pattern. So `-R other/repo`, `git diff --output=<file>` and any free text are
  denied, and `git log`, `git push`, `gh run rerun` and `gh run cancel` are off the list. Not `read_only=True`.
  The other agents' lists don't change.
- **gh missing, logged out, or no GitHub remote.** howler says so in one line and stops.

## What we build
1. **curfew's list for howler.** Lets howler run exactly its commands with checked arguments (R2, R5), for the user.
   Files: `accio/bin/accio_lib/policy.py`, `accio/bin/accio_lib/bashpolicy.py` (an argument check for prefixes,
   which `Judge` has today only for accio scripts), `accio/tests/test_curfew.py`. Needs: none. Risk: a permission
   policy (security). Checked by: test_curfew.py rows. Allowed: `gh run list --commit <40 hex> --json …`,
   `gh run watch 123 --exit-status --compact > /dev/null 2>&1`, `gh run view 123 --log-failed --job 456 | tail -60`,
   `git merge-base --is-ancestor <sha> <sha>`. Denied, each with a reason: `gh run rerun 1`, `gh run cancel 1`,
   `gh run view 1 -R x/y`, `gh run view abc`, `git diff --name-only --output=f`, `git log`, `git push`, `sleep 5`,
   `cat x`, `GH_PAGER=cat gh run list`. The other agents' existing rows still pass.
2. **The `howler` agent.** Waits for the runs, reads them and writes the report (R1, R2, R3). Files:
   `accio/agents/howler.md` (`name: howler`, `model: haiku`, `tools: Read, Bash`, `background: true`, `maxTurns`,
   a description starting "The CI watcher (howler): …"), `accio/tests/test_agents.py`. Needs: 1. Risk: it reads
   untrusted CI text. Checked by: test_agents.py passes for howler.md; pointed at the past failed `test` run
   `39170577637` (commit `1101d22`), its failing job and step equal what `gh run view 39170577637 --json jobs`
   shows.
3. **owl starts howler after its push.** (R4) Files: `accio/skills/owl/SKILL.md` (step 6 and `allowed-tools` gets
   `Agent`; stays under about 80 lines), `accio/docs/DESIGN.md` (§ 3.5, § 4.2 agent table, § 4.4 curfew),
   `accio/docs/BACKLOG.md` (S-029's row). Needs: 1, 2, and the spike under Open questions. Risk: owl's push step.
   Checked by: one real iteration in this repo; after owl pushes, howler's report lists exactly the 3 jobs that
   `gh run view <id> --json jobs` lists for that run, with the same conclusions, and arrives without being asked.

## Evidence
Each item can be checked without a model:
- test_curfew.py's allowed and denied rows for howler (part 1), with the other agents' rows unchanged.
- test_agents.py passes for `agents/howler.md` (part 2).
- On the past failed run `39170577637`, howler's failing job and step equal `gh run view 39170577637 --json jobs`
  (part 2).
- On the real iteration, the report's jobs and conclusions equal `gh run view <id> --json jobs` for the pushed sha,
  and the report arrives in the chat on its own (part 3).

## Open questions
- **Spike S-029/0, by hand, before part 3 (a throwaway test; brew can't run it, since it needs the main chat):**
  1. Inside the owl skill, the main chat starts `accio:howler` (`background: true`), and its final message reaches
     the chat on its own while the user types something else. Note whether the Agent call prompts, with and without
     `Agent` in owl's `allowed-tools`.
  2. curfew sees `agent_type: accio:howler`.
  3. A howler Bash call over 600000 ms moves to the background, and howler carries on when told it ended, instead of
     stopping early with a "still waiting" message.
  4. The field shape of `gh run view <past id> --json jobs`.
  If step 1 fails, no option meets R4 as written, and the design comes back to the user.
- The 60-line log tail is what breaks first: with many failing tests, or both matrix jobs failing, the first error
  can fall outside it. Revisit if that happens.

## One command: /accio

### Outcome
After this ships, the user types one command (`/accio`) and accio carries the work from wherever the board stands to
a pushed, CI-checked result, stopping only at real decisions. We'd know because in one real iteration the transcript
has a single `/accio`, every other message from the user answers a real question, and no step ends with "type
/accio:X".

### Who and why
The user, accio's only user. Today every step ends by telling them which command to type next (wand → sort →
prophecy → brew → owl), so they have to remember the order and keep coming back. The workflow blocks on them.

### Requirements
- R1 One entry command, `/accio`, that reads the board and runs the next step. Owner: the user (no more remembering
  the order).
- R2 It keeps going through steps that need no decision: design → stories → plan → build → review → the next plan.
  Owner: the user ("I don't have to keep calling everything"; "try not to get blocked on me going forward").
- R3 It stops only where the decision is the user's (decision 004):
  - **the design:** wand's interview, one question at a time, as today
  - **a real open question** a story needs before it can be built (prophecy's step 4, items 1 and 2)
  - **a story that failed:** blocked with a question the conductor can't answer from the story, or rejected by review
  - **push and release**, paid calls, safety overrides, and commands curfew denied
  It does **not** stop for "go" (the plan's low-stakes defaults are taken and reported) or to accept a story that
  passed every check and review (it is accepted and merged into main locally, and reported). Typing `/accio` is the
  user's opt-in to every build it starts. Owner: the user (keeps the safety model's hard stops, DESIGN § 7.3).
- R4 One copy of the "what's next" rule. Today it's written twice: in `accio/hooks/session_start.py:42-63` and in
  `accio/skills/map/SKILL.md:20-26`. Owner: the user as accio's maintainer (a third copy would drift).

### Out of scope
- Several features at once, or parallel chats driving the same board.
- Pushing without the user's confirm. The push token stays.
- pensieve (the retro step).
- Changing how the build works inside (`workflows/brew.js`).
- Watching GitHub CI after the push: howler does that (the howler design above, S-001 and S-002). `/accio` will start
  howler once it exists.

### Design
**A conductor skill** (decision 003). A skill with `name: accio`, typed `/accio` (`/accio:accio` if the bare name is
taken). It runs `accio-board next --json`, which says the next step and whether it needs the user
(`auto: true|false`). It then runs that step's skill in the same chat, and repeats while `auto` is true. It stops
when a step asks the user something, and carries on after they answer. Python decides "continue or stop"; the skill
text only follows it. The single commands (`/accio:wand`, `/accio:brew` …) keep working as now.

**wand keeps its interview.** The design step still asks one question at a time (decision 009); `/accio` just runs
it and carries on to the stories when the design is committed.

**Two things aren't documented, so each gets a spike** (a short hands-on test) before we rely on it:
- **S1:** can a skill start the build (the `Workflow` tool, `accio:brew`) when the plan is recorded, with `/accio`
  as the opt-in? If not, the plan's message says "type `/accio:brew`": one typed command per iteration.
- **The wake (S2, S3 or S5):** does the chat continue by itself when the build ends? S2 tests the build's own report,
  S3 an `asyncRewake` hook that exits 2 when `run/brew.lock` is free, S5 one long blocking wait call. If none works,
  the user types `/accio` after the build, and it picks up at the review.

Each fallback costs the user one typed command, never a skipped safety check.

### What we build
1. **One "what's next" rule.** Move `next_step()` into `accio/bin/accio_lib/nextstep.py` and add
   `accio-board next [--json]`, which returns the step (`wand`, `sort`, `prophecy`, `brew`, `owl`, `wait`, `done`),
   `auto`, and today's plain sentence. `session_start.py` imports it, and `map` runs it instead of its prose copy.
   Files: `accio/bin/accio_lib/nextstep.py`, `accio/bin/accio-board`, `accio/hooks/session_start.py`,
   `accio/skills/map/SKILL.md`, tests. Needs: none. Risk: none.
   Checked by: a unittest feeds every board state (lock held, doing, review, blocked, ready, backlog, no design, no
   stories, all done) and checks `step` and `auto`; a test fails if the rule list is still in `map` or the hook.
2. **Spikes S1 and the wake (S2, S3, S5), by hand.** Results go in Review notes and decide parts 3 and 4. Files: none
   (notes only). Needs: none. Risk: none.
   Checked by: S1 passes when `run/brew.lock` and the run's `journal.jsonl` appear after the plan is recorded, with
   no message from the user; a wake spike passes when owl starts with no message from the user.
3. **The `/accio` conductor skill.** About 40 lines. Files: `accio/skills/accio/SKILL.md`, `accio/tests/` checks.
   Needs: 1, 2. Risk: none.
   Checked by: an eval in a fixture repo with a design and no stories shows `/accio` runs `accio-board next`, then
   `accio-board new` (tool order); no reply matches `type /accio:(wand|sort|prophecy|owl)`.
4. **Step endings.** When `/accio` is driving, each step ends with "next: <step> (accio carries on)"; run alone, it
   keeps "/accio:X". Files: `accio/skills/{wand,sort,prophecy,owl}/SKILL.md`. Needs: 3. Risk: none.
   Checked by: the part 3 eval's no-"type /accio:X" check.
5. **Fewer stops (decision 004).** When `/accio` is driving: prophecy records the plan without asking "go" when no
   story needs a real decision (dropped deps or an unclear DoD), taking and reporting the low-stakes defaults; owl
   accepts every READY story (it passed its checks and reviews), merges it locally, and asks only about blocked
   stories it can't answer, and the push. `accio-board next` gives `auto: true` for prophecy and owl in those cases.
   Run alone, both skills keep today's stops. Files: `accio/skills/{prophecy,owl}/SKILL.md`,
   `accio/bin/accio_lib/nextstep.py`, tests. Needs: 1, 3. Risk: none.
   Checked by: unittests on `accio-board next` (a plan with no open question and a review with only READY stories
   give `auto: true`; a dropped dep or a BLOCKED story gives `auto: false`); an eval where `/accio` with one READY
   story runs `accio-merge` without a user message (tool order).
6. **Docs.** DESIGN.md §§ 3, 4.1 and 7.3 (the new touchpoint count), the README's quick start, and BACKLOG. Files:
   `accio/docs/DESIGN.md`, `accio/README.md`, `accio/docs/BACKLOG.md`. Needs: 3, 4, 5. Risk: none.
   Checked by: by hand, § 7.3 matches the stops in R3.

### Evidence
- The `accio-board next` unittest over every board state.
- The `/accio` eval (tool order, and no "type /accio:X").
- One real iteration in this repo: a single `/accio` in the transcript, and every other message from the user is an
  answer to a real question.

### Open questions
- S1 and the wake spikes (part 2). Their results may add one typed command each.
- After compaction only the first 5,000 tokens of each skill survive. One long chat may lose the conductor's text
  after an iteration or two; a new `/accio` recovers, because it re-reads the board.

## Lessons from iteration 1

### Outcome
After this ships, a build in a new or freshly set-up repo can't silently skip its tests, a rebuilt story never hands
back its old unreviewed work as done, and a direct fix to accio gets accio's own reviewers. We'd know because the next
iteration has no stop caused by any of these three, and a direct fix's review comes from `accio-brief --review`
instead of a hand-written package.

### Who and why
The user, building accio with accio. Iteration 1's first story (S-001) needed four builds; three of the causes were
gaps in accio, not in the story:
- `.accio/config.json` had no `checks`, so the checker ran nothing and curfew refused the builder's own test run; it
  handed in code it had never run.
- On a rebuild, the builder found its earlier commit on `story/S-001`, saw its tests pass, and handed it back unchanged.
- Fixes to accio made outside a story (snapshot_skip, the brief's Context, `.DS_Store`) needed review packages written
  by hand so professor and auror could review them.

### Requirements
- R1 A build refuses to start when no `checks` are set, and says in plain words how to add them. Owner: the user (a
  build with no checks looks green but proves nothing).
- R2 setup (`wand`'s first run) proposes the check commands from the repo (CI workflow, package scripts, test folders)
  and writes them into `config.json`. Owner: the user (so R1 never stops a first build).
- R3 When a story's branch already holds commits from an earlier build, the brief says so plainly: they were not
  accepted, and why (the review notes or the answered question). Owner: the user (no more rebuilds that change
  nothing).
- R4 `accio-brief --review` can make a review package for a branch that is not a story (a direct fix), given a short
  acceptance list, so professor, auror and examiner review it as they would a story. Owner: the user as accio's
  maintainer.
- R5 brew honours `wip` from `config.json` (DESIGN § 5.2); today `workflows/brew.js` fixes it at 3. Owner: the user
  (iteration 2 set `wip: 1` and still built 3 at once).
- R6 The main snapshot forgives another story's `run/<ID>/base` only when accio's own prepare step wrote it during
  the run, not any change to it (accio 0.1.5 forgives every change; the push security review flagged it). Owner: the
  user (keeps the tamper check whole with parallel builds).

### Out of scope
- Changing which checks run inside a build, or their time budget.
- Reviewing changes that never reach a branch.

### Design
- **R1** in `accio-board ready` (the brew load step) and `prophecy`'s go: no `checks` → a plain refusal naming
  `config.json` and an example entry.
- **R2** in `wand`'s setup step: a small script reads `.github/workflows/*.yml` `run:` lines, `package.json` scripts and
  common test commands, proposes them, and wand writes the ones the user keeps.
- **R3** in `accio-brief`: when `story/<ID>` has commits past its recorded base, add a "## Your earlier work" section
  listing them, saying they were not accepted, with the review notes and answered question beside it.
- **R4** in `accio-brief --review --fix-branch <branch> --acceptance <file>`: the same review-package template with the
  acceptance list in place of the DoD.

### What we build
1. **No build without checks.** Files: `accio/bin/accio_lib/plan.py` or the `ready` path, `accio/skills/prophecy/SKILL.md`,
   tests. Needs: none. Risk: none. Checked by: a unittest where `ready` with empty `checks` exits with the plain
   message and changes nothing.
2. **Setup proposes checks.** Files: a new `accio/bin/accio_lib/checkfinder.py`, `accio/skills/wand/SKILL.md`, tests.
   Needs: 1. Risk: none. Checked by: unittests on fixture repos (a GitHub workflow, a package.json, a pytest folder)
   that give the expected check list.
3. **The brief names earlier work.** Files: `accio/bin/accio_lib/brief.py`, `accio/bin/accio_lib/templates/brief.md`,
   tests. Needs: none. Risk: none. Checked by: a unittest where a story branch with one old commit gets a brief with
   "## Your earlier work" naming that commit and saying it was not accepted.
4. **Review packages for direct fixes.** Files: `accio/bin/accio_lib/review.py`, `accio/bin/accio-brief`, the
   review-package template, tests. Needs: none. Risk: none. Checked by: a unittest that builds a package for a
   non-story branch with an acceptance file and checks it holds the diff path, the acceptance list and the findings
   paths.
5. **brew honours wip.** The load step (`accio-board ready --json`) returns `wip` from config, and `brew.js` uses it
   instead of its fixed `WIP = 3`. Files: `accio/bin/accio-board`, `accio/workflows/brew.js`, `accio/tests/test_board.py`,
   `accio/tests/workflow/brew-core.test.mjs`. Needs: none. Risk: none. Checked by: a unittest that `ready --json`
   gives the config's `wip` (3 when unset), and a workflow test where `wip: 1` never has two stories in progress.
6. **Only accio's own base writes are forgiven.** `accio-brief` appends each `run/<ID>/base` it writes to a log in
   `.accio/run/` (watched by the snapshot itself); `checks.compare` forgives another story's base change only when
   the log holds that write with the same content. Files: `accio/bin/accio_lib/brief.py`,
   `accio/bin/accio_lib/checks.py`, `accio/tests/test_checks.py`, `accio/tests/test_brief.py`. Needs: none.
   Risk: security (a tamper check). Checked by: unittests where another story's base written by `accio-brief`
   doesn't count, the same file written by hand does, and an edited log counts as a change.

### Evidence
- The unittests above.
- The next iteration's builds: no stop from empty checks, no unchanged rebuild, and the next direct fix reviewed from a
  generated package.

### Open questions
none

## Fixes from the 2026-10-20 audit

### Outcome
After this ships, every instruction accio hands a model matches what accio's guards and scripts allow, a step skill
knows for certain whether `/accio` called it, and the iteration records keep every outcome. We'd know because no
story in the next two iterations is blocked by a fix round touching files outside its story, a rebase the builder
can't run, or a command curfew denies that its instructions told it to use; and `claude plugin details accio`
measures accio's descriptions at 2,000 tokens or fewer.

### Who and why
The user, building accio with accio and running `/accio` in their repos. Three research notes (2026-10-20) found
where the words given to models and the code disagree:
- `accio/docs/research/prompt-audit.md`: findings 1–9 of its top 10.
- `accio/docs/research/improvements.md`: items 3, 4, 11 and 12.
- The rest (fewer stops for failed checks, a log of why findings and blocks ended, boggart the breaker) needs a
  design and comes in the next note.

### Requirements
- R1 A fix round's builder gets its story's limits: the story brief (with the Definition of Done), the files it may
  change and the checks to run. Owner: the user (today a fix can touch a file outside the story and block it;
  `templates/fix-brief.md` has none of these).
- R2 The builder is never told to run a git command curfew denies. A rebase on a re-run is started by `accio-brief`;
  a conflict is left in progress for house-elf to resolve and `git rebase --continue` (decision 005). Owner: the user
  (DESIGN § 12.3 promises house-elf resolves conflicts; curfew allows only `--continue`, `--abort`, `--skip`).
- R3 house-elf's instructions say which commands it may run, and why `$(…)`, backticks and heredocs are denied; the
  brief lists only the two scripts it may run. Owner: the user (each denied guess costs a turn out of 150).
- R4 Only the workflow's last step releases the run lock, and prefect's outcome step knows how to get the ledger key.
  Owner: the user (a portkey call that fails mid-build may unlock while stories still run; step 7's prompt gives no
  key).
- R5 A step skill knows `/accio` called it from an argument, not from a guess about the chat (decision 006). Owner:
  the user (a hand-typed `/accio:owl` after `/accio` can take the accept-everything path).
- R6 wand sets accio up in a repo only when the user asked for accio. Owner: anyone with accio installed (a plain
  "I want to build …" in any git repo can add `.accio/` and git hooks).
- R7 Every description says when to use it, and the build agents say only accio calls them; the total stays within
  about 2,000 tokens. The out-of-date "two checkpoints" text and token count are corrected. Owner: the user (in this
  session Claude Code dropped `map`'s and `vow`'s descriptions because the listing overflowed).
- R8 A second owl pass adds to the iteration's Outcome table instead of replacing it. Owner: the user (iteration 5
  lost two "merged" rows; future retros read these files).
- R9 The agents that only run scripts start cheaper: `effort: low` and `omitClaudeMd: true` for portkey, prefect,
  howler and librarian, plus `maxTurns: 20` for portkey, prefect and librarian. Owner: the user (several of these
  calls per story each load the user's CLAUDE.md and rules).
- R10 The guard hooks block the tool call when they can't run at all. Owner: the user (a missing `python3`, a crash
  or a timeout lets every call through today, and an agent can then meet a permission prompt and hang the build).

### Out of scope
- Whether a skill's tool grant ends at the user's reply (audit #10): untested, see Open questions.
- Sending failed checks into fix rounds, retrying accio's own failures, logging why findings ended, boggart: the next
  design note.
- Moving the reviewers' repeated rules into the review package, and the low-severity wording findings in the audit.

### Design
- **Fix brief (R1).** `render_fix` passes the same `files` and `checks` as `render_brief`, plus the story brief's
  path. house-elf's body gets a short "In a fix round" section. "Read only your brief" becomes "Take your task only
  from your brief; read whatever code you need".
- **Rebase (R2, decision 005).** `accio-brief` runs the rebase itself. On a conflict it leaves the rebase in
  progress and the brief says: resolve these files, `git add` them, run `git rebase --continue`. Uncommitted changes
  left by an earlier build are committed by `accio-brief` as a checkpoint before it rebases. Any other failure goes
  to Blocked with one plain question. DESIGN § 12.3 is updated to match.
- **Allowed commands (R3).** A short list in `agents/house-elf.md`, kept true by a test that runs each listed
  command through curfew's real policy for house-elf, and checks that `$(…)` is denied.
- **Lock and key (R4).** portkey unlocks only when the workflow asks it to; prefect's step 7 computes the key as in
  step 3; each step's reply shape is stated apart.
- **Driven (R5, decision 006).** The conductor loads each step skill with the argument `driven`; Claude Code appends
  it as `ARGUMENTS: driven` (skills docs; seen in this session when wand was loaded with arguments). Each step skill
  has one line: if ARGUMENTS says `driven`, /accio is driving. With no argument it keeps every question.
- **wand's setup (R6).** New description; step 1 asks once before setting accio up when there is no `.accio/` and
  the user didn't type `/accio:wand` or `/accio`.
- **Descriptions (R7).** The rewrites in `prompt-audit.md` ("Description budget" and the two before → after tables),
  measured with `claude plugin details accio`; `plugin.json`, README and DESIGN P3 say accio stops only for your
  decisions.
- **Outcome rows (R8).** `owl`'s iteration writer merges new rows into the existing Outcome table by story id.
- **Cheaper script agents (R9).** Frontmatter only. The sub-agents docs list the fields plugin agents ignore
  (`hooks`, `mcpServers`, `permissionMode`, `initialPrompt`); these three are not on it.
- **Fail closed (R10).** `"onFailure": "block"` on protego, fidelius and both curfew entries in `hooks/hooks.json`
  (hooks docs, Claude Code 2.1.295 and later). Not on `doc_size` or `session_start`: if they fail, work should go on.

### What we build
1. **Fix rounds keep the story's limits.** Files: `accio/bin/accio_lib/templates/fix-brief.md`,
   `accio/bin/accio_lib/brief.py`, `accio/bin/accio_lib/templates/brief.md`, `accio/agents/house-elf.md`,
   `accio/tests/test_brief.py`, `accio/tests/test_agents.py`. Needs: none. Risk: none. Checked by: a unittest that a
   fix brief holds the story brief's path, its files and its checks; a test that house-elf's body has the fix-round
   section.
2. **A rebase the builder can finish.** Files: `accio/bin/accio_lib/brief.py`, `accio/tests/test_brief.py`,
   `accio/docs/DESIGN.md`. Needs: 1 (same files). Risk: none. Checked by: unittests on a temporary repo: a re-run
   with a conflicting base leaves the rebase in progress and the brief names the files and `git rebase --continue`;
   uncommitted changes become a checkpoint commit before the rebase; no brief text names a `git rebase` command that
   curfew's policy denies for house-elf.
3. **The builder knows its commands.** Files: `accio/agents/house-elf.md`, `accio/bin/accio_lib/templates/brief.md`,
   `accio/tests/test_agents.py`. Needs: 1 (same files). Risk: none. Checked by: a test that runs each command in
   house-elf's list through `bashpolicy` as house-elf and expects it allowed, and `$(…)` denied; a test that the brief
   lists exactly `accio-claim` and `accio-board refresh`.
4. **Script agents: right steps, cheaper.** Files: `accio/agents/portkey.md`, `accio/agents/prefect.md`,
   `accio/agents/howler.md`, `accio/agents/librarian.md`, `accio/workflows/brew.js`, `accio/tests/test_agents.py`,
   `accio/tests/workflow/*.test.mjs`. Needs: none. Risk: none. Checked by: tests that portkey's body ties unlock to
   the workflow's request only, that prefect's step 7 and brew's step 7 prompt say to compute the key, and that the
   four agents' frontmatter has the new fields; `claude plugin validate accio` passes.
5. **/accio passes driven.** Files: `accio/skills/accio/SKILL.md`, `accio/skills/owl/SKILL.md`,
   `accio/skills/prophecy/SKILL.md`, `accio/skills/sort/SKILL.md`, `accio/skills/wand/SKILL.md`,
   `accio/tests/test_accio_skill.py`, `accio/tests/test_step_endings.py`. Needs: none. Risk: none. Checked by: tests
   that the conductor loads each step with `driven` and each step skill keys its driving line on `ARGUMENTS` and no
   longer on "loaded earlier in this chat".
6. **Descriptions that route right, and wand asks first.** Files: every `accio/agents/*.md` and
   `accio/skills/*/SKILL.md` frontmatter, `accio/skills/wand/SKILL.md` step 1, `accio/.claude-plugin/plugin.json`,
   `accio/README.md`, `accio/docs/DESIGN.md` (P3), `accio/evals/README.md`, `accio/tests/test_agents.py`,
   `accio/tests/test_readme.py`, `accio/tests/test_wand.py`. Needs: 4 and 5 (same files). Risk: none. Checked by: a
   test that each build agent's description says only accio calls it; a test that wand's step 1 asks before setup
   with no `.accio/`; `claude plugin details accio` at 2,000 tokens or fewer, noted in the build report (no test).
7. **owl keeps every outcome.** Files: `accio/bin/accio_lib/owl.py`, `accio/tests/test_owl.py`. Needs: none. Risk:
   none. Checked by: a unittest where a second owl pass on the same iteration keeps the first pass's rows and adds
   its own.
8. **Guards fail closed.** Files: `accio/hooks/hooks.json`, `accio/tests/test_scaffold.py` (or the hooks test).
   Needs: none. Risk: security (the guards). Checked by: a test that protego, fidelius and both curfew entries carry
   `"onFailure": "block"` and doc_size and session_start don't; `claude plugin validate accio` passes; a by-hand
   check that a broken curfew path blocks a tool call in a plugin (no test, see Open questions).

### Evidence
- The unittests and workflow tests above, and `claude plugin validate accio`.
- `claude plugin details accio`: descriptions at 2,000 tokens or fewer.
- The next two iterations: no block from a fix round outside its files, a rebase the builder can't run, or a denied
  command its instructions named; `.accio/iterations/<N>.md` keeps every outcome row.

### Open questions
- Does `onFailure: "block"` work in a plugin's `hooks/hooks.json`? The hooks docs don't say either way. A by-hand
  check in part 8 settles it; if it doesn't work, the field is harmless and the part says so.
- Does a skill's tool grant end at the user's reply (audit #10)? One owl run without `--allow-tools` would tell.
  Left for later.

## Guards fail open (decision 007)

### Outcome
After this ships, a guard that can't start never blocks a tool call outside accio's build agents, while an accio
agent still gets a deny when curfew crashes at start-up. We'd know because a test runs curfew with its library made
unimportable and sees a deny for an `accio:*` caller and a silent exit 0 for anyone else, and `hooks/hooks.json` has
no `onFailure`.

### Who and why
The user, who has accio installed for their whole account. S-028 gave protego, fidelius and curfew
`"onFailure": "block"`. Those guards run in every session and project, so one start-up crash (a broken update that
makes `from accio_lib import …` fail) would block every tool call everywhere and deny every permission prompt.
0.6.0 is installed but not restarted into; this ships as 0.6.1 first.

### Requirements
- R1 `hooks/hooks.json` has no `onFailure` on any hook. Owner: the user (a broken guard must not freeze Claude in
  every project).
- R2 curfew loads accio's library inside a guard: if loading fails, it reads the hook input with the standard
  library only, answers `deny` (naming the error) when `agent_type` starts with `accio:` on `PreToolUse`, and exits 0
  with no output for any other caller or event. Owner: the user (keeps what S-028 was for: an accio agent never
  waits on a permission prompt because curfew crashed).

### Out of scope
- A missing `python3` or a guard past its time limit: the call goes through, as before S-028 (decision 007).
- protego and fidelius start-up crashes: they fail open, as before S-028.

### Design
`curfew.py` keeps its stdlib imports at the top and moves `from accio_lib import …` into a function that returns the
modules or the error. `main` reads stdin first; on a load error it answers as R2 says, using the same JSON shape as
`_answer`. `hooks.json` drops the four `onFailure` fields. The S-028 test in `test_scaffold.py` changes to expect no
`onFailure` anywhere.

### What we build
1. **Guards fail open; curfew catches its own start-up crash.** Files: `accio/hooks/hooks.json`,
   `accio/hooks/curfew.py`, `accio/tests/test_scaffold.py`, `accio/tests/test_curfew.py`. Needs: none. Risk:
   security (a guard). Checked by: a test that no hook in `hooks.json` has `onFailure`; tests that run `curfew.py` as
   a subprocess with `accio_lib` made unimportable (for example a copy of the hooks folder with no `bin/` beside it)
   and expect a deny for an `accio:house-elf` `PreToolUse` call, and exit 0 with no output for a main-chat call and
   for a `PermissionRequest`.

### Evidence
- The tests above, and `claude plugin validate accio`.
- By hand before the restart: copy the plugin, break curfew's import, and run one `PreToolUse` input through it for
  a main-chat caller (passes) and an accio agent (denied).

### Open questions
none

## Group B: fewer stops, a reason for every ending

### Outcome
After this ships, a build stops for the user only for a real decision, and every finding, block and break leaves a
reason. We'd know because over the next two iterations no story blocks with "Should it be fixed and built again?" or
on a one-off accio hiccup; each `.accio/iterations/<N>.md` has one line per finding and block saying how it ended;
every boggart break that reached a fix round came with a repro that failed twice on head; owl reports a cost for
every build; and the guard and allow-list tests pass.

### Who and why
The user, building accio with accio and running `/accio` in their repos. The 2026-10-20 audit
(`accio/docs/research/improvements.md`, `breaker.md`) found that most stops are not real decisions, that nobody
records why a finding or block ended, and that nothing tries the feature with inputs the DoD never named.

### Requirements
- R1 A failed check (a failing command, an untagged DoD line, a weak test, an out-of-bounds file) goes into a fix
  round with the command's output, instead of asking. Owner: the user (every answer on record was "yes, build
  again"; 7 of 20 stories blocked at least once).
- R2 accio's own failures (portkey, prefect, a reviewer or headmaster gives no answer or an error) are retried once;
  `evals/`, `eval/`, `__mocks__/` and `__fixtures__/` folders count as the story's test area. Owner: the user (5 of 7
  early blocks were accio's fault).
- R3 Each finding and block records how it ended (fixed in round N, dismissed with headmaster's ruling, open, or
  blocked because of the code, accio or a decision) in the iteration file. Owner: the user (the reviewers'
  false-positive rate and the budgets are guesses; rulings are never saved).
- R4 boggart tries to break each reviewed code story. A script keeps a break only when its repro fails twice on head,
  on an assertion or a crash in a changed file, not on a setup error, and quotes a written claim. An in-DoD break goes
  to the fix round; an out-of-DoD break becomes an owl line. Owner: the user (named it; nothing checks inputs the
  DoD never named).
- R5 protego and fidelius catch their own start-up crash: deny an `accio:*` agent, let every other caller through.
  Owner: the user (0.6.1 push security review; decision 007 keeps fail-open).
- R6 owl's cost counts a build started while the session sat in a subfolder of the repo. Owner: the user
  (iteration 9 showed "cost unknown").
- R7 `agent_allow` entries match the whole command (decision 010). Owner: the user (the 2026-10-20 commit review: a
  builder could append arguments to the two `claude` entries).
- R8 mad-eye checks a UI story's visible DoD lines in the running app, driving it through the user's Playwright MCP
  server, and saves a screenshot per line as evidence; it never edits, and its findings go to the fix round. curfew
  lets only mad-eye use those browser tools, and only on the preview's address. Owner: the user (named it; layout
  and looks aren't checked today).
- R9 mad-eye's clicks never reach real data: the preview runs only when the user has written a preview command that
  uses test data and test keys, and said so in config; mad-eye logs in only with a test account whose details come
  from environment variables, never from config.json or the story. Owner: the user (a side-agent review on
  2026-10-20: a "save", "delete" or "send" click in a preview wired to the real database or services would really
  happen).

### Out of scope
- Retrying a stalled builder (decision 011; spike S-R1 under Open questions).
- mad-eye in a repo without the Playwright MCP server: a logged skip, not a fallback (decision 008).
- accio shipping its own browser server.
- accio checking that a preview really uses test data (it can't; `test_data` is the user's word, R9).
- pensieve retro, batching small stories, re-scoring ceremony from the diff, a goal check, the Stop-hook conductor
  (improvements #7–#10).

### Design
Option C: staged, with a live browser for mad-eye (decision 008).
- **Check failures become findings (R1, decision 009).** `checks.run` keeps each failing command's output (today
  `_run_within_budget` returns it and `run` drops it, `checks.py:317-350`). `accio-check` writes
  `run/<ID>/check-findings.md` in the findings format: ids `check-1…`, one per failing command (last 2,000
  characters of output), untagged line, weak test and out-of-bounds file. A script writes it, so no agent gets a new
  write. `checkStop` in `brew.js` sends these to `fixRound`; the re-check marks earlier ids `resolved` or `open`. Check
  and review fixes share `MAX_FIX_ROUNDS = 2`.
- **Retry once (R2).** A null or `{error}` reply from portkey, prefect, a reviewer or headmaster is retried once,
  labelled `<ID> <step> retry` so `accio-cost` still ties it to the story. A second failure blocks with cause
  `accio`. `TEST_FOLDERS` (`checks.py:49`) gains `evals`, `eval`, `__mocks__`, `__fixtures__`.
- **Every ending logged (R3).** `stop()` carries a cause (`code`, `accio` or `decision`), written as the question
  file's first line. headmaster's reply gains `dismisses: [ids]` and it writes `run/<ID>/ruling-r<N>.md`.
  `accio-brief --fix` copies the findings it reads into `run/<ID>/fix-<N>/`. owl's script compares them with the last
  files and writes `## Findings and blocks` in `iterations/<N>.md` before deleting the question files. Lines look like
  `S-031 examiner-2 major: fixed in round 1` or `S-031 blocked (accio): prefect gave no answer twice`. No model tokens.
- **boggart (R4).** A new Sonnet agent with `breaker.md`'s checklist: read the claims, list 3–6 risks, at most 3
  charters and about 5 properties, judge only by a written claim, never edit. It reads the review package (story, DoD,
  diff), not house-elf's report. It writes repros to `run/<ID>/boggart/` and may run `accio-break <ID> try <file>`.
  prefect runs `accio-break <ID> verify`, so boggart never grades itself. The runner copies each repro into a
  throwaway worktree at head (and base) and runs a new config command `breaker: {"command": "… {file}"}`. Kept: fails
  twice on head, on an assertion or a crash in a changed file, no setup-error marker, a claim quoted with its source.
  Passes on base and fails on head = regression; fails on base too = pre-existing, out of scope. Skipped (and logged)
  with no `breaker` config or on a diff with no code (a `code` flag next to `risky` in the review package). After a
  fix round, `verify` reruns the kept repros; a pass is the "fixed" evidence.
- **Guards' start-up crash (R5).** A stdlib-only `hooks/_startup.py` holds curfew's crash code; curfew, protego and
  fidelius import it before `accio_lib`. protego and fidelius deny in their own style (stderr and exit 2).
  `hooks.json` keeps no `onFailure` (decision 007).
- **Cost from a subfolder (R6).** `runs.py` scans the transcript folders of the repo root's slug and its subfolders'
  slugs, and counts a run whose `cwd` is inside the root.
- **Exact allow-list (R7, decision 010).** `_is_listed` compares the whole word list for `agent_allow` and allow-once
  entries; listed checks keep their prefix match. `bashpolicy.py:13` and `BACKLOG.md:300` say so.
- **mad-eye (R8, decision 008).** After S-M2 and S-M3 pass. portkey runs `accio-preview <ID> start`: it starts the
  config's `preview: {command, url}` in the story's worktree as a detached process, records its pid in
  `run/<ID>/preview.json`, and waits for the URL; one preview at a time through `run/preview.lock`. mad-eye, a new
  Sonnet agent, opens the URL with the browser tools, walks each visible DoD line (clicking and typing as the line
  needs), saves one screenshot per line to `run/<ID>/mad-eye/`, and writes `mad-eye-findings.md`. portkey then runs
  `accio-preview <ID> stop`, which kills the process group and frees the port; the workflow also calls stop when
  mad-eye fails, so no server outlives the step. curfew allows mad-eye only the browser tools on a fixed list
  (navigate, snapshot, click, type, fill form, select, hover, press key, wait, screenshot, resize, console messages,
  close), under the prefix in `preview.mcp_prefix` (default `mcp__plugin_playwright_playwright__`). It denies
  `navigate` to any address outside the preview's origin, a screenshot path outside `run/<ID>/mad-eye/`, and every
  other browser tool (`evaluate`, `run_code_unsafe`, `file_upload` …); every other agent keeps no MCP tools. mad-eye
  runs only when the diff touches `ui_globs`; with no `preview`, or no browser tools in the session, a logged skip.
- **Test data only (R9).** accio never guesses a preview command: `preview` is written by the user and must hold
  `"test_data": true`, the user's statement that the command points at a test database and test keys (no real email,
  payments or other outside services). Without it `accio-preview start` refuses and mad-eye is a logged skip that
  names the missing field. `preview.env` adds environment variables to the preview process (for example
  `DATABASE_URL` for a test database), so the user needn't change their normal settings file. For a screen behind a
  login, `preview.login: {"user_env": "…", "password_env": "…"}` names two environment variables; `accio-preview start`
  reads them and writes `run/<ID>/preview-login.json` (git-ignored, removed by `stop`) for mad-eye to read; it
  refuses when either is unset. accio can't check that the data is test data: the field is the user's word, and
  wand's setup and the README say so plainly.

### What we build
1. **Check failures go to a fix round.** Files: `accio/bin/accio_lib/checks.py`, `accio/workflows/brew.js`,
   `accio/agents/prefect.md`, `accio/tests/test_checks.py`, `accio/tests/workflow/brew-core.test.mjs`. Needs: none.
   Risk: none. Checked by: a unittest where a check prints a marker and fails, and `check-findings.md` holds the
   command and the marker; a stub test: failing check → fix brief with `--fix …/check-findings.md` → re-check →
   review; check plus review fixes never pass 2 rounds; "Should it be fixed" is gone from `brew.js`.
2. **Retry once; wider test area.** Files: `accio/workflows/brew.js`, `accio/bin/accio_lib/checks.py`, the same
   tests. Needs: 1 (same files). Risk: none. Checked by: stubs: portkey null once → READY after 2 calls; null twice →
   BLOCKED with cause `accio`; a unittest that `evals/case.json` and `evals/x.py` are not out of bounds.
3. **Every ending logged.** Files: `accio/workflows/brew.js`, `accio/agents/headmaster.md`,
   `accio/bin/accio_lib/policy.py`, `accio/bin/accio_lib/brief.py`, `accio/bin/accio_lib/owl.py`,
   `accio/tests/test_owl.py`, `accio/tests/test_curfew.py`, `accio/tests/workflow/brew-review.test.mjs`. Needs: 1, 2.
   Risk: none. Checked by: an owl unittest on a fixture run folder (findings in `fix-1/`, `fix-2/` and the last files,
   a ruling, a question with a cause) → one line per finding id and per block, each with the right ending; a curfew
   test that headmaster may write `run/S-1/ruling-r1.md` and nothing else new.
4. **protego and fidelius catch their start-up crash.** Files: `accio/hooks/_startup.py`, `accio/hooks/protego.py`,
   `accio/hooks/fidelius.py`, `accio/hooks/curfew.py`, `accio/tests/test_protego.py`, `accio/tests/test_fidelius.py`,
   `accio/tests/test_curfew.py`, `accio/tests/test_scaffold.py`. Needs: none. Risk: security (the guards). Checked by:
   subprocess runs with `accio_lib` unimportable: an `accio:house-elf` PreToolUse call is denied (exit 2, stderr); a
   main-chat call and a PermissionRequest exit 0 with no output; `hooks.json` has no `onFailure`.
5. **Cost counts subfolder sessions.** Files: `accio/bin/accio_lib/runs.py`, `accio/tests/test_runs.py`. Needs: none.
   Risk: none. Checked by: a unittest where a transcript under a subfolder's slug with its cwd in that subfolder is
   counted, and one under a sibling `/repo-other` is not.
6. **Exact allow-list.** Files: `accio/bin/accio_lib/bashpolicy.py`, `accio/bin/accio_lib/policy.py`,
   `accio/docs/BACKLOG.md`, `accio/tests/test_curfew.py`. Needs: none. Risk: security (curfew). Checked by: tests that
   `claude plugin validate accio` is allowed and the same with `--x` added or `; rm x` appended is denied; a listed
   check still allows extra arguments; allow-once entries are exact too.
7. **Breaker runner.** Files: `accio/bin/accio-break`, `accio/bin/accio_lib/breaker.py`, `accio/bin/accio_lib/config.py`,
   `accio/bin/accio_lib/policy.py`, `accio/tests/test_breaker.py`. Needs: 3. Risk: security (runs repro code, as
   checks do). Checked by: fixture repos, one per kind: assertion fails on head and passes on base (kept,
   regression); crash in a changed file (kept); import error (dropped); passes on head (dropped); fails 1 of 2
   (dropped); fails on base too (out of scope).
8. **boggart agent and eval set.** Files: `accio/agents/boggart.md`, `accio/evals/boggart/`,
   `accio/tests/test_agents.py`. Needs: 7. Risk: none. Checked by: an agent test (tools, checklist steps, never
   edits); an eval by hand on 3 planted breaks and 3 clean stories: at least 2 caught, none kept on the clean ones.
9. **boggart after review.** Files: `accio/workflows/brew.js`, `accio/bin/accio_lib/review.py`,
   `accio/tests/workflow/brew-review.test.mjs`. Needs: 1, 8. Risk: none. Checked by: stubs: an in-DoD kept break → a
   fix round with `boggart-findings.md`; an out-of-DoD break → an owl line only; a docs-only diff → boggart never
   called.
10. **Spikes S-M2 and S-M3: browser tools in a build.** By hand, about 30–60 min each. S-M2: does a Workflow
    `agent()` get the session's MCP tools? A toy workflow agent calls
    `mcp__plugin_playwright_playwright__browser_navigate` on a local page and saves a screenshot. S-M3: what happens
    when an agent's `tools:` names an MCP server the session lacks? Files: `accio/docs/research/spike-s-m2-m3.md`.
    Needs: none. Risk: none. Checked by: S-M2 passes when the toy agent's screenshot exists; S-M3 passes when the
    agent gets a plain error or runs without the tools, with no hang. If S-M2 fails, mad-eye is not built and the
    note comes back to wand.
11. **Preview start and stop.** Files: `accio/bin/accio-preview`, `accio/bin/accio_lib/preview.py`,
    `accio/bin/accio_lib/config.py`, `accio/bin/accio_lib/policy.py` (portkey may run it), `accio/tests/test_preview.py`,
    `accio/README.md`. Needs: 10. Risk: security (runs the user's app, handles test login details). Checked by: a
    unittest with a stdlib `http.server` as the preview: `start` returns once the URL answers, a second `start` waits
    on the lock, `stop` frees the port and removes `preview.json` and `preview-login.json`, and `stop` after a crashed
    start still frees the port; `start` refuses without `"test_data": true`, and refuses when a `login` variable is
    unset; `preview.env` reaches the process; the README's mad-eye section says the preview must use test data.
12. **mad-eye.** Files: `accio/agents/mad-eye.md`, `accio/bin/accio_lib/policy.py`, `accio/hooks/curfew.py`,
    `accio/workflows/brew.js`, `accio/tests/test_curfew.py`, `accio/tests/workflow/brew-review.test.mjs`. Needs: 9, 11.
    Risk: security (curfew). Checked by: curfew tests that mad-eye's `browser_navigate` to the preview origin and a
    screenshot into `run/<ID>/mad-eye/` are allowed, while navigate to another origin, a screenshot elsewhere,
    `browser_evaluate` and any browser tool for every other agent are denied; stubs: no UI glob → mad-eye never
    called; UI but no `preview` or no `test_data` → a logged skip; mad-eye fails → `accio-preview stop` still called.

### Evidence
- Stub workflow tests (`node --test`): a failing check leads to a fix round, never the question; check and review
  fixes together stop at 2 rounds; a null portkey or prefect reply is retried once, then blocks with cause `accio`;
  boggart and mad-eye are never called on docs-only or non-UI diffs.
- Unittests: `check-findings.md` holds the output; `evals/` is inside the boundary; `accio-break verify` sorts all six
  fixture kinds; owl writes one line per finding id and per block; the guards deny `accio:*` and stay silent for
  others when `accio_lib` won't import; an `agent_allow` entry with an extra argument is denied; a subfolder
  session's transcript is counted. `claude plugin validate accio` passes.
- Over the next two iterations, by grep: no "Blocked question" holds "Should it be fixed" or a single machinery
  failure; each iteration file has a `Findings and blocks` line per finding id and block; every boggart line that
  reached a fix round has a `verify` record of two failures on head; `accio-cost` shows a row for every build.
- The curfew tests: mad-eye's browser tools allowed only on the preview's origin and its screenshot folder, and
  denied for every other agent; `accio-preview stop` frees the port.
- mad-eye: this repo has no UI, so its first evidence comes from one of the user's other repos (a UI story with one
  screenshot per visible DoD line in `run/<ID>/mad-eye/`).

### Open questions
- Spikes S-M2 and S-M3 (part 10) gate mad-eye. If a workflow agent gets no MCP tools, mad-eye is not built and this
  part comes back to wand (option A, a script-run Playwright test, is the fallback).
- Spike S-R1: does `agent()` throw a different error for a stall and a turn-budget stop? If so, retry a stalled
  builder once (decision 011). Left for later.
- A late in-DoD break after both fix rounds are spent blocks with its repro (decision 009). Part 3's log counts these;
  if it happens often, raise the cap.
- boggart's token cost (50–100k Sonnet a story, unmeasured) and mad-eye's (likely above 60k, since each page
  snapshot enters its context): measured on the first stories with `accio-cost`.
- Repros run as untrusted code (security review of S-052, 2026-10-20): `accio-break try` and `verify` run files
  boggart wrote, with the user's rights. Not a new hole (house-elf already runs anything in its worktree, and
  prefect runs the same files), but a sandbox (macOS `sandbox-exec` or a container: only the throwaway worktree
  writable, no network, no `.accio/` or main checkout) would close it. Needs a wand round before it becomes a story.

## Group B leftovers: scripts set the flags, mad-eye stays on the preview

### Outcome
After this ships, `/accio` goes from a new design note straight to sort, every flag that decides whether a review
step runs comes from a script, and mad-eye can't quietly wander off the preview. We'd know because after the next
wand note `accio-board next` says `sort`; `brew.js` asks portkey to compute no flag itself; a test shows an
off-origin page after a click is hidden from mad-eye and fenced; auror's checklist has the two-parsers line; and the
next story that adds an agent lists `accio/README.md` in its `files`.

### Who and why
The user, building accio with accio. Iteration 14's note and this one both left `accio-board next` saying `done`,
so sort was run by hand. S-047's builder warned that the `ui`, `preview` and `test_data` flags come from portkey
(Haiku) matching globs by hand, the weak spot S-058 fixed for `code` and `breaker`. auror missed a URL parser bypass
in S-046. Builds hit an out-of-bounds `accio/README.md` when a story adds an agent. The 0.7.1 push security review
found that a mad-eye click can leave the preview, since curfew checks only `browser_navigate`.

### Requirements
- L1 `accio-board next` says `sort` while a design note recorded by `record-design` has no stories yet. Owner: the
  user (`nextstep.py:41` says sort only with zero stories).
- L2 `accio-brief --review` computes `ui`, `preview` and `test_data` in Python, and `PACKAGE_SCHEMA` requires them.
  Owner: the user (S-047's risk note; `ui_globs` has no reader in `accio/bin` today).
- L3 auror's checklist has a line on two parsers reading one URL or path differently. Owner: the user (the S-046
  miss).
- L4 quill lists a file a test counts (in accio, `accio/README.md` for each new `accio/agents/*.md`) in the story's
  `files`, and the backlog check looks for it. Owner: the user (`test_readme.py:35-43`).
- L5 When mad-eye's page leaves the preview's origin, the page's text is hidden from mad-eye and its browser tools are
  fenced until it navigates back, with a reason logged. Owner: the user (0.7.1 push security review).

### Out of scope
- A sandbox for repros and checks: `sandbox-exec` and bubblewrap are unverified here and on CI (seeker); it stays
  under Open questions.
- Spike S-R1 (retry a stalled builder), as before.
- Requiring Playwright's `--allowed-origins`: Playwright says it is not a security boundary, and a plugin can't set
  it (decision 012, option C).
- Stopping mad-eye with a hook's `continue: false`: whether it ends only the subagent is undocumented.

### Design
Option B (decision 012).
- **Unsorted notes (L1).** `record-design` compares the `## ` headings of the new `design.md` with the committed one
  (`git show HEAD:.accio/design.md`; none committed means every heading is new) and writes the new ones to
  `run/unsorted.json`. `accio-board record`, which sort's step 5 runs, empties it, also when no story was added.
  `next_step` says `sort` while the file lists a heading, checked before the `backlog → prophecy` rule, so a note
  is turned into stories before prophecy plans. A missing or unreadable file means nothing is waiting.
- **Flags from a script (L2).** `review._diff_facts` also returns `ui` (a changed path matches `ui_globs`, with
  `globs.matches_any`, as `risky_files` does), `preview` (config has a `preview` mapping) and `test_data` (that
  mapping has `"test_data": true`). `PACKAGE_SCHEMA.required` becomes `code, breaker, ui, preview, test_data`, and
  `packageFor` only asks portkey to copy the flags as given (the glob-matching sentence at `brew.js:350-353` goes).
- **Two parsers (L3).** One bullet in `accio/references/checklists/auth-and-security.md`: when one part checks a URL
  or path and another reads it again (browser, server, file system), try inputs the two may read differently (`\`,
  `@`, `%2f`, `%5c`, `..`), for example `http://evil.com\@host:port/`.
- **Counted files (L4).** quill.md's `files` rule: a story that adds a file a test counts lists that file too (each
  `accio/agents/*.md` needs its row in `accio/README.md`). Sort's backlog check asks examiner to look for it.
- **Hide and fence (L5).** A PostToolUse hook on browser tools (matcher `mcp__.*__browser_.*`) acts only for
  `accio:mad-eye`. It finds the `- Page URL:` line in the tool's response and compares its origin with
  `preview.url`, using curfew's `policy._origin`. Off the origin, it returns `updatedMCPToolOutput` with the reason
  in place of the page, appends a line to `run/<ID>/mad-eye-fence.log`, and writes a fence record for that
  `agent_id`. While fenced, curfew allows mad-eye only `browser_navigate` (still checked against the origin)
  and `browser_close`, and no read tool (the page is also saved under `.playwright-mcp/`); the fence lifts when a response shows the preview's origin again.
  The hook fails open (decision 007): a crash adds no output, and curfew's navigate rule still holds. The lists stay
  exact (decision 010).

### What we build
1. **Spike S-L5: a real click payload.** By hand, 20–30 min. A logging PostToolUse hook on `mcp__.*__browser_.*`;
   mad-eye clicks a link to another origin; save the payload as a test fixture. Files:
   `accio/docs/research/spike-s-l5.md`, `accio/tests/fixtures/browser-click-offorigin.json`. Needs: none. Risk: none.
   Checked by: the fixture holds the `tool_response` and shows whether `Page URL` appears with default settings.
2. **Unsorted notes.** Files: `accio/bin/accio_lib/design.py`, `accio/bin/accio_lib/nextstep.py`, `accio/bin/accio-board`,
   `accio/tests/test_nextstep.py`, `accio/tests/test_board.py`. Needs: none. Risk: none. Checked by: a test runs
   `record-design` adding a note and `next` gives `sort`; after `record` (with and without new stories) `next` gives
   `prophecy` or `done`; a missing `unsorted.json` gives today's answers.
3. **Flags from a script.** Files: `accio/bin/accio_lib/review.py`, `accio/workflows/brew.js`,
   `accio/tests/test_review.py`, `accio/tests/workflow/brew-review.test.mjs`. Needs: none. Risk: none. Checked by: a
   unittest where a diff touching a `ui_globs` path gives `ui: true` and one that doesn't gives false, with `preview`
   and `test_data` from config; a stub test where a package reply missing `ui` is retried; `brew.js` no longer
   mentions matching globs.
4. **Checklist and quill rule.** Files: `accio/references/checklists/auth-and-security.md`, `accio/agents/quill.md`,
   `accio/skills/sort/SKILL.md`, `accio/tests/test_agents.py`. Needs: none. Risk: none. Checked by: tests that the
   checklist names two parsers with the `\@` example, and quill.md and sort's check name the counted-file rule.
5. **Hide and fence.** Files: `accio/hooks/fence.py`, `accio/hooks/hooks.json`, `accio/bin/accio_lib/policy.py`,
   `accio/hooks/curfew.py`, `accio/tests/test_fence.py`, `accio/tests/test_curfew.py`, `accio/tests/test_scaffold.py`.
   Needs: 1. Risk: security (curfew). Checked by: with the spike's fixture changed to `Page URL: http://evil.com/`, the
   hook returns `updatedMCPToolOutput` with the reason and writes a fence record and a log line; with the preview's
   URL, no output; another agent's call, no output; while fenced, curfew denies `browser_click` and allows
   `browser_navigate` to the preview; a response back on the preview lifts the fence; a hook crash gives no output.

### Evidence
- Unittests: `record-design` then `next` gives `sort`, and `record` clears it; `_diff_facts` gives `ui`, `preview`,
  `test_data` from a fixture diff and config; the fence hook's outputs on the recorded click payload; curfew's
  fenced list.
- Stub workflow test: a package reply without `ui` is retried.
- By grep: `brew.js` has no glob-matching instruction for portkey; the checklist has the `\@` example.
- After the next wand note, `accio-board next` says `sort` (seen live, as this note was not).

### Open questions
- What the PostToolUse `tool_response` looks like for a Playwright click, and whether `Page URL` appears with default
  settings: spike S-L5 (part 1). If it doesn't appear, part 5 comes back to wand.
- A sandbox for repros and checks (`sandbox-exec` on macOS, bubblewrap on Linux): both unverified; needs its own
  spike and wand round.
- Spike S-R1, as before.
