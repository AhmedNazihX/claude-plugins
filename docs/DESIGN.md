# accio: design

Status: draft for approval · Date: 2026-10-17 · Owner: Ahmed N. Ali

Sources:
- `intent.md`
- `docs/research/analysis.md`, `build-engine.md`, `platform-facts.md`
- decisions `docs/decisions/001`–`008`

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

### Goals (each traced to intent.md, I1–I8)
- **I1:** Cover the lifecycle: design → planning → iteration planning → build → review/QA → retro.
- **I2:** Work in agile iterations inspired by Lean Kanban: pull, WIP limits, and an explicit "done".
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

### Foreman's failures this design must not repeat (F1–F4)
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
| P4 | **Magic names, plain words.** The output uses one report template; decisions follow the `decisions.md` format; `lumos` re-explains anything (decision 007). | F4, I4 |
| P5 | **Verification decides "done".** Checks, an independent spec review, and a ledger keyed to the exact diff decide it, not the agent's claim. | I7, F2 |
| P6 | **Effects are guarded, not text.** Native git hooks are the wall; the Claude hooks are narrow early warnings (decision 004). | I6 |
| P7 | **The main chat coordinates and never does the work.** Every handoff is a file, and every agent returns one line or a small JSON object. Scripts come before agents. | I8, F4 |
| P8 | **State lives on disk.** Any session can be cleared and resumed from `.accio/` and git. | F2 |
| P9 | **Grill at the decision points, not everywhere.** Grilling happens in `wand` (design) and `prophecy` (iteration DoDs), one question at a time, each with a recommendation. | I5, F3 |

---

## 3. The lifecycle

