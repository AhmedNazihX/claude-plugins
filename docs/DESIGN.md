# accio: design

Status: approved · Date: 2026-10-17 · Owner: Ahmed N. Ali

Sources:
- `intent.md`
- `docs/research/analysis.md`, `build-engine.md`, `platform-facts.md`
- decisions `docs/decisions/001`–`010` (002 and 004 amended after the design review; 001, 004 and 008 amended by
  the design grilling, decision 009; decision 010 after spike S-001)

accio is a Claude Code plugin that runs production software work in Lean-Kanban iterations:
1. design the stack and architecture
2. break the work into stories
3. plan each iteration with the user
4. build stories with agent workflows
5. review and QA
6. merge safely

It guides the user, explains things simply, grills decisions, and guards the repo.

---

## 1. Goals and non-goals

### Audience (v1)
A solo developer working on their own repo. Accepted stories reach `main` by a direct push. `config.json` has
`push_mode: "direct"`, so a pull-request mode can come in v2 without a redesign (decision 009).

### Goals (each traced to intent.md, I1–I8)
- **I1:** Cover the lifecycle: design → planning → iteration planning → build → review/QA → retro. *The retro
  (`pensieve`) and the deep QA audit are v2.*
- **I2:** Work in agile iterations inspired by Lean Kanban: pull, WIP limits, and an explicit "done". *Flow
  metrics (cycle time, throughput) are v2.*
- **I3:** Plan every step and iteration with the user, and block the user only when that is really needed.
- **I4:** Explain steps and options simply.
- **I5:** Grill decisions while planning, until the user and the plugin agree on the design and the DoD.
- **I6:** Use git, and guard against destructive commands and leaked secrets.
- **I7:** Build stories with agent workflows, using current practice.
- **I8 (added during research):** Keep the token cost low.

### Non-goals (v1)
- No swarm or many-topology orchestration (see the Claude Flow warning in `analysis.md` § 6).
- No hosted services, dashboards or paid APIs of its own.
- No deep architecture workshop or retro metrics in v1 (decision 001). `pensieve` comes in v2.
- Not a replacement for the project's own CI. accio runs the project's checks; it is not a CI system.
- No team or pull-request flow in v1 (decision 009).

### Failures this design must not repeat (F1–F4)
- **F1:** too much ceremony
- **F2:** review loops and stuck agents
- **F3:** too many prompts
- **F4:** hard to understand

---

## 2. Principles

| # | Principle | Answers |
|---|---|---|
| P1 | **Ceremony scales with size.** Work goes on a Quick, Story or Feature track; the plugin picks the track and the user can override it (decision 002). | F1, I8 |
| P2 | **Caps live in code.** The build workflow, not the model, enforces the fix-round cap, the timeouts and the WIP limit (decision 003). | F2 |
| P3 | **The user takes part in two checkpoints per iteration:** plan, then review. Everything between them runs unattended, and questions are collected for the review (decision 005). | F3, I3 |
| P4 | **Magic names, plain words.** The output uses one report template; decisions follow the `decisions.md` format (decision 007). | F4, I4 |
| P5 | **Verification decides "done".** Checks, tagged tests per DoD line, an independent spec review, and a ledger keyed to the exact diff decide it, not the agent's claim. | I7, F2 |
| P6 | **Effects are guarded, not text.** Native git hooks are the wall; the Claude hooks are narrow early warnings (decision 004). | I6 |
| P7 | **The main chat coordinates and never does the work.** Every handoff is a file, and every agent returns one line or a small JSON object. Scripts come before agents. | I8, F4 |
| P8 | **State lives on disk.** Any session can be cleared and resumed from `.accio/` and git. | F2 |
| P9 | **Grill at the decision points, not everywhere.** Grilling happens in `wand` (design) and `prophecy` (iteration DoDs), one question at a time, each with a recommendation. | I5, F3 |
| P10 | **accio acts only where it was set up.** Every Claude hook does nothing in a repo without `.accio/` (decision 009). | F4 |

---

## 3. The lifecycle

```
wand ──► sort ──► ┌──────────── one iteration ─────────────┐
(design) (backlog) │ prophecy ──► brew ──► owl ──► (pensieve)│ ──► next iteration
                   │ (plan, go)  (build)  (review)  (retro v2)│
                   └─────────────────────────────────────────┘
any time: map (board) · vow (record a decision)
v1.1:     reparo (quick fix) · lumos (explain) · telescope (research)
```

### 3.1 Design: `wand`
**Input:** `intent.md` or the user's idea, plus the existing code if there is any.

**Steps:**
1. **Interview the user, one question at a time.** Every requirement must have an owner; a requirement without one
   is deleted.
2. **Research the facts.** `seeker` checks live docs and the existing code. A capability the docs don't mention
   counts as unavailable until a spike proves it.
3. **Propose designs.** `wandmaker` proposes 2–3 stack and architecture options with trade-offs and "what breaks
   first".
