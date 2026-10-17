# Research analysis: orchestration-workflow plugin

Date: 2026-10-17. Inputs: `intent.md`, the user's earlier plugin **foreman** (v0.12, `~/Workspace/claude-plugins/foreman`),
the plugins installed on this machine, and a web scan of the Claude Code ecosystem.

Two notes on the sources:
- Star counts come from third-party trackers and the date in brackets is when they were read. Treat them as rough.
- Foreman is used **only for inspiration**. This plugin is new and does not build on it.

---

## 1. What we are building (from intent.md)

A plugin that runs production software work from start to finish:
1. Choose the tech stack and design the architecture.
2. Plan the work and break it down.
3. Implement it.
4. Review it and test it (QA).

It works in agile, Lean-Kanban iterations. Each iteration is planned with the user. The plugin asks the user something only when it really needs to, and it explains each step and each option in simple words. It grills decisions until the user and the plugin agree on the design and the Definition of Done (DoD). It uses git, and it guards against destructive commands and leaked secrets. Stories are built by agent workflows, using current practice.

**Constraint added during research:** keep the token cost low.

---

## 2. Lessons from foreman

### 2.1 Why foreman failed (the user's own words)
1. **Too much ceremony.** Too many steps, documents and review rounds before anything shipped.
2. **Review loops and stuck agents.** Re-checks that never settled, agents that stalled, and work in flight that was hard to track.
3. **Too many prompts.** It stopped to ask the user too often, or asked questions that were hard to answer.
4. **Hard to understand.** Steps, options and output were full of jargon.

### 2.2 Evidence of each failure

| Failure | Evidence |
|---|---|
| Ceremony | The planning flow ran `next` → `kickoff` → `work-breakdown` → `backlog-reviewer` → `setup` → `guardrails` → `readiness-auditor` → `status` → `story-start` → `story-finish` → `handover`, which is 11 steps before and around each story. The backlog for improving foreman itself grew to 45 stories (`docs/BACKLOG.md`, 659 lines). Each story needed DoD verification, a test audit, a diff review and a security review. |
| Review loops | Q3 needed 3 security fix rounds, and Q7 and Q10 found new guard bypasses in every round (`.remember` notes, 2026-10-16/17). Reviewers stalled for hours on the guard branches (`foreman/HANDOVER.md`). Q7/Q8 re-checks had to be stopped. |
| Stuck agents | A worker cut off by a usage limit left 32 uncommitted files, and nothing noticed (`docs/DESIGN.md:13`). Agent IDs only work in the session that launched them. The reaper and watch stories (R5–R7) were never built. |
| Prompts | A decision was needed for every merge, push, triage drop and fix-round escalation. The orchestrator asked even for "merge now?" between stories. |
| Hard to understand | The skills are dense prose full of special cases: `story-finish` is 215 lines and `story-start` is 179. The config has 20+ keys (`lanes`, `gates`, `isolation`, `post_merge`, …). |

### 2.3 What worked and is worth keeping (as ideas, not code)
- **Stories that stand alone.** Each story lists Deps, Type, Context, Input, Output and a DoD that can be checked. A script computes the critical path and the waves (`foreman/skills/work-breakdown/references/`, `scripts/backlog_model.py`).
- **Independent reviewers, each starting with a fresh context.**
  - The reviewer is told the story's intent before it reads the diff.
  - `test-auditor` deliberately breaks the code and checks that a test fails.
  - `security-reviewer` judges the change against the project's own threat model.
- **Findings are triaged into Act on / Consider / Dismissed**, and only the user may drop a finding.
- **Decisions are put to the user as one question at a time**, with a recommendation. Real choices get a decision record.
- **Kickoff stress-tests requirements.** Every requirement is challenged and deleted if nobody owns it. Library facts come from live docs, and a capability is treated as unavailable until proven.
- **Context hygiene.** `doc-reader` (Haiku) answers questions about long docs with quotes, and `doc-guard` blocks reading oversized Markdown whole.
- **Worker durability.** Workers make WIP checkpoint commits, and a verdict ledger keyed by patch-id records what passed.
- **Block messages always name the way through.** Every guard says what to do instead.

### 2.4 Technical lessons
- **Guards that parse command text lose the arms race.** Every review round of `worker-guard.sh` (313 lines) found new bypasses: aliases, `--git-dir`, `sh -c`, `GIT_DIR=`, stuck options (`BACKLOG.md` Q7 notes). The planned fix, Q12 (compare refs before and after a command), was never merged.
  → **Check the effect instead:** native git hooks plus a check of the refs before and after.
- **The shell side of `doc-guard` was dropped** after three rounds of parsing still found bypasses (CHANGELOG 0.5.0).
  → Guard what the tool *does*, and guard only the tools that can be guarded exactly.