```
wand ──► sort ──► ┌──────────── one iteration ─────────────┐
(design) (backlog) │ prophecy ──► brew ──► owl ──► (pensieve)│ ──► next iteration
                   │ (plan, go)  (build)  (review)  (retro v2)│
                   └─────────────────────────────────────────┘
any time: map (board) · reparo (quick fix) · lumos (explain) · vow (record a decision) · telescope (research)
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
The design is split into story files (§ 5). Each story gets:
- deps
- a file boundary (the files it may touch)
- a risk flag
- a DoD in EARS form ("WHEN … THE SYSTEM SHALL …"), so each line maps to a test

A script computes a complexity score from the files touched, the risk paths and any new dependencies. The score
sets the track, and it auto-splits any story above the Story threshold. `examiner` checks the backlog for stories
that aren't atomic, DoDs that can't be checked, and missing deps. Its findings are fixed in the same skill run.
Unless something is truly ambiguous, the user sees only the summary.

### 3.3 Iteration planning: `prophecy` (checkpoint 1)
1. **Propose the batch:** up to 8 ready stories, pulled in dependency and value order, with their tracks.
   `telescope` (decision 008) adds sourced "better way?" notes to stories where it finds a maintained library,
   a simpler pattern or a known pitfall.
2. **Grill the open questions** for the batch: unclear DoDs, missing decisions, whether to take each
   "better way?" note. One question at a time, in the
   `decisions.md` format. Low-stakes defaults are bundled into one confirmation.
3. **Wait for "go".** The user can override any track or drop any story.

Once the user says go, the stories move to *Ready*, and the plugin tells the user to type `/accio:brew`.

### 3.4 Build: `brew` → `workflows/build.js`
This is the unattended part. The full spec is in `docs/research/build-engine.md`, section "Option C in detail".

| Step | Agent | Model | Rule |
|---|---|---|---|
| 0 load | (script via a Haiku agent) | Haiku | `board ready --json`, in dependency order |
| 1 prepare | `portkey` | Haiku | the script creates the worktree and branch `story/<ID>` and writes `brief.md` |
| 2 implement | `house-elf` | Sonnet; Opus if complex or risky | reads only the brief; test-first; checkpoint commits; `report.md`; returns a status |
| 3 check | `prefect` | Haiku | the ledger skips a patch-id that already passed; checks are scoped to the change |
| 4 review | `examiner` + `professor` (+ `auror` on risky paths); Quick track: 1 combined reviewer | Sonnet | read-only; review package as a file; confidence ≥ 80 |
| 5 judge | `headmaster` | Sonnet | only when a finding conflicts with the story, or on NEEDS_CONTEXT; rules it, or marks the story needs-user |
| 6 fix | a fresh `house-elf` | one tier up in round 2 | **≤ 2 rounds**; the re-review covers only the fix diff, and only the reviewers that raised findings run |
| 7 outcome | (script) | — | READY → *Review*; otherwise *Blocked*, with one plain question |

At most 3 stories are in progress at once. A `stallMs` timeout turns a silent agent into a failure. The run returns
one table (§ 7.2) of about 1–2k tokens.

### 3.5 Review and QA: `owl` (checkpoint 2)
For each READY story, the plugin shows:
- what changed
- how to try it
- its risks
- its token cost

The user answers everything in one batch:
- accept or reject each story
- answer the collected questions (needs-user stories, overrides, paid calls)
- confirm the push

Accepted stories merge into local main in dependency order. The merge script re-runs the checks only if main moved
since the verdict. Rejected and answered stories return to *Ready*.

### 3.6 Retro: `pensieve` (v2)
Reports the tokens per story and per iteration, the cycle time and the throughput, and lists findings that came
back more than once. `telescope` scans new Claude Code features and ecosystem plugins for improvements to accio
itself and writes proposals to `.accio/research/`. It never changes accio on its own. It proposes rules (in the style of hookify) and records accepted ones with `vow`.

### 3.7 Any time
- `map`: the board, generated by a script.
- `reparo`: a quick fix outside an iteration. One `house-elf` and one combined reviewer run as plain subagents,
  with no workflow. They follow the same safety rules and the same ledger.
- `lumos`: re-explains the last step, an option or a term in simpler words.
- `vow`: writes `.accio/decisions/NNN-<slug>.md`.
- `telescope <topic>`: on-demand research (`seeker`, about 30–60k tokens per run).

---

## 4. Components

**Every agent returns one line or a schema-bound JSON object. Full reports go to files.**

### 4.1 Skills
Each skill keeps its SKILL.md under about 80 lines, with details in `references/` (decision 006).

| Skill | Phase | User-facing? |
|---|---|---|
| `wand` | design | yes |
| `sort` | planning | yes (summary) |
| `prophecy` | iteration planning, checkpoint 1 | yes |
| `brew` | build launcher | yes (one command) |
| `owl` | review, checkpoint 2 | yes |
| `map` | board | yes |
| `reparo` | quick fix | yes |
| `lumos` | explain | yes |
| `vow` | decision record | yes |
| `telescope` | research for better ways (prophecy, pensieve, on demand) | yes (notes) |
| `pensieve` | retro (v2) | yes |

### 4.2 Agents
| Agent | Role | Model | Tools | Returns |
|---|---|---|---|---|
| `seeker` | researcher (live docs, code facts, better ways via `telescope`) | Sonnet | Read, Grep, Glob, WebSearch, WebFetch | `findings: <path>` |
| `wandmaker` | architect, 2–3 options | Opus | read-only | `options: <path>` |
| `portkey` | worktree and brief | Haiku | Bash (scripts only) | `{worktree, brief, base}` |
| `house-elf` | implementer | Sonnet / Opus | all, inside its worktree | `{status, head, report}` |
| `prefect` | checks, ledger | Haiku | Bash | `{pass, failing[], skipped}` |
| `examiner` | spec reviewer and backlog checker | Sonnet | read-only plus Write to its findings path | `{verdict, counts, path}` |
| `professor` | quality reviewer | Sonnet | same as examiner | same |
| `auror` | security reviewer (risky paths) | Sonnet | same as examiner | same |
| `headmaster` | judge | Sonnet | read-only plus Write to the ledger | `{ruling | question}` |
| `librarian` | doc lookups, quotes only | Haiku | Read, Grep | quotes with `file:line` |

### 4.3 Workflow
- `workflows/build.js`: the § 3.4 pipeline.
- Tested with a stubbed `agent()`.

### 4.4 Hooks
| Hook | Event | Does |
|---|---|---|
| `protego` | PreToolUse Bash | blocks a short list: `reset --hard`, `clean -f`, `rm -rf` outside the repo, `--no-verify`, `core.hooksPath` changes, branch delete; each block names the safe alternative; defers to dcg if installed |
| `fidelius` | PreToolUse Write/Edit | blocks key-shaped values; never echoes the secret |
| `doc-size` | PreToolUse Read | blocks a whole-file read of `.md` files over a size limit and points to `librarian` |
| `session-start` | SessionStart | injects ≤ 10 lines: the board summary, the next step and the plain-words rule (plugins can't ship rules) |

### 4.5 Native git hooks
`accio` installs these into each project with `bin/accio-hooks install`, which is run by `wand` or on first `brew`:
- **`pre-commit`:** a secret scan, with gitleaks if installed and built-in patterns otherwise.
- **`pre-push`:** blocks force-push and a direct push to the base branch.

### 4.6 Scripts
All scripts are in `bin/`, use only the Python 3 standard library, and end up on the Bash PATH.

| Script | Does |
|---|---|
| `accio-board` | parse stories → board.md, `ready --json`, `status`, `move` |
| `accio-brief` | story → brief.md (template); fix brief from findings |
| `accio-ledger` | patch-id verdicts, `check`, `record` |
| `accio-score` | complexity score → track, split hint |
| `accio-merge` | merge accepted stories in dependency order, re-check if main moved |
| `accio-cost` | sums `usage` from agent transcripts per story and iteration |
| `accio-hooks` | install or verify the native git hooks |

### 4.7 Output style (optional)
`output-styles/plain.md` holds the plain-words rule for users who want it always on.

---

## 5. State: `.accio/` (committed unless marked otherwise)

```
.accio/
  design.md                 # from wand
  decisions/NNN-<slug>.md   # from vow
  research/<date>-<topic>.md # from telescope
  stories/<ID>.md           # one per story
  board.md                  # GENERATED by accio-board — never hand-edit
  iterations/<N>.md         # plan + outcome per iteration
  config.json               # checks, risky paths, budgets, base branch
  run/                      # gitignored: ledger.tsv, briefs, reports, findings, worktrees