4. **Grill the user's choice.**

**Output:** `.accio/design.md`, one page plus sections that grow as needed, and a `vow` per real decision.

**Size by track:** a Feature that arrives later gets a design *note* (one section) from the same skill.

### 3.2 Planning: `sort`
The `quill` agent (Sonnet) splits the design into story files (§ 5), and the main chat shows only the summary.
IDs come from `accio-board new` (S-001, S-002, …). Each story gets:
- deps
- a file boundary (the files it may touch)
- a risk flag
- a DoD in EARS form ("WHEN … THE SYSTEM SHALL …"), **one numbered line per behaviour** (`S-012/1`, `S-012/2`),
  so each line maps to a test that carries its tag (§ 7.1). A line that can't be tested is marked `(no test)`.

A script computes a complexity score from the files touched, the risk paths and any new dependencies. The score
sets the track and **flags** any story above the Story threshold. `quill` splits a flagged story, and each child
gets the next free ID. `examiner` checks the backlog for stories that aren't atomic, DoDs that can't be checked,
and missing deps. Its findings are fixed in the same skill run. Unless something is truly ambiguous, the user sees
only the summary.

### 3.3 Iteration planning: `prophecy` (checkpoint 1)
1. **Propose the batch:** up to 8 stories, pulled in dependency and value order, with their tracks. A story is
   eligible when its deps are done, **or** when its parent is in the same batch and the chain stays within 2 levels
   (§ 3.4, stacking). `dropped` stories are never proposed unless the user asks.
2. **Grill the open questions** for the batch: unclear DoDs, missing decisions, and stories whose dep was dropped
   (drop them too, or remove the dep). One question at a time, in the `decisions.md` format. Low-stakes defaults
   are bundled into one confirmation.
3. **Wait for "go".** The user can override any track or drop any story.

Once the user says go, the stories move to *Ready*, and the plugin tells the user to type `/accio:brew`. That
name belongs to the **workflow itself** (`workflows/brew.js`); there is no `brew` skill (decision 009). The user
types it, which is the documented opt-in. The iteration is written to `.accio/iterations/<N>.md`. If the
`Workflow` tool is missing from `prophecy`'s own tool list, workflows are off: it says so in plain words and points
to `/accio:brew-by-hand` instead (decision 010).

### 3.4 Build: `/accio:brew` → `workflows/brew.js`
This is the unattended part. The full spec is in `docs/research/build-engine.md`, section "Option C in detail".

| Step | Agent | Model | Rule |
|---|---|---|---|
| 0 load | `portkey` | Haiku | `accio-board ready --json`, in dependency order; also recovers stories a crash left in *Doing* (§ 12.6); `accio-hooks verify`; takes the run lock with `accio-board lock` (§ 4.5) |
| 1 prepare | `portkey` | Haiku | `accio-brief` creates or reuses the worktree and branch `story/<ID>` (§ 12.3), from base or from the parent's head when stacked, and writes `brief.md`, including review notes from a rejection |
| 2 implement | `house-elf` | Sonnet; Opus if complex or risky | first runs `accio-claim <ID>` (§ 4.4); reads only the brief; starts each Bash command that touches files with `cd <worktree> &&` or uses `git -C <worktree>`; test-first; tags each test with its DoD line; checkpoint commits; `report.md`; returns a status |
| 3 check | `prefect` | Haiku | the ledger skips an exact key that already passed (§ 12.4); checks scoped to the change; **boundary check:** a diff outside the story's `files` (plus tests) becomes a finding; **DoD tags:** every numbered line not marked `(no test)` has a tagged test; **main snapshot:** the main checkout's `git status` is unchanged; **remote check:** `origin/<base>` has not moved |
| 4 review | `examiner` + `professor` (+ `auror` on risky paths); Quick track: 1 combined reviewer | Sonnet | read-only; review package as a file; confidence ≥ 80 |
| 5 judge | `headmaster` | Sonnet | only when a finding conflicts with the story, or on NEEDS_CONTEXT; rules it, or marks the story needs-user |
| 6 fix | a fresh `house-elf` | one tier up in round 2 | **≤ 2 rounds**; the re-review covers only the fix diff, and only the reviewers that raised findings run |
| 7 outcome | `prefect` | Haiku | `accio-board move` + `accio-ledger record`: READY → *Review*; otherwise *Blocked*, with one plain question in `run/questions/<ID>.md` |

At most 3 stories are in progress at once. A `stallMs` timeout turns a silent agent into a failure. It does **not**
end an agent waiting on a permission prompt (spike S-001), so no accio agent may ever reach one: `curfew` answers
every tool call for accio's agents (§ 4.4, decision 010). The run returns one table (§ 7.2) of about 1–2k tokens.
Workflow scripts have no file access, so a final `portkey` call in a `finally` block releases the lock
(`accio-board unlock`).

