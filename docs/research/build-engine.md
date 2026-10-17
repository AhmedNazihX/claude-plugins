# Build engine: a Workflow script vs. subagents driven by a skill

Date: 2026-10-17. This is the input to decision 003.

The question is what drives one story (or a batch of them) from "start" to "ready to merge":
1. implement
2. check
3. review
4. fix rounds
5. result

This comparison is built mainly from the ecosystem scan (`analysis.md` § 4) and the platform facts
(`platform-facts.md`), not from foreman.

## The two options, each at its best

**A. Workflow script.** A JavaScript program in the plugin (`workflows/build.js`) owns the control flow. It calls
`agent()` for each step, uses `parallel()` for the reviewers, and puts the fix-round cap, the timeouts (`stallMs`)
and the structured result (`schema`) in code. The main chat starts it once and gets one consolidated result back.

**B. Subagents driven by a skill.** Done well, this is **not foreman's version.** It is the current
[superpowers](https://github.com/obra/superpowers) `subagent-driven-development` pattern, the most widely used
approach in the ecosystem. The main-chat model is the controller and follows a skill. Superpowers keeps that
controller cheap with these devices:
- **Scripts that hand over work as files.** `task-brief` extracts the task to a file. `review-package` writes the
  diff to a file and prints only its path. In the skill's words: "everything a subagent prints back stays resident
  in your context … hand artifacts over as files".
- **A ledger file** (`progress.md`), so the controller can pick up again after compaction or `/clear`.
- **Policy caps.** There are at most 5 fix rounds. Rounds 1–3 resume the same implementer; rounds 4–5 use a
  fresh one, on a model one tier higher.
- **Fixed status codes:** DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED.
- **Bounded waits.** It waits in stretches of 5–10 minutes and reconciles its live children in between, so a
  stuck child is noticed within minutes.
- **The cheapest model that fits each role**, chosen explicitly. Its rule of thumb: "turn count beats token price".
- **Similar small tasks batched** into one dispatch.

GSD (thin orchestrator, fresh subagent windows) and Anthropic's `code-review` and `feature-dev` commands follow the
same B shape: a skill or command orchestrates, and subagents do the work.

## How the ecosystem actually does it
| Tool | Engine | How it controls loops and cost |
|---|---|---|
| superpowers (~250k+ ★) | B | Caps are written in the skill, plus file handoffs and a ledger |
| GSD (~64k ★) | B | Thin orchestrator; state lives in files |
| BMAD (~49k ★) | B, with manual handoffs between personas | The user starts each step |
| Anthropic code-review / feature-dev | B, a command orchestrating parallel agents | Haiku confidence scoring and fixed phases |
| ralph-loop | A Stop-hook loop (deterministic) | Iteration cap; the exit condition is a completion string |
| Task Master | MCP tools plus the user | `next` picks a task, and the user drives |
| vibe-kanban | An external app | The human reviews every card |
| A Workflow-tool plugin | — | **The scan found no popular public plugin built on the Workflow tool.** It is new. |

**Honest summary:** B is the proven mainstream. A is new, and nobody has proven it at scale. Note that
`intent.md` asks for exactly that: "use workflows with agents when building stories" and "cutting edge" practice.

## Side-by-side

| Dimension | A: Workflow script | B: Skill-driven, superpowers-style |
|---|---|---|
| **Loop control** | **Strong.** The cap and the timeouts are code, so the model can't argue past them. | **Medium.** The caps are instructions. Superpowers allows 5 rounds; foreman ran 3+ rounds with instructions much like these. |
| **Stuck agents** | **Strong.** `stallMs` turns a silent agent into a failure the script sees, and a failed agent returns `null` instead of hanging. | **Medium.** The controller has to notice, using bounded waits and reconciling its children. This works when followed, and relies on the model following it. |
| **Main-chat tokens** | Lowest: one result per run. | Low if the file-handoff discipline holds (each status line ~100–300 tokens). It grows when the controller reads reports to make judgement calls. |
| **Worker tokens** | About the same as B. Each fix round is a fresh `agent()` call with a fix brief, so the implementer's cache is never reused. | Same work. Rounds 1–3 resume the implementer, which is cheap while its cache is warm (5-minute subagent TTL) and expensive after. |
| **Judgement calls** (a finding that conflicts with the plan, a NEEDS_CONTEXT answer) | **Weak.** The script needs an extra "judge" agent or must end the story as blocked, because it can't reason on its own. | **Strong.** The controller rules on conflicts and answers context questions in place. |
| **Asking the user mid-build** | Not possible inside a run. Blocked stories end and are listed for the user afterwards. | Possible, which is also the door to prompt fatigue. |
| **Parallel stories** | Native: `parallel()`, up to 16 agents. | Possible, but superpowers says to never run implementers in parallel, because of conflicts. |
| **Recovery after /clear or a crash** | `resumeFromRunId` works only within the same session, so state on disk is still needed. | A ledger file plus `git log`; proven in superpowers. |
| **Seeing progress** | `/workflows` shows live progress for each agent. | The status lines in chat, plus transcripts. |
| **Portability** | Can be switched off (`disableWorkflows`). Headless use needs an allow rule. Interactive use shows a permission prompt per run, unless "don't ask again" is chosen. | Works anywhere subagents work. |
| **Unknowns** | Can a workflow use the plugin's named agents? Can it run them in worktrees? A spike story answers both, and each has a known fallback. | None. |
| **Maintenance** | JS code with tests, which is deterministic and testable. | Prose in the skill, harder to test (`claude plugin eval` helps). |

## What decides it
- **If the main risk is the model drifting** (looping, stalling, over-asking: foreman's failures 2 and 3), A wins,
  because its guarantees are in code.
- **If the main risk is rigidity** (a story needs a judgement call or an answer mid-build), B wins.
- **Cost is close to a tie** once B uses file handoffs. A's real advantage is control, not tokens.

## Option C: hybrid, a skill outside and a Workflow inside
- **Skills** do everything the user takes part in: planning, grilling, the iteration review, and judgement rulings
  between runs.
- **One Workflow** does the unattended part, building a batch of ready stories.
- **Judgement calls inside a run** are made by a small "judge" agent with a narrow brief, or the story ends as
  BLOCKED with a question that waits for the next touchpoint.
- **Superpowers' devices are reused inside the workflow:** briefs and review packages as files, status codes, model
  per role, and a ledger on disk.
- **Fallback:** if the spike fails, the same skills drive a superpowers-style B loop, and the design doesn't change
  shape.

## Option C in detail

### Who does what
| Part | Runs as | Model | Talks to the user? |
|---|---|---|---|
| Plan an iteration (pick stories, tracks, DoDs, grilling) | skill `plan`, in the main chat | session model (Opus) | yes: the one planned conversation |
| Build the ready stories | workflow `build` (`workflows/build.js`), started by the user typing `/<plugin>:build` | per agent, see below | no |
| Review the iteration, answer blocked questions, merge | skill `review`, in the main chat | session model | yes: the second planned conversation |
| Board, briefs, ledger, merge, cost report | Python scripts in `bin/` | no model | — |

### Inside one `build` run
The workflow's run is a pipeline with a WIP limit: at most 3 stories in progress at once, and the next starts when one
finishes. It goes through these steps:
0. **Load** (Haiku). An agent runs `board ready --json` and returns the list of ready stories, already in
   dependency order. The script itself never reads files; agents do.
1. **Prepare** (Haiku). An agent runs `brief <ID>`. The script creates the worktree
   (`git worktree add … -b story/<ID>`), writes `brief.md` (story text, file boundaries, existing code to reuse,
   checks to run) and records the base commit. The agent returns `{worktree, brief, base}`.
2. **Implement.** The model depends on the track and complexity: Sonnet by default, Opus only for complex or risky
   stories. The agent reads only `brief.md`, works test-first in the worktree, makes checkpoint commits and writes
   `report.md`. It returns `{status: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED, head}`. A `stallMs` timeout
   turns a silent agent into a failure.
3. **Check** (Haiku). An agent runs `ledger check <ID>`. If this exact diff (by patch-id) has already passed, it
   skips. Otherwise it runs only the checks that fit the change (docs only means lint only).
4. **Review**, in parallel. All reviewers are read-only and run on Sonnet. Each reads a `review-package.md` file
   (diff, story and DoD) and writes its findings to a file. Only findings with confidence ≥ 80 count. The panel
   depends on the track:
   - Quick: 1 combined reviewer.
   - Story: a spec reviewer (does the diff meet the DoD, nothing more and nothing less) plus a quality reviewer.
   - Any story touching a risky path also gets a security reviewer.
5. **Judge** (Sonnet). This runs only when it's needed: a finding contradicts the story text, or the implementer
   returned NEEDS_CONTEXT. The judge reads the story and the decision records and then does one of two things:
   - It rules and writes the ruling to the story's ledger.
   - It marks the story `needs-user` with one question written in plain words.
6. **Fix rounds, at most 2.** Each round gets a **fresh** implementer with a short fix brief made of the findings.
   A fresh agent is used because the subagent cache lasts only 5 minutes, so resuming a cold agent would re-process
   its whole context. Round 2 moves up one model tier. After each fix, a scoped re-review checks only the fix diff,
   and only the reviewers that raised findings run again.
7. **Outcome.**
   - **READY:** the ledger records the verdict against the patch-id, and the story moves to *Review* on the board.
   - **BLOCKED** (still failing after round 2, or `needs-user`): the question goes into the story file and the
     story moves to *Blocked*. It never loops a third time.

The run returns one table to the main chat. Each row is a story ID, its outcome, its token cost and the report path.
That is about 1–2k tokens, whatever the number of stories.

### What the user sees
```
/<plugin>:build
Build finished: 4 stories in 38 min
  S-012 Password reset email     READY     212k tokens
  S-013 Reset token expiry       READY     148k tokens
  S-014 Rate-limit reset form    BLOCKED   1 question for you
  S-015 Fix typo on login page   READY      31k tokens
Next: /<plugin>:review  (demo the 3 ready stories, answer 1 question, merge)
```
In `review`, each ready story gets a short "what changed / how to try it / risks" note. You accept or reject each
one, answer the blocked question, and the plugin merges the accepted stories in dependency order. A merge script
re-runs the checks only when main has moved since the verdict. Rejected and answered stories go back to *Ready* for
the next `build` run.

### Edge cases
- **Merge conflicts between parallel stories.** The story file boundaries are meant to prevent them. When one still
  happens, the story goes back to *Ready* and is rebased on the next run.
- **Ad-hoc fix outside an iteration.** The `quick` skill runs one implementer and one reviewer as plain subagents,
  with no workflow.
- **Crash, `/clear`, or a usage limit mid-run.** The ledger and the board on disk say where each story stands. The
  next `build` resumes from the board. A story with commits but no verdict restarts at step 3.
- **Permission prompts.** You see one prompt per `build` run, and "don't ask again" removes it.
- **The spike fails.** If worktrees or named agents don't work inside a workflow, the fallback has two layers:
  - First fallback: the script creates the worktree itself (step 1 already does this), and the agent prompt is
    loaded from the agent file.
  - Last resort: the `build` skill runs these same steps as plain subagents, superpowers-style. The files, the
    scripts and the outcomes stay the same; only the controller changes.