```

### 5.1 Story file
```markdown
---
id: S-012
title: Password reset email
track: story            # quick | story | feature
status: ready           # backlog | ready | doing | review | done | blocked
deps: [S-010]
files: [src/auth/reset.ts, src/auth/reset.test.ts]
risk: auth
budget_tokens: 400000
---
## Context
<why, links to design.md section>
## Definition of Done
- [ ] WHEN a user requests a reset THE SYSTEM SHALL email a single-use link valid 30 min
- [ ] checks pass: `npm test`, `npm run lint`
## Blocked question
<filled by headmaster when needed>
```

### 5.2 `config.json` (kept small)
| Key | Holds |
|---|---|
| `base_branch` | the base branch |
| `checks` | the check commands, each with a file glob |
| `risky_paths` | glob paths that force the Story track |
| `budgets` | per-track token budgets (quick, story) |
| `wip` | 3 |
| `iteration_max` | 8 |
| `paid_call_cap_usd` | 0 |

A missing key falls back to its default.

---

## 6. Safety model (decision 004)

| Layer | Stops | Bypass |
|---|---|---|
| `pre-commit` (native) | secrets in staged files | `--no-verify` (blocked by protego) |
| `pre-push` (native) | force-push, a direct push to base | `--no-verify` (blocked) |
| `protego` (Claude) | a short destructive list, early with an alternative | wrapping the command (accepted: the git hooks are the wall) |
| `fidelius` (Claude) | secret values in Write/Edit | — |
| One-time override | — | the user grants it for one exact command in one folder; it is logged |

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
- **QA in v1:** the project's checks plus a test written from each EARS line. A UI or e2e check is a project
  `checks` entry. A dedicated QA agent is a v2 candidate.

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
  - `owl` (accept, answers, push)
- **Never mid-build.**
- **Always ask** (at `owl`): push, paid calls above $0, needs-user, safety overrides.

---

## 8. Token cost (I8)

1. **Thin main chat.** Files carry every handoff, and agents return one line or a JSON object. A `brew` run adds
   about 1–2k tokens to the main chat.
2. **Model tiers** as in § 4.2. A fix in round 2 moves up one tier.
3. **Never pay twice.** The patch-id ledger skips work already verified, and checks are scoped to the change.
4. **Cache-aware fixes.** Each fix round uses a fresh agent with a short brief, because the subagent cache TTL is
   5 minutes (`platform-facts.md`).
5. **Small baseline.** Descriptions are short, and skill bodies use progressive disclosure. The target is about 2k
   tokens for all accio descriptions, checked with `claude plugin details accio`.
6. **Budgets.** Quick has 80k tokens and Story has 400k. Above budget, the build table shows a warning. At 2× the
   budget, the story stops and goes to Blocked.
7. **Measure.** `accio-cost` reports per story in `owl`, and per iteration in `pensieve`.

---

## 9. Testing and evals (decision 006)

- **Scripts:** `unittest`, with fixtures.
- **Hooks:** payload tests that pipe JSON in and expect exit 2 or a pass. They cover the safe-alternative text and a
  secret-shaped value that must never be echoed.
- **Native git hooks:** tests in a temp repo with a staged fake key and a force-push to a local bare remote.
- **Workflow:** `build.js` runs with a stubbed `agent()`. Tests cover the cap of 2 rounds, a timeout turning into
  Blocked, the WIP limit of 3, a ledger skip, and a judge question.
- **Skills:** `claude plugin eval` with free graders (`tool_used`, `regex`, `file_exists`) and
  `--max-cost-usd 2`.
- **CI:** GitHub Actions on macOS and Linux from the first story.

---

## 10. v1 scope (decision 001)

**In v1:**
- `wand`, `sort`, `prophecy`, `brew` and `workflows/build.js`, `owl`, `map`, `reparo`, `lumos`, `vow`, `telescope`
- all agents except any v2 QA agent
- `protego`, `fidelius`, `doc-size` and `session-start`
- the native git hooks
- the scripts except the `pensieve` metrics
- the plain output style

**In v2:**
- `pensieve` (retro with flow metrics, proposed rules, and `telescope`'s self-improvement scan)
- an optional weekly `telescope` routine
- a QA/e2e agent
- a deeper `wand` architecture workshop
- dcg and gitleaks integration beyond detection

### The first story is a spike (S-001)
The spike must prove two things:
1. A plugin workflow can call accio's named agents.
2. A plugin workflow can run them in a worktree created by a script.

It also checks two more points:
- whether `agent()` reports token usage
- how the opt-in and permission prompt behave when a user types `/accio:brew`

**Fallbacks**, in order:
1. The script creates the worktree and the agent prompt is loaded from its file.
2. As a last resort, the `brew` skill runs the same steps as plain subagents, superpowers-style.

---

## 11. Risks and open questions

| Risk | Mitigation |
|---|---|
| Workflow unknowns (named agents, worktrees, usage) | S-001 spike with defined fallbacks |
| Workflow disabled (`disableWorkflows`) or a headless run needs an allow rule | the `brew` skill detects this and runs the fallback controller |
| The track score misjudges | risky paths force Story; the user can override in `prophecy` |
| Parallel stories conflict on merge | file boundaries per story; on conflict, back to Ready and rebase |
| The budgets are guesses | tune them from `accio-cost` after the first two iterations |
| Lore names hurt clarity | every description and report in plain words; a README mapping table |
| Skills cached per session slow dogfooding | test with `claude --plugin-dir`; one source tree published by a script (foreman's drift lesson) |