**Stacking (decision 009).** A child is held back until its parent reaches READY in the same run, and its slot goes
to another story. The child then branches from the parent's verified head. If the parent ends BLOCKED, the child
is not started in that run and stays *Ready*. At most 2 levels stack in one iteration; a third link waits for the
next one.

### 3.5 Review and QA: `owl` (checkpoint 2)
`accio-summary` builds `run/owl.md` from the reports and the cost data. The main chat reads only that file,
about 150 tokens per story. For each READY story, the plugin shows:
- what changed
- how to try it
- its risks
- its token cost

The user answers everything in one batch:
- for each story: **accept**, **reject** (with a reason) or **drop** (with a reason)
- answer the collected questions (needs-user stories, overrides, paid calls, a hook warning from setup, and each
  command `curfew` denied: allow once, allow from now on, or no)
- confirm the push

**What the answers do:**
- **Accept.** Accepting a child requires accepting its parent; `owl` says so in plain words otherwise.
- **Reject.** The user says no to a READY story. The reason goes into its **Review notes**, its ledger entry is
  cleared, and it goes back to *Ready* with its branch kept. Its stacked children go back to *Ready* too, and are
  rebuilt on the fixed parent. Anything the build stopped on its own is BLOCKED, never "rejected".
- **Drop.** The story gets status `dropped`, final but reversible on request. Its worktree is removed and its branch
  kept. Its stacked children go back to *Ready*, and the next `prophecy` asks about them.
- **Answer** a BLOCKED story's question. It goes back to *Ready*. "Allow from now on" for a denied command adds it
  to `agent_allow` in `config.json` (decision 010).

**Merge (decision 009).** `accio-merge` merges the accepted stories, in dependency order, on a temporary branch
`accio/integrate-<N>` in its own worktree. Each story gets one `--no-ff` merge commit, `<type>(S-012): <title>`.
It then runs **all** the checks once on the result:
- **Pass:** `main` is fast-forwarded to the integration branch. `main` never needs a reset.
- **Fail:** nothing reaches `main`. The merges are replayed in order with only the failing checks, to find the
  story that broke them. That story goes back to *Ready* with the failure in its Review notes, and the user is
  asked whether to merge and push the rest.

Then:
- `accio-merge` removes each merged story's worktree and the integration worktree, and deletes their branches
  with `git branch -d`, which works only on merged branches (§ 12.3).
- One commit records every status change for the iteration: `chore(accio): iteration <N> review`.

If the main checkout has uncommitted changes, the fast-forward uses `git merge --ff-only`. Git refuses only when
those changes touch the same files, and then the user gets one plain question.

**The iteration closes at `owl`.** Leftover stories carry over to the next `prophecy`. The same batch answer can
also say "brew the answered stories now". That runs a second pass, which costs one more `/accio:brew` and one
more `owl`.

**Push.** After the user confirms, `owl` writes a one-time push token (`run/push-ok`, holding the HEAD sha). The
`pre-push` hook allows a fast-forward push of exactly that sha to base, then deletes the token (§ 4.5).

### 3.6 Retro: `pensieve` (v2)
Reports the tokens per story and per iteration, the cycle time and the throughput, and lists findings that came
back more than once. `telescope` scans new Claude Code features and ecosystem plugins for improvements to accio
itself and writes proposals to `.accio/research/`. It never changes accio on its own. It proposes rules (in the
style of hookify) and records accepted ones with `vow`.

### 3.7 Any time
- `map`: the board, generated by a script. When the `Workflow` tool is missing from its tool list, it points to
  `brew-by-hand`.
- `vow`: writes `.accio/decisions/NNN-<slug>.md`.

**v1.1 (decision 009):**
- `reparo`: a quick fix outside an iteration. One `house-elf` and one combined reviewer run as plain subagents,
  with no workflow. They follow the same safety rules and the same ledger.
- `lumos`: re-explains the last step, an option or a term in simpler words.
- `telescope <topic>`: on-demand research (`seeker`, about 30–60k tokens per run), plus "better way?" notes in
  `prophecy` (decision 008).

---

## 4. Components

**Every agent returns one line or a schema-bound JSON object. Full reports go to files.**

### 4.1 Skills
Each skill keeps its SKILL.md under about 80 lines, with details in `references/` (decision 006).

| Skill | Phase | User-facing? | Version |
|---|---|---|---|
| `wand` | design | yes | v1 |
| `sort` | planning | yes (summary) | v1 |
| `prophecy` | iteration planning, checkpoint 1 | yes | v1 |
| `owl` | review, checkpoint 2 | yes | v1 |
| `map` | board | yes | v1 |
| `vow` | decision record | yes | v1 |
| `brew-by-hand` | fallback build controller, plain subagents | yes (one command) | conditional: only for users with workflows off (spike S-001: GO) |
| `reparo` | quick fix | yes | v1.1 |
| `lumos` | explain | yes | v1.1 |
| `telescope` | research for better ways (prophecy, pensieve, on demand) | yes (notes) | v1.1 |
| `pensieve` | retro | yes | v2 |

