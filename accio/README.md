# accio

A Claude Code plugin that plans, builds, reviews and safely merges your project's work in small iterations. You talk
to it at two checkpoints: when you plan an iteration, and when you review what it built. In between, it builds on
its own: each story in its own git worktree, test-first, checked by scripts and reviewed by separate agents, with
nothing reaching your main branch until you say so.

It is for a solo developer working on their own git repo.

## How it works

| Step | You type | What happens |
|---|---|---|
| Design | `/accio:wand` | An interview, one question at a time. It always asks "after this ships, what should be true, and how would you know?". A researcher agent checks the facts against live docs, an architect agent proposes 2–3 options, and you choose. It writes `.accio/design.md` and records each decision. |
| Stories | `/accio:sort` | The design becomes small story files, each with numbered "WHEN … THE SYSTEM SHALL …" lines a test can check. A score sets how much review each story gets, and a backlog check fixes weak stories. |
| Plan | `/accio:prophecy` | Up to 8 stories that are ready to build, with their open questions settled. Say "go". |
| Build | `/accio:brew` | Unattended. At most 3 stories at once, each built test-first in its own worktree, then checked (tests, file boundaries, mutation testing if you set it up), reviewed (spec, quality, and security on risky paths) and fixed in at most 2 rounds. You get one short table back. |
| Review | `/accio:owl` | One summary of what was built and every open question. Answer in one go (accept, reject or drop each story, answer the questions, push or not). It merges what you accepted, runs every check on the result, and pushes only if you said yes. |
| Any time | `/accio:map`, `/accio:vow` | The board and the next step; a decision written down as a numbered record. |

Everything accio knows lives in `.accio/` in your repo: the design, decisions, stories, iterations and board are
committed; the build's runtime state (`.accio/run/`) is ignored by git.

## Install

```bash
claude plugin marketplace add AhmedNazihX/claude-plugins
claude plugin install accio@nazihx
```

Then, in your project, start a new Claude Code session and type `/accio:wand`. On first use it sets accio up
(`.accio/` and its git hooks).

**Needs:** git, Python 3.9 or later (the scripts use only the standard library), and Claude Code with workflows on.
`/accio:brew` is a Claude Code workflow: if workflows are switched off (the `disableWorkflows` setting, or the
`CLAUDE_CODE_DISABLE_WORKFLOWS` variable), accio says so and how to turn them on. The first `/accio:brew` asks you
once to allow the workflow; "don't ask again" covers later runs.

## Safety

- **Nothing reaches your main branch without you.** Stories are built on their own branches, in worktrees outside
  your repo. `owl` merges only what you accepted, after every check passes on the merged result, and a push to your
  main branch needs your yes at `owl` (a git `pre-push` hook enforces it, and refuses a push to it while a build runs).
- **The build's agents can only do their job.** A hook answers every tool call an accio agent makes, from a fixed
  list per agent: the builder may write only inside its own worktree, reviewers only their findings file. A
  command off the list is refused with the reason, and comes back to you at `owl` as a question (allow once, allow
  from now on, or no).
- **Secrets and destructive commands are blocked:** key-shaped values never reach a file or a commit, and commands
  such as `rm -rf` outside the project, `git reset --hard` or skipping git hooks are refused.

These guards match commands and paths, so they catch mistakes and leave a trail rather than stopping a determined
attacker; use Claude Code's sandboxing for that. They do nothing in a repo without `.accio/`. accio works alongside
[`git-guardrails`](../git-guardrails/README.md), which protects every repo.

## Cost

About 1,900 tokens of accio's descriptions are loaded in every session. A build costs what its agents use: a Quick
story has a budget of 80k fresh tokens and a Story 400k (cache reads are counted apart). The review at `owl` shows
each story's tokens; a story far over budget stops and comes back as a question.

## Development

accio is developed here, in the `nazihx` marketplace repo:

- `docs/DESIGN.md` (how it works and why), `docs/BACKLOG.md` (the stories it was built from) and
  `docs/decisions/` (numbered decision records).
- Tests, from this folder: `python3 -m unittest discover -s tests` and
  `node --test 'tests/workflow/**/*.test.mjs'`. CI runs them on Linux and macOS.
- Skill evals: `claude plugin eval` with free graders only; see `evals/README.md`. In CI they run only by hand.
- Layout: `skills/` (the commands), `agents/` (portkey, house-elf, prefect, examiner, professor, auror, headmaster,
  quill, seeker, wandmaker, librarian), `workflows/brew.js` (the build), `hooks/` (the guards), `bin/` (the
  scripts the agents and skills run).

Not in v1: `brew-by-hand`, a build without workflows (decision 012), and `reparo`, `lumos` and `telescope`
(v1.1). Licence: MIT (`../LICENSE`).
