# 009 — Design grilling: flow, merge, guards and v1 size (bundled)

Date: 2026-10-17 · Status: decided by the user (grilling session before approving `DESIGN.md`)

## Decision

**Audience.** v1 is for a solo developer on their own repo. Accepted stories reach `main` by a direct push.
`config.json` gets `push_mode: "direct"`, so a `"pr"` mode can come in v2 without a redesign.

**Rejection, defined.** A rejection is the user saying no to a READY story at `owl`, with a reason. The reason
goes into the story's Review notes, its ledger entry is cleared, it goes back to *Ready* and keeps its branch.
Anything the build stops on its own is BLOCKED, never "rejected".

**Dependent stories: stacked branches, at most 2 levels per iteration.**
- A child is held in the same `brew` run until its parent is READY, then branches from the parent's verified
  head (`story/<parent>`), not from base.
- A parent that ends BLOCKED means the child is not started in that run. It stays *Ready*.
- `owl` merges in dependency order. Accepting a child requires accepting its parent.
- A rejected or dropped parent sends its children back to *Ready*; they are rebuilt on the fixed parent.
- A third link waits for the next iteration.

**Drop.** `owl` gets a third answer, `drop <ID>: <reason>`. The story gets status `dropped`: final, but
reversible on request. Its worktree is removed and its branch kept. `prophecy` never proposes it again unless
asked. A story that depends on it gets one question at the next `prophecy`: drop it too, or remove the dependency.

**Hook scope.** Every Claude hook exits silently unless the repo has `.accio/`, found through
`git rev-parse --git-common-dir`, so story worktrees outside the repo still count.

**`/accio:brew` is the workflow only.** There is no `brew` skill. When workflows are off, `session-start` and
`map` point to the `brew-by-hand` fallback.

**Existing git-hook managers: chain and warn.**
- Plain repo: write the hook, or append to a hand-written one.
- husky: append a `# accio` marker and a call to `accio-hooks run <hook>` to `.husky/<hook>`.
- lefthook, pre-commit framework: edit nothing; warn once with a copy-paste snippet.
- `accio-hooks verify` runs at every `brew` and `owl`: the marker is present, the hooks folder is the active one,
  and the plugin path is not stale (it rewrites a stale path). If the marker is missing, the user gets one plain
  line: re-add, or carry on without it.
- Uninstall removes only the marked lines.

**Full checks before every push.** `accio-merge` merges the accepted stories, in dependency order, on a temporary
branch `accio/integrate-<N>` in its own worktree, and runs all the checks there. `main` is fast-forwarded only when
they pass, so `main` never needs a reset. On a failure, the merges are replayed in order with only the failing
checks to find the story that broke them. That story goes back to *Ready* with the failure in its Review notes,
and the user is asked whether to push the rest.

**DoD lines are numbered and tagged.** DoD lines read `S-012/1 WHEN … THE SYSTEM SHALL …`. A test carries its tag
in its name or a comment. `prefect` greps the story's tests for every tag, with no model involved. A line that
cannot be tested is marked `(no test)` and skipped. `examiner` judges only whether each tagged test really checks
its line.

**Worktree confinement: a guard and a snapshot.**
- A `PreToolUse` Write/Edit hook, `boundary`, blocks writes outside the current accio worktree. The one exception
  is `.accio/run/<ID>/` in the main repo.
- `prefect` snapshots the main checkout's `git status` before and after each story. A change sends the story to
  Blocked, with the list of changed files.
- Accepted gap: shell writes outside the main checkout (the stance of decision 004).

**`pre-push` blocks only Claude.** A push to base is blocked when `CLAUDECODE=1` is set and there is no valid `owl`
token. Pushes from the user's own terminal pass. Force-push is blocked for everyone. `CLAUDECODE=1` was verified
in Claude Code's Bash tool on 2026-10-17. The spike checks it inside workflow agents.

**Merge style.** One `--no-ff` merge commit per story, with the message `<type>(S-012): <title>` (Conventional
Commits). The checkpoint commits are kept. `git log --first-parent` shows one line per story. Undo is
`git revert -m 1 <merge>`.

**v1 size: about 24–25 stories.** These move to v1.1:
- `telescope` (amends 008)
- `reparo`
- `lumos`
- `doc-size` with `librarian`
- the plain output style

`brew-by-hand` is built only if spike S-001 shows it is needed. `wand` keeps `wandmaker`'s 2–3 options.

**How accio is built.** By hand, in plain Claude sessions, from a lean `docs/BACKLOG.md`: about 25 stories in
build order, each with deps, files and numbered EARS DoD lines. No lanes, waves or critical path. There is no
foreman story workflow and no dogfood cutover.

## Options compared
| Topic | Chosen | Rejected, and why |
|---|---|---|
| Audience | solo now, PR mode later | teams with PRs: ~3–5 more stories, and an iteration closes only when the PRs merge on GitHub |
| Dependent stories | stacked, 2 levels | independent only: a 4-link chain takes 4 iterations (~16 + k prompts); iteration branch: rejection means unpicking a shared branch, against 005 |
| Unwanted story | `drop` + `dropped` | back to Backlog: re-proposed every iteration; reject only: risks a wasted rebuild (~150–400k tokens) |
| Hook scope | accio repos only | everywhere: blocks in repos that never opted in, and doubles up with `secret-guard` / `git-guardrails` |
| `brew` | workflow only | skill in front: whether a skill's call counts as opt-in is UNKNOWN (`platform-facts.md`) |
| Hook managers | chain + warn | warn only: no wall in husky repos; take over: breaks the project's hooks; all managers: ~2–3 more stories |
| Full checks | once, before push | CI after push: `main` can break; every story: full suite × stories × rounds |
| DoD → test | numbered + tagged | reviewer judges: tokens on every review, and it varies from run to run (F2) |
| Confinement | guard + snapshot | either alone: no backstop if hooks don't fire in workflow agents, or detection without prevention |
| `pre-push` | only Claude | everyone: trains the user to type `--no-verify`; force-push only: breaks "pushing always asks" (005) |
| Merge style | merge commit | squash: breaks `git branch -d` and stacked children; rebase + ff: 40–80 wip commits per iteration |
| v1 size | cut add-ons (~25) | everything (~31): close to 001's rejected option B; light `wand`: saves ~2 stories but drops the options step |
| Build accio | by hand | foreman only, or foreman then accio: the user's choice |

Story counts and token figures are Claude's rough estimates, not measurements.

## Why
- The open points sat where two sections meet. "Deps must be done" plus "done only at `owl`" made chains take one
  iteration per link.
- The plugin-wide hook scope would have surprised the user in unrelated repos.
- A husky repo would have silently had no native wall.
- Every choice keeps decision 005's two checkpoints and decision 004's "guard the effect" stance.