The build itself is the workflow `/accio:brew` (§ 4.3), not a skill.

### 4.2 Agents
| Agent | Role | Model | Tools | Returns |
|---|---|---|---|---|
| `seeker` | researcher (live docs and code facts in `wand`; better ways via `telescope` in v1.1) | Sonnet | Read, Grep, Glob, WebSearch, WebFetch | `findings: <path>` |
| `wandmaker` | architect, 2–3 options | Opus | read-only | `options: <path>` |
| `portkey` | worktree and brief | Haiku | Bash (scripts only) | `{worktree, brief, base}` |
| `house-elf` | implementer | Sonnet / Opus | Read, Grep, Glob, Write, Edit, Bash, kept short because `curfew` must answer every tool (§ 4.4) | `{status, head, report}` |
| `prefect` | checks, ledger, DoD tags, main snapshot | Haiku | Bash | `{pass, failing[], skipped}` |
| `examiner` | spec reviewer and backlog checker | Sonnet | read-only plus Write to its findings path | `{verdict, counts, path}` |
| `professor` | quality reviewer | Sonnet | same as examiner | same |
| `auror` | security reviewer (risky paths) | Sonnet | same as examiner | same |
| `headmaster` | judge | Sonnet | read-only plus Write to the ledger | `{ruling | question}` |
| `quill` | writes story files from the design (in `sort`) | Sonnet | Read, Write to `.accio/stories/` | `stories: N · summary: <path>` |
| `librarian` | doc lookups, quotes only | Haiku | Read, Grep | quotes with `file:line` |

### 4.3 Workflow
- `workflows/brew.js`: the § 3.4 pipeline, invoked as `/accio:brew`.
- Tested with a stubbed `agent()`.

### 4.4 Hooks
**Every hook first looks for `.accio/` through `git rev-parse --git-common-dir`, and exits silently if there is
none** (decision 009). Story worktrees live outside the repo, so this lookup is what keeps the guards on inside
them.

| Hook | Event | Does |
|---|---|---|
| `protego` | PreToolUse Bash | blocks a short list: `reset --hard`, `clean -f`, `rm -rf` outside the repo, `--no-verify`, `core.hooksPath` changes, force branch delete (`-D`; `-d` is allowed because git refuses it on unmerged branches), `unset CLAUDECODE` / `env -u CLAUDECODE`; every block names the safe alternative; defers to dcg if installed |
| `fidelius` | PreToolUse Write/Edit | blocks key-shaped values; never echoes the secret; test fixtures build fake keys at runtime by concatenation, so they need no exemption |
| `curfew` | PreToolUse, every tool (matcher `*`) | **answers every permission question for accio's agents** (`agent_type` `accio:*`), so none ever waits on a prompt; other callers get no answer and go through the normal permission flow (decision 010). **`house-elf`:** its first command, `accio-claim <ID>`, links its `agent_id` to that story's worktree in `run/claims.json`, and until then it may not write. After that, Write/Edit only inside its worktree (plus `.accio/run/<ID>/`), resolving `..` and symlinks. Bash only from an allow list that learns: the checks, git except push, read-only tools, the project's run/build/test commands, plus `agent_allow` in `config.json`; split at `&&`, `;` and `\|`, and a command that touches files starts with `cd <its worktree> &&` or uses `git -C <its worktree>`. Anything unparseable (`$(…)`, backticks, `sh -c`, `eval`) is denied. **Other agents:** an exact list each. Every deny names its reason; in a build it becomes a BLOCKED question at `owl` |
| `session-start` | SessionStart | injects ≤ 10 lines: the board summary, the next step and the plain-words rule (plugins can't ship rules); points to `brew-by-hand` when `CLAUDE_CODE_DISABLE_WORKFLOWS` is set (it can't see the `disableWorkflows` setting; `prophecy` and `map` catch that case) |
| `doc-size` | PreToolUse Read | blocks a whole-file read of `.md` files over 40 KB and points to `librarian`, or to reading by section with offset/limit |

### 4.5 Native git hooks
`accio` installs these into each project with `bin/accio-hooks install`, which is run by `wand` or on first `brew`:
- **`pre-commit`:** a secret scan, with gitleaks if installed and built-in patterns otherwise.
- **`pre-push`:** blocks force-push for everyone. A push to the base branch without a valid `owl` token is
  blocked by **where and when** it happens (decision 009):
  1. **During a `brew` run, from anyone.** The run takes `run/brew.lock` at the start (`accio-board lock`) and releases it at the end.
     Every status move refreshes it. A lock with no refresh for 30 minutes counts as stale, and the hook says so.
  2. **From a story worktree, always.** Nothing legitimate pushes from one in v1.
  3. **Outside a run, when `CLAUDECODE=1` is set** (Claude is pushing). `! git push` typed inside Claude Code
     counts as Claude. Pushes from the user's own terminal pass.

  **Backstop:** `prefect` records where `origin/<base>` points before and after each story. If it moved, the story
  goes to Blocked and the user is told at `owl`.