- **A subagent with `isolation: worktree` can't take over a dirty worktree.** `--continue` only works on committed branches (`HANDOVER.md`).
  → Commit WIP checkpoints often.
- **Skills and agent files are cached per session** (`DESIGN.md:262`), so a change only shows up in a new session. This slows down dogfooding.
- **The release copy drifted** away from the working tree.
  → Keep one source and publish it from a script.
- **CI failed on Linux** (`test-guards.sh`, cause unknown) and was then removed.
  → Make the tests portable from day one.

---

## 3. Token cost

### 3.1 Foreman's cost lessons

| Lesson | Source | Response in the new plugin |
|---|---|---|
| Every worker and reviewer report landed whole in the main session, so its context kept filling up. | `DESIGN.md:15`; R2 and R3 never built | Reports are written to disk. Each agent returns a single line, and a workflow script (not the main chat) reads the agent output. |
| The dod-verifier reran 10–20 minutes of checks on a change that touched only docs, because no record said which commit had already passed. | `DESIGN.md:17`; R11 | A verdict ledger keyed by patch-id, so an unchanged diff is never checked again. Checks are scoped to the kind of change. |
| A worker left idle past the 5-minute prompt-cache window, holding 150K+ tokens, rewrote its whole context to the cache when resumed. | CHANGELOG 0.8.0 | Resume an agent only while its cache is warm. Otherwise start a fresh agent with a short fix brief. |
| `dod-verifier` and `test-auditor` on Sonnet gave the same verdicts as Opus on paired stories, across about 420 reviewer runs. | CHANGELOG 0.8.0 | Assign a model tier to each agent by its job. |
| CI watching moved from an agent to `gh run watch`. | CHANGELOG 0.8.0 | If a script can do the job, use a script, not an agent. |
| Long docs read whole flooded the context. | CHANGELOG 0.5.0 | A cheap lookup agent returns quotes, and a guard blocks reading oversized `.md` files whole. |
| Launch briefs were written by hand every time. | R13 | A script builds each brief from the story file. |
| Stories took 3 or more review rounds. | Q3, Q7, Q10 | Cap fix rounds and use reviewers with a narrow focus and a confidence threshold. |
| Skills were long and loaded on every use. | Survey of the local plugins | Keep SKILL.md small, and load the details from `references/` only when needed. |

