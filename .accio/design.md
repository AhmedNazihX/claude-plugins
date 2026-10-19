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