**Existing hook managers (decision 009).** `accio-hooks install` finds the active hooks folder
(`core.hooksPath`) and the known manager files:
- **Plain repo:** it writes the hook, or appends to a hand-written one.
- **husky:** it appends a `# accio` marker and a call to `accio-hooks run <hook>` to `.husky/<hook>`, so the
  project's own hook runs first.
- **lefthook, pre-commit framework:** these regenerate their hook files, so accio edits nothing. It warns once
  with a copy-paste snippet for their config.

`accio-hooks verify` runs at every `brew` and `owl`. It checks that the marker is present, that the hooks folder is
the active one, and that the plugin path is not stale (it rewrites a stale path). If the marker is missing, the
user gets one plain line: re-add, or carry on without it. Uninstall removes only the marked lines.

### 4.6 Scripts
All scripts are in `bin/` and use only the Python 3 standard library. **Every script finds the main checkout's
`.accio/` with `git rev-parse --git-common-dir`, from any worktree**, so worktrees never read stale state.
Submodules work. A repo made with `git init --separate-git-dir` does not support story worktrees, because git
doesn't record its main checkout; `accio-hooks install` warns about it. `bin/` is
on PATH inside workflow agents, but `${CLAUDE_PLUGIN_ROOT}` is not set there (spike S-001), so briefs give each
script's absolute path.

| Script | Does |
|---|---|
| `accio-board` | parse stories → board.md (with a Dropped line), `ready --json` (including stacked children), `status`, `move`, `new` (IDs), `lock` / `unlock` (the run lock) |
| `accio-brief` | story → brief.md (template), from base or from the parent's head; fix brief from findings |
| `accio-ledger` | patch-id verdicts, `check`, `record` |
| `accio-score` | complexity score → track, split flag |
| `accio-merge` | integration worktree, `--no-ff` merges in dependency order, full checks, find the breaking story, fast-forward main, clean up |
| `accio-cost` | sums `usage` from each `agent-<id>.jsonl` in the run's transcript folder, grouped by the label in `agent-<id>.meta.json`, per story and iteration (spike S-001) |
| `accio-claim` | run by `house-elf` as its first command; prints its worktree; `curfew` records the claim (decision 010) |
| `accio-hooks` | install (with chaining), `verify`, `run <hook>`, uninstall |
| `accio-summary` | reports and cost data → `run/owl.md` for the review |

### 4.7 Output style (v1.1)
`output-styles/plain.md` holds the plain-words rule for users who want it always on.

---

## 5. State: `.accio/` (committed unless marked otherwise)

```
.accio/
  design.md                 # from wand
  decisions/NNN-<slug>.md   # from vow
  research/<date>-<topic>.md # from telescope (v1.1)
  stories/<ID>.md           # one per story
  board.md                  # GENERATED by accio-board — never hand-edit
  iterations/<N>.md         # plan + outcome per iteration
  config.json               # checks, risky paths, budgets, base branch, push mode
  run/                      # gitignored: ledger.tsv, status.json, brew.lock, claims.json, main-snapshot, briefs, reports, findings, questions/, overrides.json, owl.md, push-ok
# worktrees live OUTSIDE the project, in <repo>/../.<repo>-accio-wt/<ID>/ (and integrate-<N>/ at owl),
# so the project's tools never scan them
```

### 5.1 Story file
```markdown
---
id: S-012
title: Password reset email
type: feat              # Conventional Commits type for the merge commit
track: story            # quick | story | feature
status: ready           # backlog | ready | doing | review | done | blocked | dropped
deps: [S-010]
files: [src/auth/reset.ts, src/auth/reset.test.ts]
risk: auth
budget_tokens: 400000
---
## Context
<why, links to design.md section>
## Definition of Done
- [ ] S-012/1 WHEN a user requests a reset THE SYSTEM SHALL email a single-use link valid 30 min
- [ ] S-012/2 WHEN the link is older than 30 min THE SYSTEM SHALL reject it
- [ ] S-012/3 (no test) checks pass: `npm test`, `npm run lint`
## Review notes
<filled by owl on a rejection or a failed full check>
## Blocked question
<filled by headmaster when needed>
```

A dropped story also records `dropped: <reason>` in its frontmatter.

### 5.2 `config.json` (kept small)
| Key | Holds |
|---|---|
| `base_branch` | the base branch |
| `push_mode` | `direct` (v1); `pr` in v2 |
| `checks` | the check commands, each with a file glob |
| `risky_paths` | glob paths that force the Story track |
| `budgets` | per-track token budgets (quick, story) |
| `wip` | 3 |
| `iteration_max` | 8 |
| `stack_depth` | 2 |
| `agent_allow` | commands `house-elf` may run beyond the built-in allow list; grown by "allow from now on" at `owl` (decision 010) |
| `paid_call_cap_usd` | 0 |

