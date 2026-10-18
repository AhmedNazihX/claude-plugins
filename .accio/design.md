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