### 3.2 What the ecosystem reports about cost
- **Superpowers.** In one 12-session test it saved only about 9% on cost, and on simple tasks it used *more* tokens. One user measured 35–40k tokens of baseline context before the first question.
  Sources: [mindstudio](https://www.mindstudio.ai/blog/5-claude-code-skills-cut-token-costs-70-percent-benchmarked), [mcp.directory](https://mcp.directory/blog/superpowers-skill-worth-it-2026).
- **Superpowers 6.0** removed redundant reviewers to cut cost ([towardsai](https://pub.towardsai.net/superpowers-6-0-unpacked-faster-ai-code-review-and-fewer-tokens-5ab40a6c564c)).
- **Spec-driven development** often doesn't pay for itself on bug fixes, refactors and test-writing, according to a 50-ticket benchmark ([uvik](https://uvik.net/blog/spec-driven-development-benchmark/)).
- **GSD** gives every subagent a fresh window and keeps the orchestrator thin, which counters "context rot" ([gittrend](https://gittrend.io/repo/gsd-build/get-shit-done)).
- **The official `code-review` plugin** uses cheap Haiku calls to decide whether a review is needed and to score each finding, and Sonnet for the actual reviews.

### 3.3 Cost principles for the new plugin
1. **The main session coordinates; it doesn't do the work.** It holds state files and one-line summaries, never raw diffs or long logs.
2. **Use a script before an agent.** Status, the board, briefs, the ledger, CI watching and metrics are all scripts.
3. **Assign a model tier by job:**
   - Haiku: lookups, CI, status.
   - Sonnet: workers on normal stories, verifiers and reviewers.
   - Opus: design, architecture and hard judgement only.
4. **Match the review effort to the change.** A small fix gets one cheap check. A risky change gets the full review panel.
5. **Never pay twice for the same verdict.** Verdicts are keyed by patch-id, and checks are scoped to the change.
6. **Stay cache-aware.** Resume an agent only while its cache is warm, and prefer a fresh agent with a short brief when its context is large.
7. **Keep the baseline context small.** Skill and agent descriptions stay short, and their bodies use progressive disclosure.
8. **Measure.** Report the token cost of each story and each iteration from the transcripts' `usage` fields, and show it in the retro.

---

## 4. Ecosystem scan

| # | Tool | Popularity | Core idea | Borrow |
|---|---|---|---|---|
| 1 | [obra/superpowers](https://github.com/obra/superpowers) | ~245–292k ★ [Jul–Sep 2026]; in the official marketplace | Brainstorm, then plan, then execute; TDD enforced; skills trigger each other in a chain | Subagent-driven development: a fresh subagent per task. Two-stage review: does the work match the spec, then is the code good. Workers report a fixed status: DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED. The worker's brief and the reviewer's diff are passed as files (`task-brief`, `review-package`). The cheapest model that fits, escalated in late fix rounds. |
| 2 | Anthropic official: [feature-dev, pr-review-toolkit, code-review, security-guidance, hookify, ralph-loop](https://developertoolkit.ai/en/ecosystem/plugins/anthropic-dev-plugins/) | Bundled with Claude Code | Explorer, then architect (2–3 options), then reviewer. Reviewers with a single concern. Findings scored for confidence, and anything under 80 dropped. Layered security hooks. Rules written in Markdown. A Stop-hook loop with an iteration cap. | Confidence scoring with a fixed rubric and a list of known false positives. Hook `if:` scoping plus background review that wakes Claude only when it finds something. Hookify-style rules users can write themselves, plus a conversation analyzer that proposes rules. Ralph's cap and session-id check. |
| 3 | [GitHub Spec Kit](https://github.github.com/spec-kit/) | ~115k ★ [Jun 2026] | Spec, then plan, then tasks, then implement, plus a "constitution" | A short file of rules that never change. Thoughtworks recommends trimming its templates ([Radar](https://www.thoughtworks.com/es-cl/radar/languages-and-frameworks/github-spec-kit)). |
| 4 | [BMAD Method](https://github.com/bmad-code-org/BMAD-METHOD) | ~49k ★ [Jun 2026] | A chain of personas: Analyst, PM, Architect, Scrum Master, Dev | A story file that stands alone, so the dev agent never needs the planning chat. *Watch out:* it is "operationally intensive" ([hicron](https://hicronsoftware.com/blog/bmad-gsd-ai-assisted-software-dev-work/)). |
| 5 | [GSD](https://github.com/gsd-build/get-shit-done) | ~64k ★ [Jul 2026] | Context engineering against context rot | A thin orchestrator. State lives in files. Subagents get fresh windows. |
| 6 | [Task Master AI](https://github.com/eyaltoledano/claude-task-master) | ~25k ★ | Turns a PRD into tasks with dependencies; `next` picks a ready task | Scores each task's complexity from 1 to 10 and splits any task above a threshold ([docs](https://docs.task-master.dev/command-reference.md)). |
| 7 | [Kiro specs](https://kiro.dev/docs/specs/index) | Commercial IDE | requirements.md (EARS) + design.md + tasks.md; steering files | EARS acceptance criteria ("WHEN … THE SYSTEM SHALL …") that turn straight into tests. A separate, lighter spec type for bug fixes. |
| 8 | [cc-sdd](https://github.com/gotalab/cc-sdd) | — | Kiro-style spec-driven development for Claude Code, with a user approval between phases | `_Boundary:_` and `_Depends:_` notes on each task, so parallel workers know which files they own. |
| 9 | Claude Flow / RuFlo | ~61–67k ★ [Aug 2026] | Swarm topologies and a shared memory | Mostly a warning: it is complex, and it had 308 open issues in Dec 2025 ([goodfirstissue](https://www.goodfirstissue.org/ruvnet/claude-flow)). |
| 10 | claude-swarm / ccswarm | <1k ★ | Role agents, each in its own worktree | Name worktrees after the lane or role. |
| 11 | [wshobson/agents](https://www.heyuan110.com/posts/ai/2026-04-20-wshobson-agents-deep-dive/) | ~34k ★ [Apr 2026] | 84 small plugins | Users install only what they need. A model tier per agent. |
| 12 | VoltAgent awesome-subagents | ~24k ★ | A catalog of 100+ subagents | Each agent lists only the tools it needs; reviewers are read-only. |
| 13 | everything-claude-code | ~234k ★ (doubtful) | Rules, hooks, agents | Short rule files, kept separate from workflow skills. |
| 14 | [vibe-kanban](https://virtuslab.com/blog/ai/vibe-kanban/) | ~28k ★ [Apr 2026] | A Kanban board of agents, one worktree per card, diff review before merge; an MCP server lets agents move cards | The board as the main interface. A pool of ports so parallel dev servers don't clash. |
| 15 | [dcg destructive_command_guard](https://github.com/Dicklesworthstone/destructive_command_guard) | — | A Rust PreToolUse hook that parses commands in context, with 50+ packs of rules | Each block message suggests a safe alternative. The human can grant a one-time allow code, bound to the command and directory, that expires after 24 hours. |
| 16 | [git-guardrails (mattpocock)](https://www.aihero.dev/this-hook-stops-claude-code-running-dangerous-git-commands) | — | A PreToolUse hook that blocks push, `reset --hard`, `clean -f` and similar | A hook test that pipes in a JSON payload and expects exit code 2. *Watch out:* it blocks every push, which is too broad. |
| 17 | [Gitleaks hooks](https://stevekinney.com/courses/self-testing-ai-agents/secret-scanning-with-gitleaks) | — | Scan staged files on `git commit` | Two layers, with a real git pre-commit hook as the backstop. The Claude hook alone has been reported to print an error and still run the command ([#23284](https://github.com/anthropics/claude-code/issues/23284)). |
| 18 | Anthropic engineering: [context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents), [long-running harnesses](https://anthropic.com/engineering/effective-harnesses-for-long-running-agents) | — | An initializer writes a feature list in which every feature starts as failing; a progress file; a commit at the end of every session | Verification decides "done", not the agent's claim. The session can resume from what is on disk. |

### 4.1 Also on this machine
- **The user's secret-guard mod** (`~/Workspace/claude-mods/secret-guard/hooks/patterns.ts`):
  - It decodes JWTs and blocks only `service_role` tokens.
  - It allows passwords in database URLs that point at local hosts, and lets known example values through.
  - It covers Stripe, Google and AWS `ASIA` keys.
  - Its messages never echo the secret.
- **User-level rules and skills:**
  - `~/.claude/rules/decisions.md`: plain words → an example → pros, cons and costs (each kind of cost on its own line, never added together) → a recommendation → one question.
  - `~/.claude/skills/grilling`: a decision tree; facts are looked up by subagents, and decisions belong to the user.
  - `wait-what`: re-explains something in simplified technical English.
  - `tdd`.

---

## 5. Top 12 patterns, ranked for this plugin

1. **A fresh-context worker per story, in its own worktree.** This is the biggest single fix for context rot and cost, and it allows parallel work.
2. **Story files that stand alone,** with a DoD that can be checked and file boundaries, so a worker never needs the planning chat.
3. **A deterministic workflow per story: implement → verify → review → at most N fix rounds → escalate.** The script, not the model, controls retries. This is the direct answer to foreman's review loops.
4. **Verification decides "done".** A story is done when its tests, an independent verifier and a ledger keyed to the exact diff say so, not when the agent claims it.
5. **Review effort matched to the change:**
   - A Quick track for fixes.
   - A Story track for normal work.
   - A Feature track with a design note.
   - Narrow reviewers, each with a confidence threshold.
6. **Fixed points where the user joins in:** iteration planning and iteration review. Between them the plugin runs on its own within WIP limits.
7. **A WIP limit on review, too,** because the human's review time is the real bottleneck ([kanbanzone](https://kanbanzone.com/2026/ai-flow-and-the-limits-of-human-judgment/)).
8. **Layered git safety, checked by effect:**
   - A PreToolUse guard that suggests a safe alternative.
   - Native git hooks for secrets and pushes, as the backstop.
   - A one-time override the human can grant.
9. **A thin orchestrator with state on disk,** so the session can be cleared at any point without losing work.
10. **Plain-language output** with a fixed report template, and decision questions in the `decisions.md` format.
11. **A complexity score that picks the track and splits big stories automatically.**
12. **Measured cost and flow:** tokens per story, cycle time and throughput in the retro, and a retro that proposes new rules.

---

## 6. Pitfalls to design against

| Pitfall | Seen in | Guard in the design |
|---|---|---|
| Ceremony: "reinvented waterfall", 16 acceptance criteria for a small bug | Spec Kit, Kiro, BMAD ([besthub](https://www.besthub.dev/articles/is-spec-driven-development-a-savior-or-a-burden-in-the-age-of-ai-generated-code-859af86e96d5)) | Tracks sized automatically; the Quick track writes no documents |
| Prompt fatigue: users type "just build it" | Superpowers brainstorming | Questions are batched at the iteration-planning point; elsewhere the plugin asks only when blocked |
| Token cost on simple tasks | Superpowers | The Quick track, a small baseline context, and model tiers |
| Agents ignore steering docs or build duplicates | Spec Kit | The worker's brief names existing code to reuse; a reviewer checks the work against the spec |
| Loops that never end | Ralph, foreman | A hard cap on rounds, then escalation in plain words |
| Hooks that don't hold (exit 2 not blocking, or blocking too broadly) | git-guardrails, issue #23284 | Native git hooks as the backstop; tests that pipe in payloads; narrow rules |
| Swarm complexity | Claude Flow | No swarm. A small, fixed set of agents. |
| Doc drift between copies | foreman | One source tree, published by a script |