A missing key falls back to its default.

---

## 6. Safety model (decisions 004 and 009)

| Layer | Stops | Bypass |
|---|---|---|
| `pre-commit` (native) | secrets in staged files | `--no-verify` (blocked by protego) |
| `pre-push` (native) | force-push by anyone; a push to base without the one-time `owl` token during a run, from a story worktree, or by Claude (§ 4.5) | `--no-verify` (blocked); outside a run, Claude deliberately unsetting `CLAUDECODE` in the main chat (accepted: the user is watching, and `protego` warns) |
| `protego` (Claude) | a short destructive list, early with an alternative | wrapping the command (accepted: the git hooks are the wall) |
| `fidelius` (Claude) | secret values in Write/Edit | — |
| `curfew` (Claude) | any tool call by an accio agent outside its policy: writes outside its claimed worktree, Bash off the allow list, unparseable commands; and every permission prompt, which it answers itself (decision 010) | an allowed command misused inside the worktree (accepted; the main snapshot and the reviews catch the effects) |
| main snapshot (`prefect`) | any change to the main checkout during a story | — |
| remote check (`prefect`) | a push to base that got past every hook during a story | — |
| One-time override | — | a block during a build makes the agent return BLOCKED with `needs override: <command>`; the question comes up at `owl`; a grant writes `run/overrides.json` (command, folder, 24 h expiry, 1 use) |

All Claude hooks act only in repos that have `.accio/`.

Secret patterns are ported from `~/Workspace/claude-mods/secret-guard/hooks/patterns.ts`:
- a JWT role decode, so only `service_role` keys are blocked
- known example values are allowed
- passwords in database URLs are allowed when the host is local
- Stripe, Google and AWS keys are covered

Messages show only a prefix of the secret.

---

## 7. Review, QA and the user's view

### 7.1 Review policy (decision 003)
- **Confidence:** a finding needs confidence ≥ 80 to count. Known false positives (what a linter or CI catches) are
  listed in each reviewer.
- **The spec reviewer comes first.** `examiner` checks the DoD one line at a time: met or not, nothing extra.
- **Fix rounds:** at most 2. A third is never run; the story goes to Blocked with a plain question.
- **Re-reviews never repeat a round.** They judge only the fix.
- **QA in v1:**
  - the project's checks, scoped per story, plus one full run on the merged result before every push (§ 3.5)
  - a test written from each EARS line, carrying its tag (`S-012/1`)
  - `prefect` fails a numbered line that has no tagged test, with a grep and no model (decision 009)
  - `examiner` judges only whether each tagged test really checks its line
- A break-the-code test audit (mutate the code and expect a test to fail) is a **v2** candidate.

### 7.2 Report template (every user-facing message)
```
What happened: <one or two plain sentences>
What I need from you: <nothing | one question>
My recommendation: <one line, with why>
```
The build table:
```
Build finished: 4 stories in 38 min
  S-012 Password reset email     READY     212k tokens
  S-014 Rate-limit reset form    BLOCKED   1 question for you
Next: /accio:owl
```

### 7.3 User touchpoints (decision 005)
- **Ask the user at:**
  - `wand` (design questions)
  - `prophecy` (go)
  - `owl` (accept, reject or drop; answers; push)
- **Never mid-build.**
- **An honest count per iteration:** k grilling questions plus "go" at `prophecy`, typing `/accio:brew`, the run
  permission (once, if "don't ask again" is chosen), and one `owl` batch: about 4 + k. Each second pass adds 2.
  First use also needs a one-time setup: the git hooks, and approving the workflow once with "don't ask again"
  (§ 12.1), plus one snippet to paste in a lefthook or pre-commit repo.
- **Always ask** (at `owl`): push, paid calls above $0, needs-user, safety overrides, a missing hook marker, and
  commands `curfew` denied.

---

## 8. Token cost (I8)

1. **Thin main chat.** Files carry every handoff, and agents return one line or a JSON object. A `brew` run adds
   about 1–2k tokens to the main chat.
2. **Model tiers** as in § 4.2. A fix in round 2 moves up one tier.
3. **Never pay twice.** The patch-id ledger skips work already verified, and checks are scoped to the change. The
   DoD-tag check and the full run before a push are scripts, not agents.
4. **Cache-aware fixes.** Each fix round uses a fresh agent with a short brief, because the subagent cache TTL is
   5 minutes (`platform-facts.md`).
5. **Small baseline.** Descriptions are short, and skill bodies use progressive disclosure. The target is about 2k
   tokens for all accio descriptions, checked with `claude plugin details accio`. Hooks print nothing outside
   accio repos.
6. **Budgets.** Quick has 80k tokens and Story has 400k. Above budget, the build table shows a warning. At 2× the
   budget, the story stops and goes to Blocked. *`agent()` reports no usage (spike S-001), so the 2× stop is the
   agent's `maxTurns`, and `accio-cost` reports the real usage from the transcripts after the run (decision 006).*
7. **Measure.** `accio-cost` reports per story in `owl`, and per iteration in `pensieve`.

---

## 9. Testing and evals (decision 006)

- **Scripts:** `unittest`, with fixtures. These cover stacking in `ready --json`, the `dropped` status, the
  DoD-tag check, and `accio-merge` finding the breaking story.
- **Hooks:** payload tests that pipe JSON in and expect exit 2 or a pass. They cover the safe-alternative text, a
  secret-shaped value that must never be echoed, `curfew`'s claim, its one write exception, its allow list,
  its `cd` rule and its deny on unparseable commands, a caller that isn't an accio agent getting no answer,
  `doc-size`'s 40 KB limit, and a silent exit in a repo without `.accio/`.
- **Native git hooks:** tests in a temp repo with a staged fake key, a force-push to a local bare remote, a push to
  base during a run, from a story worktree, and with and without `CLAUDECODE=1` and the token, a stale lock, and chaining into a husky-style hooks folder.
- **Workflow:** `brew.js` runs with a stubbed `agent()`. Tests cover the cap of 2 rounds, a timeout turning into
  Blocked, the WIP limit of 3, a ledger skip, a judge question, a held-back child, a child skipped when its
  parent is BLOCKED, and the lock released in `finally` when the script throws.
- **Skills:** `claude plugin eval` with free graders (`tool_used`, `regex`, `file_exists`) and
  `--max-cost-usd 2`.
- **CI:** GitHub Actions on macOS and Linux from the first story.

---

## 10. v1 scope (decisions 001 and 009)

**In v1** (about 27 stories):
- the skills `wand`, `sort`, `prophecy`, `owl`, `map` and `vow`
- the workflow `workflows/brew.js`
- every agent
- the hooks `protego`, `fidelius`, `curfew`, `doc-size` and `session-start`
- the native git hooks, with chaining and `verify`
- the scripts except the `pensieve` metrics
- `brew-by-hand`: only for users with workflows off (spike S-001: GO)

**In v1.1:**
- `telescope` (decision 008)
- `reparo` and `lumos`
- the plain output style

**In v2:**
- `pensieve` (retro with flow metrics, proposed rules, and `telescope`'s self-improvement scan)
- an optional weekly `telescope` routine
- a QA/e2e agent
- a deeper `wand` architecture workshop
- dcg and gitleaks integration beyond detection
- `push_mode: "pr"` (team and pull-request flow)

**How accio is built (decision 009).** By hand, in plain Claude sessions, from a lean `docs/BACKLOG.md`.

### Spike S-001: done, verdict GO
`docs/research/spike-s001.md` holds the evidence. In short:
- A plugin workflow runs accio's named agents (`agentType: 'accio:<agent>'`) in worktrees made by accio's script.
- Plugin hooks fire inside those agents, can block, and see the caller's `agent_id` and `agent_type`.
- `CLAUDECODE=1` is set inside them, and `bin/` is on their PATH.
- **No fallback is needed.** `brew-by-hand` is only for users who have workflows switched off.
- The spike also changed the design: accio's hook answers every permission question for its agents, because an
  unanswered prompt hangs a run and `stallMs` doesn't catch it, and agents claim their worktree (decision 010).

---

## 11. Risks and open questions

| Risk | Mitigation |
|---|---|
| Workflow unknowns (named agents, worktrees, usage) | settled by spike S-001: GO (`docs/research/spike-s001.md`) |
| Workflows disabled (`disableWorkflows`) | the command vanishes; `prophecy` and `map` notice the missing `Workflow` tool and point to `brew-by-hand`; a headless run needs `--allowedTools Workflow` |
| An accio agent waits on a permission prompt (the run hangs, and `stallMs` doesn't catch it) | `curfew` answers every tool call for accio's agents; agent tool lists stay short (decision 010) |
| `curfew`'s allow list is too narrow at first | each denial becomes a question at `owl`; "allow from now on" grows `agent_allow` |
| A crash leaves `run/brew.lock` behind and blocks the user's pushes | every status move refreshes the lock; it counts as stale after 30 min, and the hook says so |
| The track score misjudges | risky paths force Story; the user can override in `prophecy` |
| Parallel stories conflict on merge | file boundaries per story; on conflict, back to Ready and rebase |
| A rejected parent wastes its children's build | stacking is capped at 2 levels; children are rebuilt only once the parent is fixed |
| A hook manager hides the native wall | chaining for plain and husky; a snippet for the others; `verify` at every `brew` and `owl` |
| The budgets are guesses | tune them from `accio-cost` after the first two iterations |
| Lore names hurt clarity | every description and report in plain words; a README mapping table |
| Skills cached per session slow dogfooding | test with `claude --plugin-dir`; one source tree published by a script (a second copy drifts) |

---

## 12. Contracts and lifecycle (added after the design review)

### 12.1 One-time setup
`accio-hooks install` runs at the first `wand` or `brew` and installs the native git hooks, chaining into an
existing hook manager where it can (§ 4.5). **It writes no allow rules** to the project's settings, because
`curfew` answers permission questions for accio's agents itself (decision 010). The only other approval is the
workflow launch: the first `/accio:brew` asks once, and "don't ask again" covers later runs.

### 12.2 Who writes what
| File | Written by | When committed |
|---|---|---|
| `design.md`, `decisions/` | `wand`, `vow` (main chat) | at once |
| `stories/<ID>.md` | `quill` (in `sort`); `owl` (status, review notes, answers, drops) | in `sort`; once per iteration at `owl` |
| `iterations/<N>.md` | `prophecy` (plan), `owl` (outcome) | at `prophecy` and at `owl` |
| `board.md` | `accio-board` only | together with the stories |
| `run/status.json` | `accio-board move` (from `portkey`/`prefect`) | never (runtime); `owl` folds it into the story files |
| `run/ledger.tsv` | `accio-ledger` (from `prefect`, `headmaster`) | never |
| `run/main-snapshot` | `prefect` (before and after each story: `git status` and `origin/<base>`) | never |
| `run/brew.lock` | `accio-board lock` / `unlock` (from `portkey`), refreshed by `accio-board move` | never |
| `run/claims.json` | `curfew` (when `house-elf` runs `accio-claim`) | never; cleared when a run starts |
| `run/<ID>/brief.md`, `report.md`, `findings-*.md` | `accio-brief`; `house-elf`; each reviewer | never |
| `run/questions/<ID>.md` | `headmaster` (needs-user), or an agent's `needs override` | never; answers go into the story at `owl` |

**During a build, status lives only in `run/status.json`.** Nothing commits to main while a build runs.

### 12.3 Worktree and branch lifecycle
1. **Create.** `accio-brief` runs `git worktree add <wt>/<ID> -b story/<ID>` from base, or from `story/<parent>`'s
   head for a stacked child. If the branch already exists (a re-run), it reuses the branch and rebases it on base,
   or on the parent's current head.
2. **Rebase conflict.** If the rebase conflicts, the conflict goes into the brief and `house-elf` resolves it as
   part of the story. If it still fails, the story goes to *Blocked*.
3. **Integrate.** At `owl`, `accio-merge` creates `<wt>/integrate-<N>` on `accio/integrate-<N>` from base, merges
   the accepted stories there, and fast-forwards main only after the full checks pass.
4. **Remove.** After the fast-forward, `accio-merge` runs `git worktree remove` and `git branch -d` for each merged
   story and for the integration branch.
5. **Rejected or blocked stories keep their branch** for the next pass. **Dropped stories** lose their worktree but
   keep their branch.

### 12.4 Ledger key
```
key = sha256(work digest + sha(config.checks) + panel-id + sha(story DoD section))
work digest = sha256(tree at `from` + the exact diff from..head, from plumbing with display settings off)
from = merge-base with base, or the parent's head for a stacked child
```
- **Invalidation:** the key changes automatically when the diff (any byte, whitespace included), the base it starts
  from, the checks, the reviewer panel or the DoD changes. A rebase onto a moved base therefore re-runs the checks.
  A worktree with uncommitted work can't be keyed (S-006 review).
  A rejection at `owl` also deletes the entry.
- **`reparo` (v1.1):** it has no story file, so it gets an ID of the form `Q-<n>`, used only in the ledger.

### 12.5 Agent reply schemas (enums)
| Agent | Reply |
|---|---|
| `house-elf` | `status ∈ {DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, BLOCKED}` |
| `prefect` | `{pass: bool, failing: [check], skipped: bool, out_of_bounds: [path], untagged: [dod-id], main_changed: [path], remote_moved: bool}` |
| reviewers | `{verdict ∈ {pass, fail}, counts: {critical, major, minor}, path}` |
| `headmaster` | `{kind ∈ {ruling, question}, text, path}` |

**Findings file:** a Markdown list. Each item holds a severity, a confidence (0–100), `file:line`, the claim, the
failure scenario, and the DoD line it concerns (its tag, if any). The exact template is defined in the first review
story.

### 12.6 Crash recovery
A story whose status in `run/status.json` is *Doing* but which has no live run gets resumed by the next `brew`:
- at step 3 (check) if its branch has commits after its base (base, or the parent's head)
- at step 1 (prepare) otherwise

Checkpoint commits make this safe. A new run clears `run/claims.json`, so a resumed story's fresh `house-elf`
claims again. An `accio/integrate-<N>` branch left by a crash at `owl` is deleted and rebuilt;
main was never touched.
